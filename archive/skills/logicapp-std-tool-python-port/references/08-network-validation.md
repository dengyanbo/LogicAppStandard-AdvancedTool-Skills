# Reference 08 — Network Validation (DNS / TCP / SSL)

`ValidateStorageConnectivity`, `ValidateSPConnectivity`, and
`EndpointValidation` all rely on the same primitive validators in
`Shared/NetworkValidator.cs`. The Python port should expose them as a
single `lat/network.py` module.

## 1. C# source

`Shared/NetworkValidator.cs`:

* `DNSValidator` — lines 16–44
* `SocketValidator` — lines 46–85
* `SSLValidator` — lines 87–155 (uses an `EventListener` on
  `Private.InternalDiagnostics.System.Net.Http` to capture cert errors)
* `StorageValidator` — lines 157–203 (auth-level probe against the four
  storage services)
* `ValidationStatus` enum in `Enum/Enum.cs`

## 2. Behavior in detail

### 2.1 `DNSValidator.Validate()`

```csharp
IPs = Dns.GetHostAddresses(Endpoint);   // host:port stripped — caller passes hostname only
Result = Succeeded;
```

Python:

```python
import socket

def resolve(host: str) -> list[str]:
    try:
        return list({sa[4][0] for sa in socket.getaddrinfo(host, None)})
    except socket.gaierror:
        return []
```

### 2.2 `SocketValidator.Validate()`

* Tries `TcpClient.ConnectAsync(ip, port).Wait(1000)` → 1-second timeout.
* Result is `Succeeded` if and only if the connect completes within 1 s.

Python:

```python
import socket
def tcp_connect(ip: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False
```

### 2.3 `SSLValidator.Validate()`

The .NET implementation is unusual: it triggers an HTTPS GET, captures
internal diagnostic events from `Private.InternalDiagnostics.System.Net.Http`
via an `EventListener`, and looks for the string `RemoteCertificateNameMismatch`
to detect cert problems. This is brittle — *don't* port this approach to
Python. Instead, do an explicit TLS handshake and inspect the cert chain
using stdlib `ssl`:

```python
import ssl, socket
from dataclasses import dataclass
from datetime import datetime

@dataclass
class SslProbeResult:
    ok: bool
    error: str | None = None
    subject: str | None = None
    issuer: str | None = None
    not_after: datetime | None = None
    san_match: bool | None = None


def ssl_probe(host: str, port: int = 443, timeout: float = 5.0) -> SslProbeResult:
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((host, port), timeout=timeout) as raw:
            with ctx.wrap_socket(raw, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
                # cert dict format documented in `ssl.SSLSocket.getpeercert`
                not_after = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
                subject = dict(x[0] for x in cert["subject"]).get("commonName", "")
                issuer = dict(x[0] for x in cert["issuer"]).get("commonName", "")
                san_dns = [v for k, v in cert.get("subjectAltName", []) if k == "DNS"]
                san_match = any(_match_san(host, p) for p in san_dns)
                return SslProbeResult(ok=True, subject=subject, issuer=issuer,
                                      not_after=not_after, san_match=san_match)
    except ssl.SSLCertVerificationError as e:
        return SslProbeResult(ok=False, error=str(e))
    except OSError as e:
        return SslProbeResult(ok=False, error=str(e))


def _match_san(host: str, pattern: str) -> bool:
    # RFC 6125 §6.4.3 wildcard match for left-most label
    if pattern == host:
        return True
    if pattern.startswith("*."):
        h_suffix = host.split(".", 1)[1] if "." in host else host
        return pattern[2:] == h_suffix
    return False
```

### 2.4 `StorageValidator.Validate()`

Probes each of the four storage services (Blob / File / Queue / Table) by
calling `.GetProperties()`. This validates **both** network reachability
and shared-key auth. Failure → status `Failed`. Used by
`ValidateStorageConnectivity` (`Operations/ValidateStorageConnectivity.cs`).

Python:

```python
from azure.data.tables import TableServiceClient
from azure.storage.blob import BlobServiceClient
from azure.storage.queue import QueueServiceClient
from azure.storage.fileshare import ShareServiceClient

def probe_storage_auth(conn: str) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for name, ctor in [
        ("blob", BlobServiceClient.from_connection_string),
        ("file", ShareServiceClient.from_connection_string),
        ("queue", QueueServiceClient.from_connection_string),
        ("table", TableServiceClient.from_connection_string),
    ]:
        try:
            ctor(conn).get_service_properties()
            out[name] = True
        except Exception:
            out[name] = False
    return out
```

## 3. Composition for `ValidateStorageConnectivity`

The combined command:

1. Parse connection string → endpoint hostnames for blob/file/queue/table.
2. For each hostname: DNS → TCP-443 → SSL handshake → auth probe.
3. Pretty-print as `ConsoleTable`.
4. Optionally (when MI subscription Reader is granted) check whether the
   storage's resolved IPs fall into any `AzureCloud.<region>` service tag
   subnet, to flag traffic egressing to a private endpoint.

The .NET tool uses `CommonOperations.IsIpInSubnet(ip, subnet)` for the last
step (`Shared/Common.cs:252-278`). The Python equivalent is
`ipaddress.ip_network(subnet).supernet_of(ipaddress.ip_address(ip))` — or
simpler, `ipaddress.ip_address(ip) in ipaddress.ip_network(subnet)`.

## 4. Composition for `ValidateSPConnectivity`

Reads `connections.json` from `wwwroot`, iterates each entry whose
`type` falls into the supported Service Provider list, extracts host:port
from connection parameters, and runs DNS + TCP + (if scheme is HTTPS) SSL.
Excluded provider types in `Operations/ValidateServiceProviderConnectivity.cs`:
`sap`, `jdbc`, `fileSystem` (case-sensitive).

## 5. Composition for `EndpointValidation`

Takes a single `-url`. Parses host + port via Python `urllib.parse.urlsplit`,
runs DNS → TCP → SSL if scheme is `https`. Prints the same `ConsoleTable`
format.

## 6. Output formatting

Use `rich.table.Table` for parity with the .NET `ConsoleTable`. Suggested
columns:

```
Endpoint        | DNS    | IP            | TCP    | SSL    | Auth  | Notes
```

`Notes` carries extra info such as cert NotAfter, SAN mismatch, private-
endpoint warning, etc.

## 7. Timeouts

The .NET TCP probe uses a hard 1-second timeout. For SSL the implicit
HTTPS GET inherits the default `HttpClient` timeout (100 s). The Python
port should expose `--timeout` flags (defaults: TCP 1 s, SSL 5 s) so
users can tune for unstable networks.
