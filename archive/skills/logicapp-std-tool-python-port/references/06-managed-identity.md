# Reference 06 — Managed Identity Token Flow

The tool's control-plane operations (read/write app settings, restart site,
resubmit/cancel runs, list service tags, modify connector firewalls) all use
the Logic App site's **Managed Identity** to obtain an Azure AD bearer
token. This reference documents the wire protocol, header set, query
parameters, caching, and refresh logic — all of which the Python port must
reproduce.

## 1. C# source

`Shared/MSITokenService.cs` (entire file, ~62 lines):

* `RetrieveToken(string resource)` — lines 15–43
* `VerifyToken(ref MSIToken token)` — lines 45–59

Structure model: `Structures/MITokenStructure.cs`.

## 2. Wire protocol

The Logic App / App Service host injects two env vars during runtime:

| Var | Example | Source |
| --- | --- | --- |
| `MSI_ENDPOINT` | `http://127.0.0.1:41xx/msi/token` | App Service runtime |
| `MSI_SECRET` | `<32 hex chars>` | App Service runtime |

The request:

```
GET {MSI_ENDPOINT}?resource={resource}&api-version=2019-08-01
X-IDENTITY-HEADER: {MSI_SECRET}
```

Response body (JSON):

```json
{
  "access_token": "eyJ0…",
  "expires_on": "1715500000",        // epoch seconds
  "resource": "https://management.azure.com",
  "token_type": "Bearer",
  "client_id": "<guid>"              // optional
}
```

> The `MITokenStructure` POCO in `Structures/MITokenStructure.cs` has
> properties `access_token`, `expires_on`, `resource`, `token_type`,
> `client_id` (lowercase to match the JSON). Mirror these names in the
> Python pydantic model.

### 2.1 Resource values used by the tool

| Resource | Used for |
| --- | --- |
| `https://management.azure.com` | All ARM calls (default) |
| `https://storage.azure.com/` | (Not currently used — tool uses connection string for storage) |
| Any user-supplied audience | `Tools GetMIToken -a <audience>` |

## 3. Local-dev mode (DEBUG)

When compiled with `#if DEBUG`, the tool reads a pre-generated token from
`Temp/MIToken.json` instead of calling `MSI_ENDPOINT`. The Python port
should support both modes:

* **Live mode** (default): call `MSI_ENDPOINT`.
* **Local mode** (env var `LAT_OFFLINE_MI_TOKEN=<path>`): read the cached
  JSON from disk.

Recommended cache path: `~/.cache/lat/mi-token.json` (XDG; on Windows,
`%LOCALAPPDATA%\lat\mi-token.json`). Always set file permissions to user-
read-only (`0600` on POSIX).

## 4. Expiry handling

`VerifyToken`:

```csharp
long epochNow = DateTime.UtcNow.ToEpoch();
long diff = long.Parse(token.expires_on) - epochNow;
if (diff < 300) {
    Console.WriteLine($"MSI token will be expired in {diff} seconds, refresh token.");
    token = RetrieveToken("https://management.azure.com");
}
```

Refresh threshold: **5 minutes before expiry**. The Python port should:

* Always call `verify_token(token)` at the *start* of any ARM operation
  loop (e.g. `BatchResubmit` makes thousands of calls; the token must be
  refreshed between batches).
* Use a single in-process cache keyed by `resource` so multiple operations
  share one token.

## 5. Python implementation

```python
# src/lat/msi.py
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

from .settings import settings


@dataclass
class MIToken:
    access_token: str
    expires_on: int            # epoch seconds
    resource: str
    token_type: str = "Bearer"
    client_id: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "MIToken":
        return cls(
            access_token=d["access_token"],
            expires_on=int(d["expires_on"]),
            resource=d.get("resource", ""),
            token_type=d.get("token_type", "Bearer"),
            client_id=d.get("client_id"),
        )

    def expires_in(self) -> int:
        return self.expires_on - int(time.time())


_CACHE: dict[str, MIToken] = {}
_DEFAULT_CACHE_PATH = (
    Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache")
    / "lat" / "mi-token.json"
)


def _retrieve_from_msi(resource: str) -> MIToken:
    endpoint = settings.msi_endpoint
    secret = settings.msi_secret
    if not endpoint or not secret:
        raise RuntimeError(
            "MSI_ENDPOINT / MSI_SECRET are not set; either run inside an "
            "Azure host with managed identity, or set LAT_OFFLINE_MI_TOKEN "
            "to point at a cached token JSON."
        )
    resp = httpx.get(
        endpoint,
        params={"resource": resource, "api-version": "2019-08-01"},
        headers={"X-IDENTITY-HEADER": secret},
        timeout=30.0,
    )
    resp.raise_for_status()
    return MIToken.from_dict(resp.json())


def _retrieve_from_cache(resource: str) -> MIToken | None:
    path = Path(os.environ.get("LAT_OFFLINE_MI_TOKEN", _DEFAULT_CACHE_PATH))
    if not path.exists():
        return None
    return MIToken.from_dict(json.loads(path.read_text()))


def retrieve_token(resource: str = "https://management.azure.com") -> MIToken:
    cached = _CACHE.get(resource)
    if cached and cached.expires_in() > 300:
        return cached
    try:
        token = _retrieve_from_msi(resource)
    except Exception:
        offline = _retrieve_from_cache(resource)
        if offline is None:
            raise
        token = offline
    _CACHE[resource] = token
    return token


def verify_token(token: MIToken) -> MIToken:
    """Refresh if expiring within 5 minutes; return the (possibly new) token."""
    if token.expires_in() < 300:
        return retrieve_token(token.resource or "https://management.azure.com")
    return token
```

## 6. Tests

* Mock `httpx.get` to return a fixed token JSON; assert headers contain
  `X-IDENTITY-HEADER` and query has `api-version=2019-08-01` and the right
  `resource`.
* Test `verify_token` triggers refresh at the boundary (expires_in == 299
  vs 301).
* Test cache file is created with `0600` perms on POSIX (skip on Windows).

## 7. Common bugs to avoid

* Using `Secret` header instead of `X-IDENTITY-HEADER`. (App Service used
  the former with `api-version=2017-09-01`; the current MSI endpoint uses
  `X-IDENTITY-HEADER` with `2019-08-01`.)
* Not encoding `resource` — it includes `://` but URL libs handle that
  correctly via the `params=` dict. **Do not** double-URL-encode.
* Logging the access token. Never print `token.access_token`; in logs,
  print only `token_type` and `expires_in`.
