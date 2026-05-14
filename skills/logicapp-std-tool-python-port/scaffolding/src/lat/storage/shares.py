"""File share helpers — used by SyncToLocal and Snapshot commands.

The Logic App's wwwroot is hosted on the content file share addressed by
`WEBSITE_CONTENTAZUREFILECONNECTIONSTRING`. The share name is provided by
the operator (typically `<site-name>-content`).
"""
from __future__ import annotations

from pathlib import Path

from azure.storage.fileshare import ShareClient, ShareServiceClient

from ..settings import settings


def service_client(connection_string: str | None = None) -> ShareServiceClient:
    conn = connection_string or settings.file_share_connection_string
    if not conn:
        raise RuntimeError("WEBSITE_CONTENTAZUREFILECONNECTIONSTRING is not set")
    return ShareServiceClient.from_connection_string(conn)


def share_client(share_name: str, connection_string: str | None = None) -> ShareClient:
    return service_client(connection_string).get_share_client(share_name)


def download_share_to_local(
    share_name: str,
    local_path: Path,
    connection_string: str | None,
    excludes: set[str] | None = None,
) -> None:
    """Recursively mirror the share to local_path.

    See Operations/SyncToLocal.cs in the .NET source.
    """
    raise NotImplementedError(
        "TODO: implement directory walk using azure.storage.fileshare and write "
        "each file via ShareFileClient.download_file()"
    )
