"""Environment-variable resolver — mirrors Shared/AppSettings.cs.

Read-only view of the env vars the .NET tool consumes. The dataclass is
intentionally re-evaluated on each attribute access so tests can mutate
os.environ in-place without re-importing the module.

The Python port additionally understands the Azure Functions runtime
convention for AAD-authenticated storage (`AzureWebJobsStorage__accountName`,
`AzureWebJobsStorage__tableServiceUri`, etc.) so it works against modern
Logic App Standard instances configured with managed identity for storage.
"""
from __future__ import annotations

import os
from pathlib import Path


def _parse_conn_string(cs: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for chunk in cs.split(";"):
        if not chunk:
            continue
        idx = chunk.find("=")
        if idx == -1:
            continue
        out[chunk[:idx]] = chunk[idx + 1 :]
    return out


class _Settings:
    """Lazily-evaluated facade around os.environ."""

    # ------------------------------------------------------------------
    # Raw env-var passthroughs
    # ------------------------------------------------------------------

    @property
    def connection_string(self) -> str | None:
        return os.environ.get("AzureWebJobsStorage")

    @property
    def file_share_connection_string(self) -> str | None:
        return os.environ.get("WEBSITE_CONTENTAZUREFILECONNECTIONSTRING")

    @property
    def subscription_id(self) -> str | None:
        owner = os.environ.get("WEBSITE_OWNER_NAME")
        if not owner:
            return None
        return owner.split("+")[0]

    @property
    def resource_group(self) -> str | None:
        return os.environ.get("WEBSITE_RESOURCE_GROUP")

    @property
    def region(self) -> str | None:
        return os.environ.get("REGION_NAME")

    @property
    def logic_app_name(self) -> str | None:
        return os.environ.get("WEBSITE_SITE_NAME")

    @property
    def msi_endpoint(self) -> str | None:
        return os.environ.get("MSI_ENDPOINT")

    @property
    def msi_secret(self) -> str | None:
        return os.environ.get("MSI_SECRET")

    @property
    def root_folder(self) -> Path:
        return Path(os.environ.get("LAT_ROOT_FOLDER", r"C:\home\site\wwwroot"))

    @property
    def management_base_url(self) -> str:
        # See Shared/AppSettings.cs:83-89
        return (
            "https://management.azure.com"
            f"/subscriptions/{self.subscription_id}"
            f"/resourceGroups/{self.resource_group}"
            f"/providers/Microsoft.Web/sites/{self.logic_app_name}"
        )

    # ------------------------------------------------------------------
    # AAD / Entra ID storage support (Azure Functions runtime convention)
    # ------------------------------------------------------------------

    @property
    def storage_mi_client_id(self) -> str | None:
        """User-assigned MI client ID for storage, if configured."""
        return os.environ.get("AzureWebJobsStorage__clientId")

    @property
    def storage_account_name(self) -> str | None:
        """Storage account name, resolved from any of the supported env shapes.

        Resolution order:
          1. `AzureWebJobsStorage__accountName` (Functions runtime convention)
          2. Parsed `AccountName=` segment of `AzureWebJobsStorage` conn string
          3. Hostname segment of any `AzureWebJobsStorage__<svc>ServiceUri`
        """
        name = os.environ.get("AzureWebJobsStorage__accountName")
        if name:
            return name
        cs = self.connection_string
        if cs and "AccountName=" in cs:
            parsed = _parse_conn_string(cs)
            if parsed.get("AccountName"):
                return parsed["AccountName"]
        for key in (
            "AzureWebJobsStorage__tableServiceUri",
            "AzureWebJobsStorage__blobServiceUri",
            "AzureWebJobsStorage__queueServiceUri",
        ):
            uri = os.environ.get(key)
            if uri and "://" in uri:
                host = uri.split("://", 1)[1].split("/", 1)[0]
                # e.g. mystorage.table.core.windows.net -> mystorage
                return host.split(".")[0]
        return None

    @property
    def storage_endpoint_suffix(self) -> str:
        """DNS suffix for storage endpoints (default: core.windows.net)."""
        cs = self.connection_string
        if cs:
            parsed = _parse_conn_string(cs)
            if parsed.get("EndpointSuffix"):
                return parsed["EndpointSuffix"]
        for key in (
            "AzureWebJobsStorage__tableServiceUri",
            "AzureWebJobsStorage__blobServiceUri",
            "AzureWebJobsStorage__queueServiceUri",
        ):
            uri = os.environ.get(key)
            if uri and "://" in uri:
                host = uri.split("://", 1)[1].split("/", 1)[0]
                # mystorage.table.core.windows.net -> core.windows.net
                parts = host.split(".", 2)
                if len(parts) == 3:
                    return parts[2]
        return "core.windows.net"

    @property
    def uses_aad_storage(self) -> bool:
        """True if storage clients should authenticate with a TokenCredential.

        We pick AAD mode when EITHER:
          * `AzureWebJobsStorage` is unset / has no AccountKey, AND a storage
            account is resolvable from one of the supported env vars, OR
          * `AzureWebJobsStorage__credential` is set (the Functions runtime
            convention for opting into managed identity).
        """
        if os.environ.get("AzureWebJobsStorage__credential"):
            return True
        cs = self.connection_string
        if cs and "AccountKey=" in cs:
            return False
        return self.storage_account_name is not None

    def storage_endpoint(self, service: str) -> str | None:
        """Build a service URL (https://<account>.<svc>.<suffix>) for AAD mode."""
        # Explicit override env var wins.
        explicit = os.environ.get(f"AzureWebJobsStorage__{service}ServiceUri")
        if explicit:
            return explicit.rstrip("/")
        account = self.storage_account_name
        if not account:
            return None
        return f"https://{account}.{service}.{self.storage_endpoint_suffix}"


settings = _Settings()
