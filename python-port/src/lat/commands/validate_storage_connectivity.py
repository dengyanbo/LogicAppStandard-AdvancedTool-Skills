"""`ValidateStorageConnectivity` — DNS/TCP/auth check for each storage endpoint.

Mirrors `Operations/ValidateStorageConnectivity.cs`. For each of the four
storage services (Blob/Queue/Table/File), the command:

  1. Resolves the canonical endpoint hostname (account.<service>.suffix).
  2. DNS resolves it.
  3. Opens a TCP socket on :443.
  4. Calls the matching Azure SDK `get_service_properties()` to verify the
     connection string / key actually authenticates.
  5. Tags the endpoint as private (PE) if its IP falls outside Microsoft's
     public "Storage" service tag prefixes — same heuristic as the .NET tool.

The .NET tool had a subtle bug where `IsPrivateEndpoint` was always
overwritten to "No" after the loop body; the Python port fixes that
(uses `else` on the for-loop so we only mark No when no match was found).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from ipaddress import ip_address, ip_network

import typer
from azure.data.tables import TableServiceClient
from azure.mgmt.network import NetworkManagementClient
from azure.storage.blob import BlobServiceClient
from azure.storage.fileshare import ShareServiceClient
from azure.storage.queue import QueueServiceClient
from rich.console import Console
from rich.table import Table

from ..auth import credential
from ..network import resolve, tcp_connect
from ..settings import settings

console = Console()

# Service name -> URL segment used in `<account>.<svc>.<suffix>`.
_SERVICE_URL_SEGMENT = {
    "Blob": "blob",
    "Queue": "queue",
    "Table": "table",
    "File": "file",
}


@dataclass
class _StorageConnInfo:
    account_name: str
    endpoint_suffix: str
    service: str  # 'Blob' | 'Queue' | 'Table' | 'File'
    connection_string: str

    @property
    def endpoint(self) -> str:
        return f"{self.account_name}.{_SERVICE_URL_SEGMENT[self.service]}.{self.endpoint_suffix}"


@dataclass
class _ValidationResult:
    conn: _StorageConnInfo
    dns_status: str = "NotApplicable"
    ips: list[str] = field(default_factory=list)
    tcp_status: str = "NotApplicable"
    auth_status: str = "NotApplicable"
    is_private_endpoint: str = "Skipped"  # Yes / No / Skipped


def _parse_connection_string(cs: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for chunk in cs.split(";"):
        if not chunk:
            continue
        idx = chunk.find("=")
        if idx == -1:
            continue
        out[chunk[:idx]] = chunk[idx + 1:]
    return out


def _build_validators(
    main_cs: str | None, file_cs: str | None
) -> list[_StorageConnInfo]:
    """Construct one _StorageConnInfo per service, returning [] if main_cs missing."""
    if not main_cs:
        return []
    parsed = _parse_connection_string(main_cs)
    account = parsed.get("AccountName") or ""
    suffix = parsed.get("EndpointSuffix") or "core.windows.net"

    out = [
        _StorageConnInfo(account, suffix, svc, main_cs)
        for svc in ("Blob", "Queue", "Table")
    ]
    if file_cs:
        file_parsed = _parse_connection_string(file_cs)
        out.append(
            _StorageConnInfo(
                file_parsed.get("AccountName") or account,
                file_parsed.get("EndpointSuffix") or suffix,
                "File",
                file_cs,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Service tag lookup (for PE detection)
# ---------------------------------------------------------------------------


def _network_client() -> NetworkManagementClient:
    sub = settings.subscription_id
    if not sub:
        raise RuntimeError(
            "WEBSITE_OWNER_NAME is required to look up Storage service tag IPs."
        )
    return NetworkManagementClient(credential(), sub)


def _storage_service_tag_prefixes(region: str) -> list[str]:
    """IPv4 prefixes for the global 'Storage' service tag."""
    tags = _network_client().service_tags.list(region.lower())
    for value in tags.values or []:
        if value.name == "Storage":
            return [
                p for p in (value.properties.address_prefixes or []) if "." in p
            ]
    return []


def _is_private_endpoint(ip: str, public_prefixes: list[str]) -> str:
    """Return 'Yes' / 'No' / 'Skipped' based on whether IP is outside public Storage IPs."""
    if not public_prefixes:
        return "Skipped"
    try:
        addr = ip_address(ip)
    except ValueError:
        return "Skipped"
    for prefix in public_prefixes:
        try:
            net = ip_network(prefix, strict=False)
        except ValueError:
            continue
        if addr in net:
            # IP is in public range -> NOT a private endpoint
            return "No"
    return "Yes"


# ---------------------------------------------------------------------------
# SDK auth probe — test seam for unit tests
# ---------------------------------------------------------------------------


def _auth_check(conn: _StorageConnInfo) -> str:
    """Use the matching Azure SDK client to verify auth via get_service_properties."""
    try:
        if conn.service == "Blob":
            BlobServiceClient.from_connection_string(
                conn.connection_string
            ).get_service_properties()
        elif conn.service == "Queue":
            QueueServiceClient.from_connection_string(
                conn.connection_string
            ).get_service_properties()
        elif conn.service == "Table":
            TableServiceClient.from_connection_string(
                conn.connection_string
            ).get_service_properties()
        elif conn.service == "File":
            ShareServiceClient.from_connection_string(
                conn.connection_string
            ).get_service_properties()
        else:
            return "NotApplicable"
        return "Succeeded"
    except Exception:  # noqa: BLE001 - mirror .NET catch-all
        return "Failed"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def validate_storage_connectivity(
    region: str = typer.Option(
        None, "--region",
        help=f"Region for the Storage service-tag lookup. Defaults to {settings.region}.",
    ),
    skip_pe_check: bool = typer.Option(
        False, "--skip-pe-check",
        help="Skip the public/private endpoint detection (no MI subscription Reader).",
    ),
) -> None:
    """DNS + TCP + auth probe for every storage service endpoint."""
    main_cs = settings.connection_string
    if not main_cs:
        raise typer.BadParameter(
            "AzureWebJobsStorage is not set; cannot validate storage connectivity."
        )
    file_cs = settings.file_share_connection_string

    validators = _build_validators(main_cs, file_cs)
    if file_cs:
        typer.echo(
            "Successfully retrieved Storage Account information from environment variables."
        )
    else:
        typer.echo(
            "Cannot retrieve connection string of Storage - File Share, "
            "validation will be skipped for file share service.\n"
            "If you are NOT using ASEv3, please verify "
            "WEBSITE_CONTENTAZUREFILECONNECTIONSTRING in your appsettings."
        )

    public_prefixes: list[str] = []
    if not skip_pe_check:
        target_region = (region or settings.region or "").replace(" ", "")
        if not target_region:
            typer.echo(
                "Region not set, public/private endpoint detection will be skipped."
            )
        else:
            try:
                public_prefixes = _storage_service_tag_prefixes(target_region)
                if public_prefixes:
                    typer.echo(
                        "IP list of Storage Account service tag has been retrieved successfully."
                    )
            except Exception:  # noqa: BLE001
                typer.echo(
                    "Failed to fetch service tag of Storage, "
                    "public/private IP validation will be skipped."
                )

    results: list[_ValidationResult] = []
    for conn in validators:
        result = _ValidationResult(conn=conn)
        ips = resolve(conn.endpoint)
        if ips:
            result.dns_status = "Succeeded"
            result.ips = ips
            # Probe TCP for each IP (use first only — matches C# assumption).
            tcp_ok = tcp_connect(ips[0], 443, timeout=1.0)
            result.tcp_status = "Succeeded" if tcp_ok else "Failed"
            if tcp_ok:
                result.auth_status = _auth_check(conn)
            if public_prefixes:
                result.is_private_endpoint = _is_private_endpoint(ips[0], public_prefixes)
        else:
            result.dns_status = "Failed"
        results.append(result)

    table = Table(show_header=True, header_style="bold")
    for col in (
        "Storage Name", "Type", "DNS Resolution",
        "Endpoint IP", "Is PE", "TCP Conn", "Authentication",
    ):
        table.add_column(col)
    for r in results:
        table.add_row(
            r.conn.account_name,
            r.conn.service,
            r.dns_status,
            " ".join(r.ips) if r.ips else "N/A",
            r.is_private_endpoint,
            r.tcp_status,
            r.auth_status,
        )
    console.print(table)


def register(validate_app: typer.Typer) -> None:
    validate_app.command(
        "storage-connectivity",
        help="DNS + TCP + auth probe for every backing storage service endpoint.",
    )(validate_storage_connectivity)
