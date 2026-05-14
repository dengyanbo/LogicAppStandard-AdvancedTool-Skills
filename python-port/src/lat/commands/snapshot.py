"""`Snapshot Create` / `Snapshot Restore` — wwwroot + app settings snapshot.

Mirrors `Operations/Snapshot.cs`. The .NET tool:
  * Snapshot Create — copies wwwroot to `Snapshot_<ts>/`, then writes the
    site's app settings dump as `appsettings.json` next to it.
  * Snapshot Restore — copies a snapshot folder back to wwwroot, then PUTs
    the snapshot's `appsettings.json` via ARM (auto-restarts the site).

The Python port preserves both behaviors. API Connection resources are
NOT captured (same limitation as the .NET tool — those live as separate
ARM resources, not in wwwroot).
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

import typer

from .. import arm
from ..settings import settings


def snapshot_create(
    root: Path = typer.Option(
        None, "--root",
        help=f"wwwroot to snapshot. Defaults to {settings.root_folder}.",
    ),
    output: Path | None = typer.Option(
        None, "--out",
        help="Snapshot folder (defaults to Snapshot_<yyyyMMddHHmmss>/ in cwd).",
    ),
    skip_appsettings: bool = typer.Option(
        False, "--skip-appsettings",
        help="Don't try to dump app settings via ARM (useful offline / no MI).",
    ),
) -> None:
    """Snapshot wwwroot + app settings to a local folder."""
    root_path = root or settings.root_folder
    if not root_path.exists() or not root_path.is_dir():
        raise typer.BadParameter(f"Root folder does not exist: {root_path}")

    target = output or Path.cwd() / f"Snapshot_{datetime.now():%Y%m%d%H%M%S}"
    if target.exists():
        raise typer.BadParameter(
            f"Folder with name {target} already exist, snapshot will not be "
            "created, please try again."
        )

    typer.echo(
        "Backing up workflow related files (definition, artifacts, host.json, etc.)"
    )
    shutil.copytree(root_path, target)
    typer.echo("Backup for wwwroot folder succeeded.")

    if skip_appsettings:
        typer.echo("Skipping app-settings dump as requested.")
        typer.echo(f"Snapshot created, you can review all files in folder {target}")
        return

    typer.echo("Retrieving appsettings..")
    try:
        appsettings = arm.get_appsettings()
    except Exception as e:  # noqa: BLE001 - match .NET catch-all
        typer.echo(
            "Failed to retrieve appsettings, please review your Logic App "
            "Managed Identity role (Website Contributor or Logic App Standard "
            f"Contributor required). Error: {e}"
        )
    else:
        (target / "appsettings.json").write_text(
            json.dumps(appsettings, indent=2), encoding="utf-8"
        )
        typer.echo("Appsettings backup successfully.")

    typer.echo(f"Snapshot created, you can review all files in folder {target}")


def snapshot_restore(
    path: Path = typer.Option(
        ..., "-p", "--path",
        help="Snapshot folder to restore from.",
    ),
    root: Path = typer.Option(
        None, "--root",
        help=f"wwwroot to restore into. Defaults to {settings.root_folder}.",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the destructive-restore confirmation.",
    ),
) -> None:
    """Restore wwwroot + push app settings to ARM (will auto-restart)."""
    if not path.exists() or not path.is_dir():
        raise typer.BadParameter(
            f"Cannot find Snapshot path: {path}, please revew you input."
        )
    root_path = root or settings.root_folder

    if not yes:
        typer.confirm(
            f"This will overwrite {root_path} with {path}, then push app settings "
            "to ARM (the site will auto-restart). Continue?",
            abort=True,
        )

    typer.echo("Restoring files in wwwroot folder.")
    # Robust folder-overwrite copy: rmtree if dest exists (matching .NET's
    # File.Copy overwrite=true semantics), then copytree.
    if root_path.exists():
        shutil.rmtree(root_path)
    shutil.copytree(path, root_path)
    typer.echo("All files are restored")

    typer.echo("Restoring appsettings...")
    appsettings_path = path / "appsettings.json"
    if not appsettings_path.exists():
        raise typer.BadParameter(
            "Warning!!! Missing appsettings.json, appsetting won't be restored."
        )

    appsettings = json.loads(appsettings_path.read_text(encoding="utf-8"))
    if not isinstance(appsettings, dict):
        raise typer.BadParameter(
            "appsettings.json must be a flat object {key: value}; got "
            f"{type(appsettings).__name__}"
        )
    arm.put_appsettings({str(k): str(v) for k, v in appsettings.items()})
    typer.echo(
        "Restore successfully, Logic App will restart automatically to refresh appsettings."
    )


def register(site_app: typer.Typer) -> None:
    site_app.command(
        "snapshot-create",
        help="Snapshot wwwroot + app settings to a local folder.",
    )(snapshot_create)
    site_app.command(
        "snapshot-restore",
        help="Restore wwwroot + push app settings from a snapshot folder.",
    )(snapshot_restore)
