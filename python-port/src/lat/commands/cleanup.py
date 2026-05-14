"""`CleanUpContainers` / `CleanUpTables` / `CleanUpRunHistory`.

Mirrors `Operations/CleanUpContainers.cs`, `CleanUpTables.cs`, and the
composite `CleanUpRunHistory` Program.cs sub-command (which is just
tables-then-containers).

The runtime stores per-workflow run-history in containers/tables whose
names embed the date as a yyyyMMdd suffix starting at offset 34 of the
full name (`flow<la_prefix:15><wf_prefix:15><yyyymmdd>...`). The .NET
tool deletes everything whose date suffix is strictly less than the
user-supplied `--date`.
"""
from __future__ import annotations

import datetime as _dt

import typer
from rich.console import Console
from rich.table import Table

from ..settings import settings
from ..storage import blobs, tables
from ..storage.prefix import logic_app_prefix, workflow_prefix

console = Console()


_DATE_OFFSET = 34
_DATE_LEN = 8


def _name_date_int(name: str) -> int | None:
    """Extract the yyyyMMdd integer from a runtime resource name (or None)."""
    if len(name) < _DATE_OFFSET + _DATE_LEN:
        return None
    chunk = name[_DATE_OFFSET : _DATE_OFFSET + _DATE_LEN]
    try:
        return int(chunk)
    except ValueError:
        return None


def _prefixes(workflow_name: str | None) -> list[str]:
    """Build the resource-name prefixes to scan for cleanup.

    Without a workflow name, scans the entire Logic App's resources
    (`flow<la_prefix>`). With a workflow name, scans every FlowId that
    has ever existed for that workflow.
    """
    la = settings.logic_app_name
    if not la:
        raise typer.BadParameter("WEBSITE_SITE_NAME is not set.")
    la_pref = logic_app_prefix(la)
    if not workflow_name:
        return [f"flow{la_pref}"]
    flow_ids = tables.list_flow_ids_by_name(workflow_name)
    if not flow_ids:
        raise typer.BadParameter(
            f"No FlowIds found for workflow {workflow_name}; check spelling."
        )
    return [f"flow{la_pref}{workflow_prefix(fid)}" for fid in flow_ids]


def _print_optional(items: list[str], header: str) -> None:
    typer.echo(
        f"There are {len(items)} {header} found, please enter \"P\" to print "
        "the list or press any other key to continue without print"
    )


def _validate_date(date: str) -> tuple[int, str]:
    try:
        parsed = _dt.datetime.strptime(date, "%Y%m%d")
    except ValueError as exc:
        raise typer.BadParameter(
            f"--date must be yyyyMMdd, got {date!r}"
        ) from exc
    return int(date), parsed.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# CleanUpContainers
# ---------------------------------------------------------------------------


def _cleanup_containers_impl(
    workflow_name: str | None,
    date: str,
    *,
    yes: bool,
) -> None:
    target_int, formatted = _validate_date(date)
    matched: list[str] = []
    for prefix in _prefixes(workflow_name):
        for name in blobs.list_containers_with_prefix(prefix):
            dt = _name_date_int(name)
            if dt is not None and dt < target_int:
                matched.append(name)
    if not matched:
        raise typer.BadParameter("No blob containers found.")
    typer.echo(f"There are {len(matched)} containers matched for deletion.")
    if not yes:
        typer.confirm(
            f"Deleted those container will cause run history data lossing "
            f"which executed before {formatted}",
            abort=True,
        )
    for name in matched:
        blobs.delete_container(name)
    typer.echo("Clean up succeeded")


def cleanup_containers(
    workflow_name: str = typer.Option(
        None, "-wf", "--workflow-name",
        help="(Optional) Workflow name. When omitted, scans the entire Logic App.",
    ),
    date: str = typer.Option(
        ..., "-d", "--date",
        help="Delete resources with date suffix before this date (yyyyMMdd, UTC).",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the confirmation prompt.",
    ),
) -> None:
    """Delete run-history blob containers older than the given date."""
    _cleanup_containers_impl(workflow_name, date, yes=yes)


# ---------------------------------------------------------------------------
# CleanUpTables
# ---------------------------------------------------------------------------


def _cleanup_tables_impl(
    workflow_name: str | None,
    date: str,
    *,
    yes: bool,
) -> None:
    target_int, formatted = _validate_date(date)
    matched: list[str] = []
    for prefix in _prefixes(workflow_name):
        for name in tables.list_tables_with_prefix(prefix):
            if not (name.endswith("actions") or name.endswith("variables")):
                continue
            dt = _name_date_int(name)
            if dt is not None and dt < target_int:
                matched.append(name)
    if not matched:
        raise typer.BadParameter("No storage tables found.")
    typer.echo(f"There are {len(matched)} storage tables matched for deletion.")
    if not yes:
        typer.confirm(
            f"Deleted those storage tables will cause run history data "
            f"lossing which executed before {formatted}",
            abort=True,
        )
    for name in matched:
        tables.delete_table(name)
    typer.echo("Clean up succeeded")


def cleanup_tables(
    workflow_name: str = typer.Option(
        None, "-wf", "--workflow-name",
        help="(Optional) Workflow name. When omitted, scans the entire Logic App.",
    ),
    date: str = typer.Option(
        ..., "-d", "--date",
        help="Delete resources with date suffix before this date (yyyyMMdd, UTC).",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the confirmation prompt.",
    ),
) -> None:
    """Delete run-history action/variable storage tables older than the date."""
    _cleanup_tables_impl(workflow_name, date, yes=yes)


# ---------------------------------------------------------------------------
# CleanUpRunHistory — composite
# ---------------------------------------------------------------------------


def cleanup_run_history(
    workflow_name: str = typer.Option(
        None, "-wf", "--workflow-name",
        help="(Optional) Workflow name. When omitted, scans the entire Logic App.",
    ),
    date: str = typer.Option(
        ..., "-d", "--date",
        help="Delete resources with date suffix before this date (yyyyMMdd, UTC).",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the confirmation prompts.",
    ),
) -> None:
    """Run CleanUpTables + CleanUpContainers for a single date threshold."""
    try:
        _cleanup_tables_impl(workflow_name, date, yes=yes)
    except typer.BadParameter as exc:
        if "No storage tables found" not in str(exc):
            raise
        typer.echo("No storage tables matched; continuing to container cleanup.")
    _cleanup_containers_impl(workflow_name, date, yes=yes)


def register(cleanup_app: typer.Typer) -> None:
    cleanup_app.command(
        "containers",
        help="Delete run-history blob containers older than the given date.",
    )(cleanup_containers)
    cleanup_app.command(
        "tables",
        help="Delete run-history storage tables older than the given date.",
    )(cleanup_tables)
    cleanup_app.command(
        "run-history",
        help="Delete both run-history storage tables and blob containers.",
    )(cleanup_run_history)
