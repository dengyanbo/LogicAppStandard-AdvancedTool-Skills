"""DNS / TCP / SSL validators — mirrors Shared/NetworkValidator.cs.

See references/08-network-validation.md.
"""
from __future__ import annotations

import socket
import ssl
from dataclasses import dataclass, field
from datetime import datetime


def resolve(host: str) -> list[str]:
    try:
        return sorted({sa[4][0] for sa in socket.getaddrinfo(host, None)})
    except socket.gaierror:
        return []


def tcp_connect(ip: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


@dataclass
class SslProbeResult:
    ok: bool
    error: str | None = None
    subject: str | None = None
    issuer: str | None = None
    not_after: datetime | None = None
    san_match: bool | None = None
    san_dns: list[str] = field(default_factory=list)


def ssl_probe(host: str, port: int = 443, timeout: float = 5.0) -> SslProbeResult:
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((host, port), timeout=timeout) as raw:
            with ctx.wrap_socket(raw, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
                subject = dict(x[0] for x in cert["subject"]).get("commonName", "")
                issuer = dict(x[0] for x in cert["issuer"]).get("commonName", "")
                not_after = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
                san_dns = [v for k, v in cert.get("subjectAltName", []) if k == "DNS"]
                san_match = any(_san_match(host, p) for p in san_dns)
                return SslProbeResult(
                    ok=True,
                    subject=subject,
                    issuer=issuer,
                    not_after=not_after,
                    san_match=san_match,
                    san_dns=san_dns,
                )
    except ssl.SSLCertVerificationError as e:
        return SslProbeResult(ok=False, error=str(e))
    except OSError as e:
        return SslProbeResult(ok=False, error=str(e))


def _san_match(host: str, pattern: str) -> bool:
    if pattern == host:
        return True
    if pattern.startswith("*."):
        suffix = host.split(".", 1)[1] if "." in host else host
        return pattern[2:] == suffix
    return False
