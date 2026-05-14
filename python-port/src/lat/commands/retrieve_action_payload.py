"""`RetrieveActionPayload` — dump inputs/outputs for an action on a date.

Mirrors `Operations/RetrieveActionPayload.cs`. Looks up matching rows in
both the per-flow history table (for triggers) and the per-day actions
table (for actions), decodes each `Inputs/OutputsLinkCompressed` column,
then writes the assembled payload list as JSON to disk.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import typer

from ..settings import settings
from ..storage import payloads, tables


def _entity_to_payload(entity: dict) -> dict:
    """Mirror Structures/RunHistoryStructure.cs ActionPayload(TableEntity)."""
    ts = entity.get("Timestamp")
    if isinstance(ts, _dt.datetime):
        timestamp = ts.astimezone(_dt.timezone.utc).isoformat()
    else:
        timestamp = str(ts) if ts is not None else None
    inputs = payloads.decode_content(entity.get("InputsLinkCompressed"))
    outputs = payloads.decode_content(entity.get("OutputsLinkCompressed"))
    return {
        "Timestamp": timestamp,
        "ActionName": entity.get("ActionName") or entity.get("TriggerName"),
        "InputContent": inputs.actual_content,
        "OutputContent": outputs.actual_content,
        "RepeatItemIdenx": entity.get("RepeatItemIndex"),
        "FlowRunSequenceId": entity.get("FlowRunSequenceId"),
    }


def retrieve_action_payload(
    workflow_name: str = typer.Option(
        ..., "-wf", "--workflow-name", help="Workflow name (FlowName)."
    ),
    date: str = typer.Option(
        ..., "-d", "--date", help="Date in yyyyMMdd format.",
    ),
    action_name: str = typer.Option(
        ..., "-a", "--action-name",
        help="Action or trigger name to retrieve payloads for.",
    ),
    output_folder: Path = typer.Option(
        Path("."), "-o", "--output",
        help="Destination folder for the JSON dump (default: current dir).",
    ),
) -> None:
    """Dump every input/output payload for an action on the given date."""
    try:
        min_ts = _dt.datetime.strptime(date, "%Y%m%d").replace(
            tzinfo=_dt.timezone.utc
        )
    except ValueError as exc:
        raise typer.BadParameter(
            f"--date must be in yyyyMMdd format, got {date!r}"
        ) from exc
    max_ts = min_ts + _dt.timedelta(days=1)
    min_iso = min_ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    max_iso = max_ts.strftime("%Y-%m-%dT%H:%M:%SZ")

    trigger_filter = (
        f"CreatedTime ge datetime'{min_iso}' "
        f"and CreatedTime le datetime'{max_iso}' "
        f"and TriggerName eq '{action_name}'"
    )
    action_filter = (
        f"CreatedTime ge datetime'{min_iso}' "
        f"and CreatedTime le datetime'{max_iso}' "
        f"and ActionName eq '{action_name}'"
    )

    rows: list[dict] = []
    rows.extend(tables.query_history_table(workflow_name, trigger_filter))
    rows.extend(tables.query_action_table(workflow_name, date, action_filter))

    if not rows:
        raise typer.BadParameter(
            "No records found, please verify the options you provided."
        )

    output_folder.mkdir(parents=True, exist_ok=True)
    out_file = output_folder / f"{workflow_name}_{date}_{action_name}.json"
    if out_file.exists():
        typer.echo(f"File {out_file} already exist, existing file will be overwritten.")
        out_file.unlink()
    decoded = [_entity_to_payload(r) for r in rows]
    out_file.write_text(json.dumps(decoded, indent=2), encoding="utf-8")
    typer.echo(
        f"Retrieved payload, please check {out_file} for detail information."
    )


def register(runs_app: typer.Typer) -> None:
    runs_app.command(
        "retrieve-action-payload",
        help="Dump inputs/outputs for an action on a date to JSON.",
    )(retrieve_action_payload)
