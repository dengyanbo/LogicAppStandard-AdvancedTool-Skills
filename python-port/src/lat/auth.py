"""Azure credential acquisition.

Wraps `azure.identity` to provide:

* `credential()` — singleton `TokenCredential` picked appropriately for the
  runtime environment (Managed Identity on a Logic Apps Standard host,
  `DefaultAzureCredential` chain elsewhere — typically resolves via
  `az login` during local development).
* `retrieve_token(audience)` — convenience wrapper that returns an `MIToken`
  with the same shape `MSITokenService.RetrieveToken` produces in the .NET
  tool, so existing CLI output (`Tools GetMIToken`) stays JSON-compatible.

The `azure-identity` SDK handles token caching, refresh, MSI endpoint
detection (IDENTITY_ENDPOINT / IDENTITY_HEADER for newer hosts and
MSI_ENDPOINT / MSI_SECRET for older ones), and silent fallback. This file
replaces the hand-rolled HTTP-to-IMDS code previously here.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass

from azure.core.credentials import TokenCredential
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential

DEFAULT_AUDIENCE = "https://management.azure.com"

_credential: TokenCredential | None = None


def _build_credential() -> TokenCredential:
    """Pick a credential strategy by sniffing the runtime environment."""
    if os.environ.get("IDENTITY_ENDPOINT") or os.environ.get("MSI_ENDPOINT"):
        # Running on an Azure host with managed identity.
        return ManagedIdentityCredential()
    # Local dev / CI: chain through env vars, az login, VS, etc.
    return DefaultAzureCredential()


def credential() -> TokenCredential:
    """Return the process-wide TokenCredential, building it on first call."""
    global _credential
    if _credential is None:
        _credential = _build_credential()
    return _credential


def reset_credential() -> None:
    """Test helper — clear the cached credential."""
    global _credential
    _credential = None


@dataclass
class MIToken:
    """Backwards-compatible token envelope, matches .NET MSIToken JSON shape."""

    access_token: str
    expires_on: int
    resource: str
    token_type: str = "Bearer"
    client_id: str | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


def _audience_to_scope(audience: str) -> str:
    """ARM scopes for azure-identity expect the form `<audience>/.default`."""
    return audience if audience.endswith("/.default") else audience.rstrip("/") + "/.default"


def retrieve_token(audience: str = DEFAULT_AUDIENCE) -> MIToken:
    """Acquire a bearer token for `audience` and return as an `MIToken`."""
    scope = _audience_to_scope(audience)
    access = credential().get_token(scope)
    return MIToken(
        access_token=access.token,
        expires_on=int(access.expires_on),
        resource=audience.rstrip("/"),
    )
