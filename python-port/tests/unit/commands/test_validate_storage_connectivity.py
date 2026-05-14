"""Tests for `lat validate storage-connectivity`."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from lat.cli import app
from lat.commands import validate_storage_connectivity as mod
from lat.commands.validate_storage_connectivity import (
    _is_private_endpoint,
    _parse_connection_string,
    _StorageConnInfo,
)

runner = CliRunner()


_FAKE_CS = (
    "DefaultEndpointsProtocol=https;"
    "AccountName=mystorage;"
    "AccountKey=fakekey==;"
    "EndpointSuffix=core.windows.net"
)
_FAKE_FILE_CS = (
    "DefaultEndpointsProtocol=https;"
    "AccountName=fileacct;"
    "AccountKey=fk==;"
    "EndpointSuffix=core.windows.net"
)


@pytest.fixture()
def fake_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AzureWebJobsStorage", _FAKE_CS)
    monkeypatch.setenv("WEBSITE_OWNER_NAME", "sub+region")
    monkeypatch.setenv("REGION_NAME", "East US")


@pytest.fixture()
def stub_network(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"dns": {}, "tcp_ok": set(), "auth_status": "Succeeded"}

    def fake_resolve(host: str) -> list[str]:
        return state["dns"].get(host, [])

    def fake_tcp(ip: str, port: int, timeout: float = 1.0) -> bool:
        return f"{ip}:{port}" in state["tcp_ok"]

    def fake_auth(conn: _StorageConnInfo) -> str:
        return state["auth_status"]

    monkeypatch.setattr(mod, "resolve", fake_resolve)
    monkeypatch.setattr(mod, "tcp_connect", fake_tcp)
    monkeypatch.setattr(mod, "_auth_check", fake_auth)
    return state


@pytest.fixture()
def stub_service_tag(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    """Stub _storage_service_tag_prefixes to return a configurable list."""
    state: dict[str, list[str]] = {"prefixes": ["20.0.0.0/8"]}

    def fake_prefixes(region: str) -> list[str]:
        return list(state["prefixes"])

    monkeypatch.setattr(mod, "_storage_service_tag_prefixes", fake_prefixes)
    return state


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_parse_connection_string_keys() -> None:
    parsed = _parse_connection_string(_FAKE_CS)
    assert parsed["AccountName"] == "mystorage"
    assert parsed["EndpointSuffix"] == "core.windows.net"


def test_is_private_endpoint_ip_in_public_range() -> None:
    assert _is_private_endpoint("20.1.2.3", ["20.0.0.0/8"]) == "No"


def test_is_private_endpoint_ip_outside_public_range() -> None:
    assert _is_private_endpoint("10.0.0.5", ["20.0.0.0/8"]) == "Yes"


def test_is_private_endpoint_skipped_without_prefixes() -> None:
    assert _is_private_endpoint("20.1.2.3", []) == "Skipped"


def test_is_private_endpoint_skipped_on_invalid_ip() -> None:
    assert _is_private_endpoint("not-an-ip", ["20.0.0.0/8"]) == "Skipped"


def test_storage_endpoint_url_construction() -> None:
    info = _StorageConnInfo("acct", "core.windows.net", "Blob", _FAKE_CS)
    assert info.endpoint == "acct.blob.core.windows.net"
    assert _StorageConnInfo("acct", "core.windows.net", "Queue", _FAKE_CS).endpoint == "acct.queue.core.windows.net"
    assert _StorageConnInfo("acct", "core.windows.net", "Table", _FAKE_CS).endpoint == "acct.table.core.windows.net"
    assert _StorageConnInfo("acct", "core.windows.net", "File", _FAKE_CS).endpoint == "acct.file.core.windows.net"


# ---------------------------------------------------------------------------
# CLI end-to-end
# ---------------------------------------------------------------------------


def test_all_endpoints_succeed(fake_env: None, stub_network: dict, stub_service_tag: dict) -> None:
    # Resolve each of Blob/Queue/Table to an IP in the public Storage range
    stub_network["dns"] = {
        "mystorage.blob.core.windows.net": ["20.1.1.1"],
        "mystorage.queue.core.windows.net": ["20.2.2.2"],
        "mystorage.table.core.windows.net": ["20.3.3.3"],
    }
    stub_network["tcp_ok"] = {"20.1.1.1:443", "20.2.2.2:443", "20.3.3.3:443"}

    result = runner.invoke(app, ["validate", "storage-connectivity"])
    assert result.exit_code == 0, result.stdout
    # mystorage account name should appear in output
    assert "mystorage" in result.stdout
    # All four columns of Succeeded/No appear
    assert "Succeeded" in result.stdout
    assert "No" in result.stdout  # all IPs in public range -> No PE


def test_file_share_added_when_env_set(
    fake_env: None,
    stub_network: dict,
    stub_service_tag: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WEBSITE_CONTENTAZUREFILECONNECTIONSTRING", _FAKE_FILE_CS)
    stub_network["dns"]["fileacct.file.core.windows.net"] = ["20.4.4.4"]
    stub_network["tcp_ok"] = {"20.4.4.4:443"}

    result = runner.invoke(app, ["validate", "storage-connectivity"])
    assert result.exit_code == 0, result.stdout
    assert "fileacct" in result.stdout
    assert "Successfully retrieved Storage Account information" in result.stdout


def test_file_share_warning_when_env_missing(
    fake_env: None, stub_network: dict, stub_service_tag: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("WEBSITE_CONTENTAZUREFILECONNECTIONSTRING", raising=False)
    result = runner.invoke(app, ["validate", "storage-connectivity"])
    assert result.exit_code == 0
    assert "validation will be skipped for file share service" in result.stdout
    # Only 3 service rows expected (Blob/Queue/Table); no fileacct
    assert "fileacct" not in result.stdout


def test_dns_failure_marks_row_failed(
    fake_env: None, stub_network: dict, stub_service_tag: dict
) -> None:
    # No DNS entries -> every host returns []
    result = runner.invoke(app, ["validate", "storage-connectivity"])
    assert result.exit_code == 0
    assert "Failed" in result.stdout


def test_tcp_failure_skips_auth(
    fake_env: None, stub_network: dict, stub_service_tag: dict
) -> None:
    stub_network["dns"] = {"mystorage.blob.core.windows.net": ["20.1.1.1"]}
    # No tcp_ok entries — TCP will fail
    stub_network["auth_status"] = "Succeeded"  # would succeed if called
    result = runner.invoke(app, ["validate", "storage-connectivity"])
    assert result.exit_code == 0
    # Auth column should be NotApplicable because TCP failed (rich may truncate to NotAppli…)
    assert "NotAppli" in result.stdout


def test_pe_detection_ip_outside_public_range(
    fake_env: None, stub_network: dict, stub_service_tag: dict
) -> None:
    stub_service_tag["prefixes"] = ["1.0.0.0/8"]  # narrow range, no real IPs match
    stub_network["dns"] = {
        "mystorage.blob.core.windows.net": ["10.0.0.5"],
        "mystorage.queue.core.windows.net": ["10.0.0.6"],
        "mystorage.table.core.windows.net": ["10.0.0.7"],
    }
    stub_network["tcp_ok"] = {"10.0.0.5:443", "10.0.0.6:443", "10.0.0.7:443"}
    result = runner.invoke(app, ["validate", "storage-connectivity"])
    assert result.exit_code == 0
    assert "Yes" in result.stdout  # private endpoint detected


def test_missing_connection_string_aborts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AzureWebJobsStorage", raising=False)
    result = runner.invoke(app, ["validate", "storage-connectivity"])
    assert result.exit_code != 0


def test_skip_pe_check_flag(
    fake_env: None, stub_network: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--skip-pe-check skips the service-tag lookup entirely."""
    # If service-tag lookup is invoked, it would raise.
    def boom(region: str) -> list[str]:
        raise AssertionError("service-tag lookup should not be called")

    monkeypatch.setattr(mod, "_storage_service_tag_prefixes", boom)
    stub_network["dns"] = {
        "mystorage.blob.core.windows.net": ["20.1.1.1"],
        "mystorage.queue.core.windows.net": ["20.1.1.2"],
        "mystorage.table.core.windows.net": ["20.1.1.3"],
    }
    stub_network["tcp_ok"] = {"20.1.1.1:443", "20.1.1.2:443", "20.1.1.3:443"}
    result = runner.invoke(app, ["validate", "storage-connectivity", "--skip-pe-check"])
    assert result.exit_code == 0
    assert "Skipped" in result.stdout
