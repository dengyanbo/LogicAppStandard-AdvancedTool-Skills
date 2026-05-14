"""`ValidateSPConnectivity` — DNS + TCP probe for every Service Provider.

Mirrors `Operations/ValidateServiceProviderConnectivity.cs`. The .NET tool
parses `connections.json`'s `serviceProviderConnections` block, derives
endpoint + port for each provider (15 known types, each with its own
parameter conventions and default port), runs DNS + TCP probes, and prints
a table summarizing results.

The parsing logic is by far the most intricate piece of this command —
each provider type has different parameter names, some endpoints are full
connection strings (Storage, Cosmos, EH, SB, SQL) needing key=value parse,
others are bare hostnames (DB2, MQ, FTP, SMTP). Endpoint values may also
be `@appsetting('NAME')` references requiring env var lookup.
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ..network import resolve, tcp_connect
from ..settings import settings

console = Console()


# ---------------------------------------------------------------------------
# Service Provider type table — drives endpoint + port extraction.
# Aligns with `Enum/Enum.cs::ServiceProviderType`.
# ---------------------------------------------------------------------------

# Auth provider strings as they appear in connections.json -> parameterSetName.
_AUTH_CONN_STR = {"connectionString"}
# Provider types whose endpoint is a bare hostname under a known param name.
# (param_name, port_param, default_port)
_BARE_HOST_PROVIDERS: dict[str, tuple[str, str | None, int | None]] = {
    "DB2": ("serverName", "portNumber", None),
    "Ftp": ("serverAddress", "portNumber", 21),
    "Sftp": ("sshHostAddress", "portNumber", 22),
    "Smtp": ("serverAddress", "port", 587),
    "mq": ("serverName", "portNumber", None),
}
# Provider types whose endpoint is a single URL-style param with a fixed port.
# (param_name, fixed_port)
_URL_PROVIDERS: dict[str, tuple[str, int]] = {
    "eventGridPublisher": ("topicEndpoint", 443),
    "keyVault": ("VaultUri", 443),
}
# Provider types using connection strings — parse via _parse_connection_string.
# (conn_string_key, port_default)
_CONN_STR_PROVIDERS: dict[str, int] = {
    "AzureBlob": 443,
    "AzureFile": 443,
    "azurequeues": 443,
    "azureTables": 443,
    "AzureCosmosDB": 443,
    "eventHub": 443,
    "serviceBus": 5671,
    "sql": 0,  # Port comes from Server=tcp:host,1433 parsing.
}
# All known providers (NotSupported = anything not in this set).
_SUPPORTED_PROVIDERS = (
    set(_BARE_HOST_PROVIDERS) | set(_URL_PROVIDERS) | set(_CONN_STR_PROVIDERS)
)

# Storage suffix matching by provider — used to build `<account>.<svc>.<suffix>`.
_STORAGE_SERVICE_BY_PROVIDER = {
    "AzureBlob": "blob",
    "AzureFile": "file",
    "azurequeues": "queue",
    "azureTables": "table",
}

_APPSETTING_RE = re.compile(r"^@appsetting\('([^']+)'\)$")


@dataclass
class ServiceProvider:
    """Parsed view of one entry in connections.json `serviceProviderConnections`."""

    name: str
    display_name: str
    provider_type: str  # raw type string; "NotSupported" if not in _SUPPORTED_PROVIDERS
    endpoint: str       # bare hostname after stripping scheme/path/port/comma
    port: int
    is_supported: bool
    is_empty: bool      # endpoint resolved to empty string

    @property
    def is_ip(self) -> bool:
        try:
            ip_address(self.endpoint)
            return True
        except ValueError:
            return False


# ---------------------------------------------------------------------------
# Endpoint / port extraction
# ---------------------------------------------------------------------------


def _resolve_appsetting(value: str) -> str:
    """Replace `@appsetting('NAME')` with the corresponding env var value (or '')."""
    if not isinstance(value, str):
        return ""
    m = _APPSETTING_RE.match(value)
    if m:
        return os.environ.get(m.group(1), "") or ""
    return value


def _parse_connection_string(cs: str) -> dict[str, str]:
    """Parse a key=value;key=value;... connection string."""
    out: dict[str, str] = {}
    for chunk in cs.split(";"):
        if not chunk:
            continue
        idx = chunk.find("=")
        if idx == -1:
            continue
        out[chunk[:idx]] = chunk[idx + 1:]
    return out


def _decode_default_endpoint(parameter_values: Mapping[str, object]) -> str:
    """Scan parameterValues for endpoint-like keys, mirroring the .NET DecodeEndpoint."""
    patterns = ("Endpoint", "connectionString", "fullyQualifiedNamespace")
    for key, val in parameter_values.items():
        if not isinstance(val, str):
            continue
        if any(p.lower() in key.lower() for p in patterns):
            return val
    return ""


def _convert_to_base_uri(url: str) -> str:
    """Strip scheme / path / port / commas to obtain a bare hostname."""
    out = url
    for prefix in ("https://", "http://", "sb://", "tcp:"):
        if out.startswith(prefix):
            out = out[len(prefix):]
    # Cut on first /, :, or ,
    for sep in ("/", ":", ","):
        idx = out.find(sep)
        if idx != -1:
            out = out[:idx]
    return out


def _format_storage_endpoint(service: str, raw: str, auth: str) -> str:
    """Storage SPs: parse conn string -> `<AccountName>.<service>.<EndpointSuffix>`."""
    if auth in _AUTH_CONN_STR or auth == "None":
        cs = _parse_connection_string(raw)
        account = cs.get("AccountName")
        suffix = cs.get("EndpointSuffix")
        if account and suffix:
            return f"{account}.{service}.{suffix}"
    return raw


def _format_endpoint(raw: str, provider_type: str, auth: str) -> str:
    """Final endpoint string before _convert_to_base_uri."""
    value = _resolve_appsetting(raw)
    if not value:
        return ""

    if provider_type in _STORAGE_SERVICE_BY_PROVIDER:
        return _format_storage_endpoint(_STORAGE_SERVICE_BY_PROVIDER[provider_type], value, auth)
    if provider_type == "AzureCosmosDB":
        cs = _parse_connection_string(value)
        return cs.get("AccountEndpoint", value)
    if provider_type in ("eventHub", "serviceBus") and auth in _AUTH_CONN_STR:
        cs = _parse_connection_string(value)
        return cs.get("Endpoint", value)
    if provider_type == "sql" and auth in _AUTH_CONN_STR:
        cs = _parse_connection_string(value)
        return cs.get("Server", value)
    return value


def _format_port(raw_port: str, provider_type: str, formatted_endpoint: str) -> int:
    """Resolve port: appsetting -> static rule per provider -> SQL Server parsing."""
    candidate = _resolve_appsetting(raw_port) if raw_port else ""
    if provider_type in _STORAGE_SERVICE_BY_PROVIDER or provider_type == "AzureCosmosDB":
        return 443
    if provider_type == "eventHub":
        return 443
    if provider_type == "serviceBus":
        return 5671
    if provider_type == "sql":
        # SQL Server param is `tcp:host,port` — formatted_endpoint already
        # contains that string. Split on comma.
        parts = formatted_endpoint.split(",")
        if len(parts) >= 2 and parts[1].isdigit():
            return int(parts[1])
        return 1433  # SQL default if unspecified
    if not candidate:
        return 0
    try:
        return int(candidate)
    except ValueError:
        return 0


# ---------------------------------------------------------------------------
# connections.json -> list[ServiceProvider]
# ---------------------------------------------------------------------------


def parse_service_providers(conn_json: Path) -> list[ServiceProvider]:
    """Read connections.json and return one ServiceProvider per entry."""
    if not conn_json.exists():
        raise typer.BadParameter(f"connections.json not found in path: {conn_json}")
    data = json.loads(conn_json.read_text(encoding="utf-8"))
    sp_map = data.get("serviceProviderConnections") or {}
    if not sp_map:
        raise typer.BadParameter("No Service Provider found in connections.json")

    out: list[ServiceProvider] = []
    for name, body in sp_map.items():
        if not isinstance(body, dict):
            continue
        # Provider type lives at serviceProvider.id, last path segment.
        ptype_full = ((body.get("serviceProvider") or {}).get("id") or "")
        ptype = ptype_full.rsplit("/", 1)[-1] if ptype_full else ""
        display = str(body.get("displayName") or name)
        is_supported = ptype in _SUPPORTED_PROVIDERS
        if not is_supported:
            out.append(ServiceProvider(name, display, ptype or "NotSupported", "", 0, False, True))
            continue

        auth = str(body.get("parameterSetName") or "None")
        params = body.get("parameterValues") or {}
        if not isinstance(params, dict):
            params = {}

        # Extract raw endpoint + raw port per provider category.
        if ptype in _BARE_HOST_PROVIDERS:
            host_key, port_key, default_port = _BARE_HOST_PROVIDERS[ptype]
            raw_endpoint = str(params.get(host_key) or "")
            raw_port = ""
            if port_key:
                pv = params.get(port_key)
                raw_port = "" if pv is None else str(pv)
            formatted = _format_endpoint(raw_endpoint, ptype, auth)
            if not formatted:
                out.append(ServiceProvider(name, display, ptype, "", 0, True, True))
                continue
            base = _convert_to_base_uri(formatted)
            port = _format_port(raw_port, ptype, formatted) or (default_port or 0)
            out.append(ServiceProvider(name, display, ptype, base, port, True, False))
            continue

        if ptype in _URL_PROVIDERS:
            param_name, fixed_port = _URL_PROVIDERS[ptype]
            raw_endpoint = str(params.get(param_name) or "")
            formatted = _format_endpoint(raw_endpoint, ptype, auth)
            if not formatted:
                out.append(ServiceProvider(name, display, ptype, "", 0, True, True))
                continue
            base = _convert_to_base_uri(formatted)
            out.append(ServiceProvider(name, display, ptype, base, fixed_port, True, False))
            continue

        # Connection-string-derived providers
        if ptype in _CONN_STR_PROVIDERS:
            raw_endpoint = _decode_default_endpoint(params)
            formatted = _format_endpoint(raw_endpoint, ptype, auth)
            if not formatted:
                out.append(ServiceProvider(name, display, ptype, "", 0, True, True))
                continue
            port = _format_port("", ptype, formatted)
            base = _convert_to_base_uri(formatted)
            out.append(ServiceProvider(name, display, ptype, base, port, True, False))
            continue

        # Should be unreachable given _SUPPORTED_PROVIDERS gate.
        out.append(ServiceProvider(name, display, ptype, "", 0, False, True))
    return out


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------


@dataclass
class _ValidationOutcome:
    dns_status: str
    ip: str
    tcp_status: str


def _validate(sp: ServiceProvider) -> _ValidationOutcome:
    if sp.is_empty:
        return _ValidationOutcome("EmptyEndpoint", "", "EmptyEndpoint")
    if sp.is_ip:
        ok = tcp_connect(sp.endpoint, sp.port, timeout=1.0)
        return _ValidationOutcome("Skipped", sp.endpoint, "Succeeded" if ok else "Failed")
    ips = resolve(sp.endpoint)
    if not ips:
        return _ValidationOutcome("Failed", "", "Skipped")
    ip = ips[0]
    ok = tcp_connect(ip, sp.port, timeout=1.0)
    return _ValidationOutcome("Succeeded", ip, "Succeeded" if ok else "Failed")


def _print_provider_listing(title: str, providers: Iterable[ServiceProvider]) -> None:
    typer.echo(title)
    table = Table(show_header=True, header_style="bold")
    table.add_column("Reference Name")
    table.add_column("Display Name")
    for sp in providers:
        table.add_row(sp.name, sp.display_name)
    console.print(table)


def validate_sp_connectivity(
    root: Path = typer.Option(
        None, "--root",
        help=(
            "wwwroot path containing connections.json. "
            f"Defaults to LAT_ROOT_FOLDER env var or {settings.root_folder}."
        ),
    ),
) -> None:
    """DNS + TCP connectivity probe for every Service Provider in connections.json."""
    root_path = root or settings.root_folder
    conn_path = root_path / "connections.json"

    typer.echo("connections.json found, reading Service Provider information.")
    providers = parse_service_providers(conn_path)
    typer.echo(f"Found {len(providers)} Service Provider(s) in connections.json.")

    empty = [p for p in providers if p.is_supported and p.is_empty]
    unsupported = [p for p in providers if not p.is_supported]
    valid = [p for p in providers if p.is_supported and not p.is_empty]

    if empty:
        _print_provider_listing(
            "Cannot find Endpoint for following Service Provider(s), "
            "please verify appsettings or connections.json.",
            empty,
        )
    if unsupported:
        _print_provider_listing(
            "Following service provider(s) not supported yet.", unsupported
        )

    typer.echo(
        f"Found {len(valid)} validate Service Provider(s), "
        "testing DNS resolution and tcp connection."
    )

    result_table = Table(show_header=True, header_style="bold")
    for col in ("Name", "Display Name", "DNS Status", "IP", "Port", "Connection Status"):
        result_table.add_column(col)
    for sp in valid:
        outcome = _validate(sp)
        result_table.add_row(
            sp.name,
            sp.display_name,
            outcome.dns_status,
            outcome.ip or "N/A",
            str(sp.port),
            outcome.tcp_status,
        )
    console.print(result_table)


def register(validate_app: typer.Typer) -> None:
    validate_app.command(
        "sp-connectivity",
        help="DNS + TCP probe for every Service Provider in connections.json.",
    )(validate_sp_connectivity)
