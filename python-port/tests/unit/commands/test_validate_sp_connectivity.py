"""Tests for `lat validate sp-connectivity`."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from lat.cli import app
from lat.commands import validate_sp_connectivity as mod
from lat.commands.validate_sp_connectivity import (
    _convert_to_base_uri,
    _decode_default_endpoint,
    _format_endpoint,
    _format_port,
    _parse_connection_string,
    _resolve_appsetting,
    parse_service_providers,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_connections_json(tmp_path: Path, providers: dict[str, dict[str, Any]]) -> Path:
    data = {"serviceProviderConnections": providers, "managedApiConnections": {}}
    p = tmp_path / "connections.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _sp(provider_id: str, display_name: str, parameter_set: str, parameter_values: dict) -> dict:
    return {
        "serviceProvider": {"id": f"/serviceProviders/{provider_id}"},
        "displayName": display_name,
        "parameterSetName": parameter_set,
        "parameterValues": parameter_values,
    }


@pytest.fixture()
def stub_network(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    """Replace DNS/TCP with deterministic stubs keyed by host."""
    resolved: dict[str, list[str]] = {}
    tcp_ok: set[str] = set()

    def fake_resolve(host: str) -> list[str]:
        return resolved.get(host, [])

    def fake_tcp(ip: str, port: int, timeout: float = 1.0) -> bool:
        return f"{ip}:{port}" in tcp_ok

    monkeypatch.setattr(mod, "resolve", fake_resolve)
    monkeypatch.setattr(mod, "tcp_connect", fake_tcp)
    return {"resolved": resolved, "tcp_ok": tcp_ok}  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_parse_connection_string_basic() -> None:
    cs = "Endpoint=sb://x.servicebus.windows.net/;SharedAccessKeyName=k;SharedAccessKey=v"
    parsed = _parse_connection_string(cs)
    assert parsed == {
        "Endpoint": "sb://x.servicebus.windows.net/",
        "SharedAccessKeyName": "k",
        "SharedAccessKey": "v",
    }


def test_parse_connection_string_storage_format() -> None:
    cs = "DefaultEndpointsProtocol=https;AccountName=acct;AccountKey=k;EndpointSuffix=core.windows.net"
    parsed = _parse_connection_string(cs)
    assert parsed["AccountName"] == "acct"
    assert parsed["EndpointSuffix"] == "core.windows.net"


def test_parse_connection_string_skips_empty_and_malformed() -> None:
    parsed = _parse_connection_string("AccountName=acct;;invalid_chunk;AccountKey=k")
    assert parsed == {"AccountName": "acct", "AccountKey": "k"}


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://example.com/path", "example.com"),
        ("sb://my.servicebus.windows.net/", "my.servicebus.windows.net"),
        ("tcp:server.database.windows.net,1433", "server.database.windows.net"),
        ("plainhost", "plainhost"),
        ("plainhost:8080", "plainhost"),
        ("https://x.y.z/api?q=1", "x.y.z"),
    ],
)
def test_convert_to_base_uri(raw: str, expected: str) -> None:
    assert _convert_to_base_uri(raw) == expected


def test_resolve_appsetting_passthrough() -> None:
    assert _resolve_appsetting("plain-value") == "plain-value"


def test_resolve_appsetting_env_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_ENDPOINT", "https://resolved.example")
    assert _resolve_appsetting("@appsetting('MY_ENDPOINT')") == "https://resolved.example"


def test_resolve_appsetting_missing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISSING_SETTING", raising=False)
    assert _resolve_appsetting("@appsetting('MISSING_SETTING')") == ""


def test_decode_default_endpoint_picks_endpoint_key() -> None:
    params = {
        "policyName": "RootManageSharedAccessKey",
        "myEndpoint": "sb://my-ns.servicebus.windows.net/",
        "extra": "irrelevant",
    }
    assert _decode_default_endpoint(params) == "sb://my-ns.servicebus.windows.net/"


def test_decode_default_endpoint_picks_connection_string_key() -> None:
    params = {
        "blobConnectionString": "AccountName=foo;EndpointSuffix=core.windows.net",
    }
    assert _decode_default_endpoint(params) == "AccountName=foo;EndpointSuffix=core.windows.net"


# ---------------------------------------------------------------------------
# Endpoint / port formatting per provider type
# ---------------------------------------------------------------------------


def test_format_endpoint_azureblob_connection_string() -> None:
    raw = "DefaultEndpointsProtocol=https;AccountName=acct;AccountKey=k;EndpointSuffix=core.windows.net"
    assert _format_endpoint(raw, "AzureBlob", "connectionString") == "acct.blob.core.windows.net"


def test_format_endpoint_azurefile_with_none_auth() -> None:
    """File auth is 'None' in connections.json; storage formatter applies."""
    raw = "AccountName=acct;EndpointSuffix=core.windows.net"
    assert _format_endpoint(raw, "AzureFile", "None") == "acct.file.core.windows.net"


def test_format_endpoint_cosmosdb_connection_string() -> None:
    raw = "AccountEndpoint=https://my-cosmos.documents.azure.com:443/;AccountKey=k"
    assert _format_endpoint(raw, "AzureCosmosDB", "connectionString").startswith(
        "https://my-cosmos.documents.azure.com"
    )


def test_format_endpoint_eventhub_connection_string() -> None:
    raw = "Endpoint=sb://my-eh.servicebus.windows.net/;SharedAccessKeyName=key"
    assert _format_endpoint(raw, "eventHub", "connectionString") == "sb://my-eh.servicebus.windows.net/"


def test_format_endpoint_sql_connection_string() -> None:
    raw = "Server=tcp:srv.database.windows.net,1433;Database=db;User Id=u;Password=p"
    assert _format_endpoint(raw, "sql", "connectionString") == "tcp:srv.database.windows.net,1433"


def test_format_port_storage_returns_443() -> None:
    assert _format_port("", "AzureBlob", "acct.blob.core.windows.net") == 443
    assert _format_port("443", "AzureFile", "acct.file.core.windows.net") == 443


def test_format_port_servicebus_returns_5671() -> None:
    assert _format_port("", "serviceBus", "sb://x.servicebus.windows.net/") == 5671


def test_format_port_sql_parses_from_server_string() -> None:
    """SQL Server param is `tcp:host,port` — we split on comma to get port."""
    assert _format_port("", "sql", "tcp:srv.database.windows.net,1433") == 1433


def test_format_port_sql_falls_back_to_default() -> None:
    assert _format_port("", "sql", "tcp:srv.database.windows.net") == 1433


def test_format_port_appsetting_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FTP_PORT", "2121")
    assert _format_port("@appsetting('FTP_PORT')", "Ftp", "ftp.example.com") == 2121


# ---------------------------------------------------------------------------
# parse_service_providers
# ---------------------------------------------------------------------------


def test_parse_service_providers_blob_with_connection_string(tmp_path: Path) -> None:
    cs = "DefaultEndpointsProtocol=https;AccountName=acct;AccountKey=k;EndpointSuffix=core.windows.net"
    conn = _make_connections_json(
        tmp_path,
        {"blob1": _sp("AzureBlob", "Blob 1", "connectionString", {"connectionString": cs})},
    )
    providers = parse_service_providers(conn)
    assert len(providers) == 1
    sp = providers[0]
    assert sp.provider_type == "AzureBlob"
    assert sp.endpoint == "acct.blob.core.windows.net"
    assert sp.port == 443
    assert sp.is_supported
    assert not sp.is_empty


def test_parse_service_providers_keyvault(tmp_path: Path) -> None:
    conn = _make_connections_json(
        tmp_path,
        {
            "kv1": _sp(
                "keyVault", "KV 1", "ManagedServiceIdentity",
                {"VaultUri": "https://my-kv.vault.azure.net/"},
            )
        },
    )
    providers = parse_service_providers(conn)
    assert providers[0].endpoint == "my-kv.vault.azure.net"
    assert providers[0].port == 443


def test_parse_service_providers_ftp_default_port(tmp_path: Path) -> None:
    conn = _make_connections_json(
        tmp_path,
        {"ftp1": _sp("Ftp", "FTP 1", "None", {"serverAddress": "ftp.example.com"})},
    )
    providers = parse_service_providers(conn)
    assert providers[0].endpoint == "ftp.example.com"
    assert providers[0].port == 21


def test_parse_service_providers_sftp_explicit_port(tmp_path: Path) -> None:
    conn = _make_connections_json(
        tmp_path,
        {
            "sftp1": _sp(
                "Sftp", "SFTP 1", "None",
                {"sshHostAddress": "sftp.example.com", "portNumber": 2222},
            )
        },
    )
    providers = parse_service_providers(conn)
    assert providers[0].endpoint == "sftp.example.com"
    assert providers[0].port == 2222


def test_parse_service_providers_servicebus(tmp_path: Path) -> None:
    cs = "Endpoint=sb://my-sb.servicebus.windows.net/;SharedAccessKeyName=key"
    conn = _make_connections_json(
        tmp_path,
        {"sb1": _sp("serviceBus", "SB 1", "connectionString", {"connectionString": cs})},
    )
    providers = parse_service_providers(conn)
    sp = providers[0]
    assert sp.endpoint == "my-sb.servicebus.windows.net"
    assert sp.port == 5671


def test_parse_service_providers_sql(tmp_path: Path) -> None:
    cs = "Server=tcp:srv.database.windows.net,1433;Database=db;User Id=u;Password=p"
    conn = _make_connections_json(
        tmp_path,
        {"sql1": _sp("sql", "SQL 1", "connectionString", {"sqlConnectionString": cs})},
    )
    providers = parse_service_providers(conn)
    sp = providers[0]
    assert sp.endpoint == "srv.database.windows.net"
    assert sp.port == 1433


def test_parse_service_providers_unsupported_type(tmp_path: Path) -> None:
    conn = _make_connections_json(
        tmp_path,
        {"weird1": _sp("brand-new-thing", "Weird 1", "None", {})},
    )
    providers = parse_service_providers(conn)
    assert providers[0].is_supported is False
    assert providers[0].is_empty is True


def test_parse_service_providers_empty_endpoint_appsetting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Endpoint references missing app-setting => empty."""
    monkeypatch.delenv("MISSING_KV", raising=False)
    conn = _make_connections_json(
        tmp_path,
        {
            "kv1": _sp(
                "keyVault", "KV missing", "ManagedServiceIdentity",
                {"VaultUri": "@appsetting('MISSING_KV')"},
            )
        },
    )
    providers = parse_service_providers(conn)
    assert providers[0].is_supported is True
    assert providers[0].is_empty is True


