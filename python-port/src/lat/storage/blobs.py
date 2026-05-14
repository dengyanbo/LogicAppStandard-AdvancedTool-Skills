"""Blob helpers used by CleanUp commands and validate-storage-connectivity.

See Shared/Common.cs:149-174 for GetBlobContent (size-capped download +
decompression) which the .NET tool uses to fetch large run-history
payloads stored as blobs. That path is NOT implemented here because no
ported command currently needs it; the `search-in-history` command in
this port only inspects inlined payloads (see MIGRATION-NOTES.md).
"""
from __future__ import annotations

from azure.storage.blob import BlobServiceClient

from ..settings import settings


def service_client() -> BlobServiceClient:
    if settings.uses_aad_storage:
        from ..auth import credential

        endpoint = settings.storage_endpoint("blob")
        if not endpoint:
            raise RuntimeError(
                "Storage account not resolvable; set AzureWebJobsStorage or "
                "AzureWebJobsStorage__accountName."
            )
        return BlobServiceClient(account_url=endpoint, credential=credential())
    conn = settings.connection_string
    if not conn:
        raise RuntimeError("AzureWebJobsStorage is not set")
    return BlobServiceClient.from_connection_string(conn)


def list_containers_with_prefix(prefix: str) -> list[str]:
    """Return every container whose name starts with `prefix`."""
    return [
        c.name for c in service_client().list_containers(name_starts_with=prefix)
    ]


def delete_container(name: str) -> None:
    service_client().delete_container(name)
