"""`IngestWorkflow` — push a locally-edited workflow.json into the storage tables.

Mirrors `Operations/IngestWorkflow.cs`. Reads `<wwwroot>/<workflowName>/workflow.json`,
compresses its `definition` field, and force-updates the newest 4 rows in
the main definition table + newest 2 rows in the per-workflow `flows`
table with the new compressed payload and a fresh `ChangedTime`.

This is an experimental, destructive command in the .NET tool. The
Python port keeps the same semantics, but adds a `--yes` flag to skip
the confirmation prompt for scripted use, and an `--input` option so
the workflow.json can be sourced from a path other than wwwroot.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import typer

from ..settings import settings
from ..storage import compression, tables
from ..storage.prefix import main_definition_table, per_flow_table


def _changed_time_dt(entity: dict) -> _dt.datetime:
    value = entity.get("ChangedTime")
    if isinstance(value, _dt.datetime):
        return value
    if isinstance(value, str):
        try:
            return _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return _dt.datetime.min.replace(tzinfo=_dt.timezone.utc)
    return _dt.datetime.min.replace(tzinfo=_dt.timezone.utc)


def ingest_workflow(
    workflow_name: str = typer.Option(
        ..., "-wf", "--workflow-name", help="Workflow name (FlowName)."
    ),
    input_path: Path = typer.Option(
        None, "--input", "-i",
        help="Path to the workflow.json to ingest. Defaults to "
        "<wwwroot>/<workflowName>/workflow.json.",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the experimental-feature prompt.",
    ),
) -> None:
    """Force-update the storage tables with a new workflow definition."""
    if not yes:
        typer.echo(
            "Warning: this is an experimental feature. It mutates the "
            "storage tables directly and may bypass safety checks; broken "
            "workflows can result."
        )
        typer.confirm("Continue?", abort=True)

    path = input_path or (settings.root_folder / workflow_name / "workflow.json")
    if not path.is_file():
        raise typer.BadParameter(
            f"Cannot find definition Json file based on workflow path ({path}), "
            "please check the Workflow name and verify whether file exists in Kudu"
        )
    template = json.loads(path.read_text(encoding="utf-8"))
    definition_json = json.dumps(template.get("definition") or {})
    compressed = compression.compress(definition_json)

    la_name = settings.logic_app_name
    if not la_name:
        raise RuntimeError("WEBSITE_SITE_NAME is not set")

    # Latest 4 rows by ChangedTime in the main definition table.
    main_rows = list(
        tables.query_main_table(f"FlowName eq '{workflow_name}'")
    )
    main_rows.sort(key=_changed_time_dt, reverse=True)
    main_targets = main_rows[:4]

    # Latest 2 rows in the per-workflow table.
    flow_id = tables._current_flow_id(workflow_name)
    wf_table_name = per_flow_table(la_name, flow_id, "flows")
    wf_rows = list(
        tables.query_paged(wf_table_name, f"FlowName eq '{workflow_name}'")
    )
    wf_rows.sort(key=_changed_time_dt, reverse=True)
    wf_targets = wf_rows[:2]

    now = _dt.datetime.now(_dt.timezone.utc)
    main_client = tables.table_client(main_definition_table(la_name))
    wf_client = tables.table_client(wf_table_name)

    for row in main_targets:
        update = {
            "PartitionKey": row["PartitionKey"],
            "RowKey": row["RowKey"],
            "DefinitionCompressed": compressed,
            "ChangedTime": now,
        }
        main_client.update_entity(update, mode="merge")

    for row in wf_targets:
        update = {
            "PartitionKey": row["PartitionKey"],
            "RowKey": row["RowKey"],
            "DefinitionCompressed": compressed,
            "ChangedTime": now,
        }
        wf_client.update_entity(update, mode="merge")

    typer.echo(
        f"Updated {len(main_targets)} row(s) in {main_definition_table(la_name)} "
        f"and {len(wf_targets)} row(s) in {wf_table_name}."
    )


def register(workflow_app: typer.Typer) -> None:
    workflow_app.command(
        "ingest-workflow",
        help="Push a local workflow.json into the storage tables (experimental).",
    )(ingest_workflow)
