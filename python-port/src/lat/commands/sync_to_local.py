"""`SyncToLocal Normal/Auto/Batch` — pull a Logic App's wwwroot file share locally.

Mirrors `Operations/SyncToLocal.cs`. Three command variants share one
recursive `_sync_tree` walker:

  * `lat site sync-to-local-normal`  — interactive prompts for cleanup +
    extra excludes (same UX as the .NET tool).
  * `lat site sync-to-local-auto`    — non-interactive; always cleans up
    non-excluded subfolders before syncing.
  * `lat site sync-to-local-batch`   — runs the Auto mode against a JSON
    config listing many Logic Apps.

Default exclude folders are `.git` and `.vscode` (preserved from the .NET tool).
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Iterable, Protocol

import typer

from ..settings import settings

DEFAULT_EXCLUDES = {".git", ".vscode"}
_WWWROOT_PATH = "site/wwwroot"


# ---------------------------------------------------------------------------
# Test seam: a thin abstraction over azure.storage.fileshare so unit tests
# can inject a synthetic share tree without spinning Azurite.
# ---------------------------------------------------------------------------


class _DirClient(Protocol):
    def list_files(self) -> Iterable[tuple[str, bool]]: ...
    def open_subdir(self, name: str) -> "_DirClient": ...
    def download_file(self, name: str) -> bytes: ...


class _AzureShareDirClient:
    """Wraps `azure.storage.fileshare.ShareDirectoryClient` to match _DirClient."""

    def __init__(self, share_dir_client: object) -> None:
        self._inner = share_dir_client

    def list_files(self) -> Iterable[tuple[str, bool]]:
        # list_directories_and_files yields ShareDirectoryClient.FileProperties items
        for item in self._inner.list_directories_and_files():  # type: ignore[attr-defined]
            yield item.name, bool(item.is_directory)

    def open_subdir(self, name: str) -> "_AzureShareDirClient":
        return _AzureShareDirClient(self._inner.get_subdirectory_client(name))  # type: ignore[attr-defined]

    def download_file(self, name: str) -> bytes:
        file_client = self._inner.get_file_client(name)  # type: ignore[attr-defined]
        return file_client.download_file().readall()


def _open_share(connection_string: str, share_name: str) -> _DirClient:
    """Default share-client factory; tests monkeypatch this."""
    from azure.storage.fileshare import ShareClient

    share = ShareClient.from_connection_string(connection_string, share_name)
    return _AzureShareDirClient(share.get_directory_client(_WWWROOT_PATH))


# Test seam — tests can patch this to return a fake _DirClient.
def _share_client(connection_string: str, share_name: str) -> _DirClient:
    return _open_share(connection_string, share_name)


# ---------------------------------------------------------------------------
# Core sync logic
# ---------------------------------------------------------------------------


def _purge_subfolders(local_path: Path, excludes: set[str]) -> None:
    """Delete subdirectories of local_path whose name is NOT in `excludes`."""
    if not local_path.exists():
        return
    for child in local_path.iterdir():
        if child.is_dir() and child.name not in excludes:
            shutil.rmtree(child)


def _sync_tree(local_folder: Path, client: _DirClient) -> None:
    """Recursively materialize a share directory under `local_folder`."""
    local_folder.mkdir(parents=True, exist_ok=True)
    for name, is_dir in client.list_files():
        target = local_folder / name
        if is_dir:
            target.mkdir(exist_ok=True)
            _sync_tree(target, client.open_subdir(name))
        else:
            content = client.download_file(name)
            target.write_bytes(content)


def _resolve_excludes(extra: Iterable[str] | None) -> set[str]:
    out = set(DEFAULT_EXCLUDES)
    if extra:
        out.update(item.strip() for item in extra if item and item.strip())
    return out


# ---------------------------------------------------------------------------
# Normal mode — interactive prompts
# ---------------------------------------------------------------------------


def sync_to_local_normal(
    share_name: str = typer.Option(
        ..., "-sn", "--share-name", help="Azure file share name."
    ),
    connection_string: str = typer.Option(
        ..., "-cs", "--connection-string",
        help="Storage account connection string for the share.",
    ),
    local_path: Path = typer.Option(
        ..., "-path", "--local-path", help="Destination folder."
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y",
        help="Bypass the overwrite confirmation (do not cleanup local folders).",
    ),
) -> None:
    """Interactive sync of wwwroot to a local folder."""
    if not yes:
        typer.confirm(
            "This operation will overwrite your local project files. Continue?",
            abort=True,
        )
        do_cleanup = typer.confirm(
            "Whether clean up workflows in local project which cannot be found on "
            "cloud?\n  Yes: Clean up all subfolders not in cloud (except .git, .vscode).\n"
            "  No: Only overwrite cloud-modified files.",
            default=False,
        )
    else:
        do_cleanup = False

    if do_cleanup:
        extra = typer.prompt(
            "Please provide the folders which you would like to exclude for clean "
            "up, use comma for split.\nIf no extra folder need to be excluded, just "
            "press Enter (.git, .vscode excluded by default)",
            default="",
            show_default=False,
        )
        excludes = _resolve_excludes(extra.split(",") if extra else None)
        _purge_subfolders(local_path, excludes)

    _sync_tree(local_path, _share_client(connection_string, share_name))
    typer.echo(f"Sync to local successed, File Share name {share_name}.")


# ---------------------------------------------------------------------------
# Auto mode — non-interactive, always cleans up subfolders
# ---------------------------------------------------------------------------


def sync_to_local_auto(
    share_name: str = typer.Option(
        ..., "-sn", "--share-name", help="Azure file share name."
    ),
    connection_string: str = typer.Option(
        ..., "-cs", "--connection-string",
        help="Storage account connection string for the share.",
    ),
    local_path: Path = typer.Option(
        ..., "-path", "--local-path", help="Destination folder."
    ),
    exclude: list[str] = typer.Option(
        [], "-ex", "--exclude",
        help="Extra folder names to preserve during cleanup. Repeatable.",
    ),
) -> None:
    """Non-interactive sync. Always wipes non-excluded local subfolders first."""
    excludes = _resolve_excludes(exclude)
    _purge_subfolders(local_path, excludes)
    _sync_tree(local_path, _share_client(connection_string, share_name))
    typer.echo(f"Sync to local successed, File Share name {share_name}.")


# ---------------------------------------------------------------------------
# Batch mode — run Auto for many Logic Apps from a JSON config
# ---------------------------------------------------------------------------


def sync_to_local_batch(
    config_file: Path = typer.Option(
        ..., "-cf", "--config-file",
        help="JSON file with list of {FileShareName, ConnectionString, LocalPath, Excludes}.",
    ),
) -> None:
    """Run Auto mode against many Logic Apps from a JSON config."""
    if not config_file.exists():
        raise typer.BadParameter(f"{config_file} cannot be found, please check your input")
    configs = json.loads(config_file.read_text(encoding="utf-8"))
    if not isinstance(configs, list):
        raise typer.BadParameter("Config file must be a JSON array of sync entries.")
    for entry in configs:
        if not isinstance(entry, dict):
            raise typer.BadParameter("Each entry must be an object.")
        share = entry.get("FileShareName")
        cs = entry.get("ConnectionString")
        local = entry.get("LocalPath")
        if not share or not cs or not local:
            raise typer.BadParameter(
                "Each entry needs FileShareName, ConnectionString, LocalPath."
            )
        excludes = _resolve_excludes(entry.get("Excludes") or [])
        _purge_subfolders(Path(local), excludes)
        _sync_tree(Path(local), _share_client(cs, share))
        typer.echo(f"Sync to local successed, File Share name {share}.")
    typer.echo("All the projects have been synced")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(site_app: typer.Typer) -> None:
    site_app.command(
        "sync-to-local-normal",
        help="Interactive sync of wwwroot to a local folder.",
    )(sync_to_local_normal)
    site_app.command(
        "sync-to-local-auto",
        help="Non-interactive sync (deletes non-excluded local subfolders first).",
    )(sync_to_local_auto)
    site_app.command(
        "sync-to-local-batch",
        help="Run Auto mode for many Logic Apps from a JSON config.",
    )(sync_to_local_batch)
