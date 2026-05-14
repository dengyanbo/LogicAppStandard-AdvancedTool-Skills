"""Managed Identity token flow — mirrors Shared/MSITokenService.cs.

See references/06-managed-identity.md for protocol details (header
X-IDENTITY-HEADER, api-version 2019-08-01).
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from .settings import settings


@dataclass
class MIToken:
    access_token: str
    expires_on: int
    resource: str
    token_type: str = "Bearer"
    client_id: str | None = None

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
            "MSI_ENDPOINT / MSI_SECRET are not set; either run inside an Azure "
            "host with managed identity, or set LAT_OFFLINE_MI_TOKEN to point "
            "at a cached token JSON."
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