def test_parse_service_providers_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(Exception):  # typer.BadParameter
        parse_service_providers(tmp_path / "missing.json")


def test_parse_service_providers_empty_block_raises(tmp_path: Path) -> None:
    p = tmp_path / "connections.json"
    p.write_text(json.dumps({"serviceProviderConnections": {}}), encoding="utf-8")
    with pytest.raises(Exception):
        parse_service_providers(p)


# ---------------------------------------------------------------------------
# CLI end-to-end
# ---------------------------------------------------------------------------


def test_cli_dns_succeeds_tcp_ok(tmp_path: Path, stub_network: dict) -> None:
    resolved = stub_network["resolved"]
    tcp_ok = stub_network["tcp_ok"]
    resolved["my-kv.vault.azure.net"] = ["20.1.2.3"]
    tcp_ok.add("20.1.2.3:443")
    _make_connections_json(
        tmp_path,
        {
            "kv1": _sp(
                "keyVault", "KV 1", "ManagedServiceIdentity",
                {"VaultUri": "https://my-kv.vault.azure.net/"},
            )
        },
    )
    result = runner.invoke(app, ["validate", "sp-connectivity", "--root", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    assert "Found 1 Service Provider(s)" in result.stdout
    assert "20.1.2.3" in result.stdout
    assert "Succeeded" in result.stdout


def test_cli_dns_fails_skips_tcp(tmp_path: Path, stub_network: dict) -> None:
    _make_connections_json(
        tmp_path,
        {
            "kv1": _sp(
                "keyVault", "KV 1", "ManagedServiceIdentity",
                {"VaultUri": "https://does-not-resolve.example/"},
            )
        },
    )
    result = runner.invoke(app, ["validate", "sp-connectivity", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "Failed" in result.stdout
    assert "Skipped" in result.stdout


def test_cli_ip_address_endpoint_skips_dns(tmp_path: Path, stub_network: dict) -> None:
    """When endpoint is already an IP, DNS column is Skipped."""
    stub_network["tcp_ok"].add("10.0.0.5:21")
    _make_connections_json(
        tmp_path,
        {"ftp1": _sp("Ftp", "FTP 1", "None", {"serverAddress": "10.0.0.5"})},
    )
    result = runner.invoke(app, ["validate", "sp-connectivity", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "Skipped" in result.stdout
    assert "10.0.0.5" in result.stdout


def test_cli_unsupported_lists_in_warning_section(tmp_path: Path, stub_network: dict) -> None:
    _make_connections_json(
        tmp_path,
        {
            "x": _sp("UnknownThing", "X provider", "None", {}),
            "kv1": _sp(
                "keyVault", "KV 1", "ManagedServiceIdentity",
                {"VaultUri": "https://my-kv.vault.azure.net/"},
            ),
        },
    )
    stub_network["resolved"]["my-kv.vault.azure.net"] = ["1.2.3.4"]
    stub_network["tcp_ok"].add("1.2.3.4:443")
    result = runner.invoke(app, ["validate", "sp-connectivity", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "not supported yet" in result.stdout
    assert "X provider" in result.stdout
    # Valid provider should still be probed
    assert "my-kv.vault.azure.net" in result.stdout or "1.2.3.4" in result.stdout
