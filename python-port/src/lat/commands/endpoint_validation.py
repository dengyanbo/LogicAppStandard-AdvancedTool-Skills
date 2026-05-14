"""`EndpointValidation` — DNS + TCP + SSL probe for any HTTPS/HTTP endpoint.

Mirrors `Operations/EndpointValidation.cs`. Output is a single table with
columns: Name Resolution | IP | TCP connection | SSL connection.
"""
from __future__ import annotations

from urllib.parse import urlparse

import typer
from rich.console import Console
from rich.table import Table

from ..network import resolve, ssl_probe, tcp_connect

console = Console()


def _parse_endpoint(endpoint: str) -> tuple[str, str, int]:
    """Return (scheme, host, port) tuple.

    Mirrors C# logic: assume HTTPS:443 by default; HTTP:80 if explicit scheme.
    Strip path and trailing slashes from the host. If the URL has an explicit
    port (e.g. example.com:8443) that overrides the default.
    """
    if "://" not in endpoint:
        endpoint = "https://" + endpoint
    parsed = urlparse(endpoint)
    scheme = parsed.scheme.lower()
    host = parsed.hostname or ""
    if not host:
        raise typer.BadParameter(f"Could not extract host from endpoint: {endpoint!r}")
    if parsed.port:
        port = parsed.port
    else:
        port = 80 if scheme == "http" else 443
    return scheme, host, port


def endpoint_validation(
    url: str = typer.Option(
        ..., "-url", "--url",
        help="HTTP(S) endpoint to validate (e.g. https://example.com).",
    ),
) -> None:
    """DNS + TCP + SSL handshake check for any HTTP(S) endpoint."""
    scheme, host, port = _parse_endpoint(url)

    if scheme == "http":
        typer.echo(
            f"The endpoint {url} you provide is Http protocol, "
            "SSL certificate validation will be skipped."
        )
        ssl_status = "Skipped"
    else:
        result = ssl_probe(host, port)
        ssl_status = "Succeeded" if result.ok else "Failed"

    ips = resolve(host)
    dns_status = "Succeeded" if ips else "Failed"

    table = Table(show_header=True, header_style="bold")
    table.add_column("Name Resolution")
    table.add_column("IP")
    table.add_column("TCP connection")
    table.add_column("SSL connection")

    if not ips:
        table.add_row("Failed", "N/A", "NotApplicable", "NotApplicable")
    else:
        for ip in ips:
            tcp_status = "Succeeded" if tcp_connect(ip, port, timeout=1.0) else "Failed"
            table.add_row(dns_status, ip, tcp_status, ssl_status)

    console.print(table)


def register(validate_app: typer.Typer) -> None:
    validate_app.command(
        "endpoint",
        help="DNS + TCP + SSL handshake check for any HTTP(S) endpoint.",
    )(endpoint_validation)
