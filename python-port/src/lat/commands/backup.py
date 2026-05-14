"""`Backup` — backup all FLOWVERSION rows + appsettings to local disk.

Mirrors `Operations/Backup.cs`. Each workflow definition is written to:

    Backup/<FlowName>/LastModified_<latestModified>_<FlowId>/<modifiedDate>_<FlowSequenceId>.json

If the matching file already exists, that version is skipped (so reruns
are cheap). App settings come from ARM and are written to
`Backup/appsettings.json`; a failed appsettings call only warns and
continues.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import typer

from .. import arm
from ..storage import tables


def _changed_time(entity: dict) -> _dt.datetime | None:
    value = entity.get("ChangedTime")
    if isinstance(value, _dt.datetime):
        return value
    if isinstance(value, str):
        try:
            return _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _fmt_compact(dt: _dt.datetime) -> str:
    return dt.astimezone(_dt.timezone.utc).strftime("%Y%m%d%H%M%S")


def backup(
    date: str = typer.Option(
        "19700101", "--date", "-d",
        help="Only back up rows whose ChangedTime is on or after this date (yyyyMMdd).",
    ),
    output_folder: Path = typer.Option(
        Path("Backup"), "--output", "-o",
        help="Destination folder (created if missing). Defaults to ./Backup.",
    ),
) -> None:
    """Back up every workflow definition (FLOWVERSION row) since `date`."""
    output_folder.mkdir(parents=True, exist_ok=True)

    typer.echo("Retrieving appsettings...")
    try:
        settings_obj = arm.get_appsettings()
        (output_folder / "appsettings.json").write_text(
            json.dumps(settings_obj, indent=2), encoding="utf-8"
        )
        typer.echo("Backup for appsettings succeeded.")
    except Exception as exc:  # noqa: BLE001 - mirror .NET catch-all
        typer.echo(
            f"Failed to retrieve appsettings ({exc}). "
            "Please review your Logic App Managed Identity role "
            "(Website Contributor or Logic App Standard Contributor required)."
        )

    try:
        parsed = _dt.datetime.strptime(date, "%Y%m%d").replace(
            tzinfo=_dt.timezone.utc
        )
    except ValueError as exc:
        raise typer.BadParameter(
            f"--date must be in yyyyMMdd format, got {date!r}"
        ) from exc
    formatted_date = parsed.strftime("%Y-%m-%dT00:00:00Z")

    typer.echo("Retrieving workflow definitions...")
    rows = [
        r
        for r in tables.query_main_table(
            f"ChangedTime ge datetime'{formatted_date}'",
            select=[
                "FlowName", "FlowSequenceId", "ChangedTime",
                "FlowId", "RowKey", "DefinitionCompressed", "Kind",
            ],
        )
        if str(r.get("RowKey", "")).startswith("MYEDGEENVIRONMENT_FLOWVERSION")
    ]

    # Compute the latest ChangedTime per FlowId, used as the per-flow folder tag.
    latest_per_flow: dict[str, str] = {}
    for r in rows:
        fid = str(r.get("FlowId") or "")
        ts = _changed_time(r)
        if not fid or ts is None:
            continue
        compact = _fmt_compact(ts)
        cur = latest_per_flow.get(fid)
        if cur is None or compact > cur:
            latest_per_flow[fid] = compact

    typer.echo(f"Found {len(rows)} workflow definitions, saving to folder...")

    for r in rows:
        flow_name = str(r.get("FlowName") or "")
        flow_id = str(r.get("FlowId") or "")
        seq_id = str(r.get("FlowSequenceId") or "")
        ts = _changed_time(r)
        if not flow_name or not flow_id or not seq_id or ts is None:
            continue
        modified = _fmt_compact(ts)
        flow_latest = latest_per_flow.get(flow_id, modified)
        folder = output_folder / flow_name / f"LastModified_{flow_latest}_{flow_id}"
        file_name = f"{modified}_{seq_id}.json"
        if (folder / file_name).exists():
            continue
        tables.save_definition(folder, file_name, r, overwrite=False)

    typer.echo("Backup for workflow definitions succeeded.")


def register(workflow_app: typer.Typer) -> None:
    workflow_app.command(
        "backup",
        help="Back up workflow definitions + appsettings to a local folder.",
    )(backup)
