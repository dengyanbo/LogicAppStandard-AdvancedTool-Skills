"""Environment-variable resolver — mirrors Shared/AppSettings.cs.

Read-only view of the env vars the .NET tool consumes. The dataclass is
intentionally re-evaluated on each attribute access so tests can mutate
os.environ in-place without re-importing the module.
"""
from __future__ import annotations

import os
from pathlib import Path


class _Settings:
    """Lazily-evaluated facade around os.environ."""

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


settings = _Settings()
