"""`ListVersions` — show all FLOWVERSION rows for a workflow name.

Mirrors `Operations/ListVersion.cs`. Reads from the main definition table
and filters down to RowKeys containing `FLOWVERSION`, ordering by
`FlowUpdatedTime` descending.
"""
from __future__ import annotations

import datetime as _dt

import typer
from rich.console import Console
from rich.table import Table

from ..storage import tables

console = Console()


def _fmt_dt(value: object) -> str:
    if isinstance(value, _dt.datetime):
        return value.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, str):
        return value
    return ""


def list_versions(
    workflow_name: str = typer.Option(
        ..., "-wf", "--workflow-name",
        help="Workflow name (FlowName) to enumerate versions for.",
    ),
) -> None:
    """List every saved version (FLOWVERSION row) for a workflow."""
    rows = [
        r
        for r in tables.query_main_table(
            f"FlowName eq '{workflow_name}'",
            select=["RowKey", "FlowId", "FlowSequenceId", "FlowUpdatedTime"],
        )
        if "FLOWVERSION" in str(r.get("RowKey", ""))
    ]
    if not rows:
        raise typer.BadParameter(
            f"{workflow_name} cannot be found in storage table, please check whether "
            "workflow is correct."
        )
    rows.sort(
        key=lambda r: _fmt_dt(r.get("FlowUpdatedTime")) or "",
        reverse=True,
    )
    table = Table(show_header=True, header_style="bold")
    for col in ("Workflow ID", "Version ID", "Updated Time (UTC)"):
        table.add_column(col)
    for r in rows:
        table.add_row(
            str(r.get("FlowId") or ""),
            str(r.get("FlowSequenceId") or ""),
            _fmt_dt(r.get("FlowUpdatedTime")),
        )
    console.print(table)


def register(workflow_app: typer.Typer) -> None:
    workflow_app.command(
        "list-versions",
        help="List every saved version (FLOWVERSION row) for a workflow.",
    )(list_versions)
