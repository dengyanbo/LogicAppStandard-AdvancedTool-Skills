"""Blob helpers used by ContentDecoder, Snapshot, and CleanUp commands.

See Shared/Common.cs:149-174 for GetBlobContent (size-capped download +
decompression) which the .NET tool uses to fetch large run-history
payloads stored as blobs.
"""
from __future__ import annotations

from collections.abc import Iterable

from azure.storage.blob import BlobClient, BlobServiceClient

from ..settings import settings
from .compression import decompress as decompress_payload


def service_client() -> BlobServiceClient:
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


def get_blob_content(blob_uri: str, max_size_bytes: int | None = None) -> str:
    """Fetch a blob payload and decompress.

    `max_size_bytes` mirrors `contentSize` from the C# version: if the blob
    is larger than the limit, return an empty string (so callers can skip
    big payloads quickly).
    """
    client = BlobClient.from_blob_url(blob_uri, credential=_shared_key_credential())
    props = client.get_blob_properties()
    if max_size_bytes is not None and props.size > max_size_bytes:
        return ""
    downloaded = client.download_blob().readall()
    return decompress_payload(downloaded) or ""


def _shared_key_credential() -> object:
    """Extract a SharedKeyCredential from the connection string.

    Implementation hint: parse `AzureWebJobsStorage` for `AccountName=`
    and `AccountKey=` and instantiate `azure.storage.blob.SharedKeyCredential`.
    See Shared/Structures/StorageConnectionStructure.cs for the parser the
    .NET tool uses.
    """
    raise NotImplementedError("TODO: parse storage conn string → SharedKeyCredential")
