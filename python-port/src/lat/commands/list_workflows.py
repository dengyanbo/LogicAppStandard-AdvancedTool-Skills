"""`ListWorkflows` — interactive 3-level drill-down through main definition table.

Mirrors `Operations/ListWorkflows.cs`. The .NET tool prompts the user
twice (pick workflow → pick FlowId → see versions). The Python port
keeps the interactive UX for `list-workflows` and exposes a
`list-workflows-summary` non-interactive variant useful for scripts and
tests.
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


def _summary_table(rows: list[dict]) -> Table:
    table = Table(show_header=True, header_style="bold")
    for col in ("#", "Workflow Name", "Last Updated (UTC)", "Workflow Count"):
        table.add_column(col)
    return table


def _print_summary(rows: list[dict]) -> None:
    table = _summary_table(rows)
    for i, r in enumerate(rows):
        name = str(r.get("FlowName") or "")
        try:
            siblings = tables.list_workflows_by_name(name)
            count = str(len(siblings))
        except RuntimeError:
            count = "0"
        table.add_row(str(i), name, _fmt_dt(r.get("ChangedTime")), count)
    console.print(table)


def list_workflows_summary() -> None:
    """Non-interactive: print one line per workflow name (latest version)."""
    rows = tables.list_all_workflows()
    _print_summary(rows)


def list_workflows() -> None:
    """Interactive 3-level drill-down: name -> FlowId -> version."""
    rows = tables.list_all_workflows()
    _print_summary(rows)
    typer.echo(
        "The workflow count is the total workflows detected with same workflow "
        "name but different FlowId which includes deleted workflows."
    )

    idx = typer.prompt(
        "Enter index to list all workflows with same name", type=int
    )
    if idx < 0 or idx >= len(rows):
        raise typer.BadParameter(f"Index {idx} out of range")

    selected_name = str(rows[idx].get("FlowName") or "")
    flows = tables.list_workflows_by_name(selected_name)
    current = tables.query_current_workflow_by_name(selected_name, ["FlowId"])
    current_id = str(current[0].get("FlowId")) if current else None

    typer.echo(f"All workflows named {selected_name} based on workflow ID:")
    flows_table = Table(show_header=True, header_style="bold")
    for col in ("#", "Flow ID", "Last Updated (UTC)", "Kind", "Status"):
        flows_table.add_column(col)
    for i, r in enumerate(flows):
        flow_id = str(r.get("FlowId") or "")
        flows_table.add_row(
            str(i),
            flow_id,
            _fmt_dt(r.get("ChangedTime")),
            str(r.get("Kind") or ""),
            "In Use" if flow_id == current_id else "Deleted",
        )
    console.print(flows_table)

    idx = typer.prompt(
        "Enter index to list all versions of selected workflow id", type=int
    )
    if idx < 0 or idx >= len(flows):
        raise typer.BadParameter(f"Index {idx} out of range")

    selected_flow_id = str(flows[idx].get("FlowId") or "")
    versions = tables.list_versions_by_id(selected_flow_id)
    versions_table = Table(show_header=True, header_style="bold")
    for col in ("Version ID", "Last Updated (UTC)"):
        versions_table.add_column(col)
    for r in versions:
        versions_table.add_row(
            str(r.get("FlowSequenceId") or ""),
            _fmt_dt(r.get("ChangedTime")),
        )
    console.print(versions_table)


def register(workflow_app: typer.Typer) -> None:
    workflow_app.command(
        "list-workflows",
        help="Interactive 3-level drill-down through the main definition table.",
    )(list_workflows)
    workflow_app.command(
        "list-workflows-summary",
        help="Non-interactive: one row per workflow name.",
    )(list_workflows_summary)
