"""`CancelRuns` — flip Running/Waiting rows in the runs table to Cancelled.

Mirrors `Operations/CancelRuns.cs`. This is an experimental command in
the .NET tool: it talks directly to the storage table (not ARM) and
sets each in-flight run's `Status` to `"Cancelled"`. We mirror the
same behavior — including the race-condition tolerance (rows whose
status changes between the SELECT and UPDATE are counted as failures
and the user is told to re-run).
"""
from __future__ import annotations

import typer

from ..settings import settings
from ..storage import tables
from ..storage.prefix import per_flow_table


def cancel_runs(
    workflow_name: str = typer.Option(
        ..., "-wf", "--workflow-name", help="Workflow name (FlowName)."
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y",
        help="Skip the experimental-feature confirmation prompt.",
    ),
) -> None:
    """Cancel every Running/Waiting run in the workflow's runs table."""
    if not yes:
        typer.echo(
            "Warning: this is an experimental feature. Cancelling running "
            "instances will cause data loss and disables run history / "
            "resubmit for any waiting runs."
        )
        typer.confirm("Continue?", abort=True)

    rows = list(
        tables.query_run_table(
            workflow_name,
            "Status eq 'Running' or Status eq 'Waiting'",
            select=["Status", "PartitionKey", "RowKey"],
        )
    )
    if not rows:
        raise typer.BadParameter(
            f"There's no running/waiting runs of workflow {workflow_name}"
        )

    typer.echo(f"Found {len(rows)} run(s) in run table.")

    la = settings.logic_app_name
    if not la:
        raise RuntimeError("WEBSITE_SITE_NAME is not set")
    flow_id = tables._current_flow_id(workflow_name)
    runs_table = per_flow_table(la, flow_id, "runs")
    client = tables.table_client(runs_table)

    cancelled = 0
    failed = 0
    for row in rows:
        update = {
            "PartitionKey": row["PartitionKey"],
            "RowKey": row["RowKey"],
            "Status": "Cancelled",
        }
        try:
            client.update_entity(update, mode="merge")
            cancelled += 1
        except Exception:  # noqa: BLE001 - mirror .NET catch-all
            failed += 1

    typer.echo(f"{cancelled} runs cancelled sucessfully")
    if failed:
        typer.echo(
            f"{failed} runs cancelled failed due to status changed "
            "(it is an expected behavior while runs finished during "
            "canceling), please run command again to verify whether still "
            "have running instance or not."
        )


def register(runs_app: typer.Typer) -> None:
    runs_app.command(
        "cancel-runs",
        help="Cancel every Running/Waiting run of a workflow (experimental).",
    )(cancel_runs)
