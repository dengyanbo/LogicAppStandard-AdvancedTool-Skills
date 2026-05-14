"""`RetrieveFailures` — collect failure records (by date or by run id).

Mirrors `Operations/RetrieveFailures.cs`. Two CLI variants:

  * `lat runs retrieve-failures-by-date` — every failure on a date.
  * `lat runs retrieve-failures-by-run`  — every failure within one run id
    (looks up the run's CreatedTime first to compute the per-day table).

Control-flow actions (foreach/until) that fail purely because their inner
actions failed are filtered out — same `An action failed.` heuristic the
.NET tool uses.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import typer

from ..settings import settings
from ..storage import payloads, tables

_DEPENDENT_FAILURE_MSG = "An action failed. No dependent actions succeeded."


def _save_failure_logs(rows: list[dict], file_path: Path) -> None:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        # Skip control actions that have no payload AND no error.
        if (
            row.get("InputsLinkCompressed") is None
            and row.get("OutputsLinkCompressed") is None
            and row.get("Error") is None
        ):
            continue
        record = payloads.history_record(row)
        err = record.get("Error")
        if isinstance(err, dict) and isinstance(err.get("message"), str):
            if _DEPENDENT_FAILURE_MSG in err["message"]:
                continue
        run_id = str(row.get("FlowRunSequenceId") or "")
        grouped.setdefault(run_id, []).append(record)

    if not grouped:
        raise typer.BadParameter("No failure actions found in action table.")

    if file_path.exists():
        file_path.unlink()
        typer.echo("File already exists, the previous log file has been deleted")
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(grouped, indent=2), encoding="utf-8")
    typer.echo(f"Failure log generated, please check the file - {file_path}")


def retrieve_failures_by_date(
    workflow_name: str = typer.Option(
        ..., "-wf", "--workflow-name", help="Workflow name (FlowName)."
    ),
    date: str = typer.Option(
        ..., "-d", "--date", help="Date in yyyyMMdd format.",
    ),
    output_folder: Path = typer.Option(
        Path("."), "-o", "--output",
        help="Destination folder for the JSON dump.",
    ),
) -> None:
    """Dump every failure action on the given date."""
    rows = list(
        tables.query_action_table(workflow_name, date, "Status eq 'Failed'")
    )
    out_file = (
        output_folder
        / f"{settings.logic_app_name or 'unknown'}_{workflow_name}_{date}_FailureLogs.json"
    )
    _save_failure_logs(rows, out_file)


def retrieve_failures_by_run(
    workflow_name: str = typer.Option(
        ..., "-wf", "--workflow-name", help="Workflow name (FlowName)."
    ),
    run_id: str = typer.Option(
        ..., "-r", "--run-id", help="FlowRunSequenceId of the run to inspect.",
    ),
    output_folder: Path = typer.Option(
        Path("."), "-o", "--output",
        help="Destination folder for the JSON dump.",
    ),
) -> None:
    """Dump every failure action of a single run id."""
    run_rows = list(
        tables.query_run_table(
            workflow_name, f"FlowRunSequenceId eq '{run_id}'"
        )
    )
    if not run_rows:
        raise typer.BadParameter(
            f"Cannot find workflow run with run id: {run_id} of workflow: "
            f"{workflow_name}, please check your input."
        )
    typer.echo(
        "Workflow run id found in run history table. Retrieving failure actions."
    )
    created = run_rows[0].get("CreatedTime")
    if isinstance(created, _dt.datetime):
        date = created.astimezone(_dt.timezone.utc).strftime("%Y%m%d")
    elif isinstance(created, str):
        try:
            date = _dt.datetime.fromisoformat(
                created.replace("Z", "+00:00")
            ).astimezone(_dt.timezone.utc).strftime("%Y%m%d")
        except ValueError as exc:
            raise typer.BadParameter(
                f"Could not parse run CreatedTime: {created!r}"
            ) from exc
    else:
        raise typer.BadParameter("Run row missing CreatedTime.")

    rows = list(
        tables.query_action_table(
            workflow_name,
            date,
            f"Status eq 'Failed' and FlowRunSequenceId eq '{run_id}'",
        )
    )
    out_file = (
        output_folder
        / f"{settings.logic_app_name or 'unknown'}_{workflow_name}_{run_id}_FailureLogs.json"
    )
    _save_failure_logs(rows, out_file)


def register(runs_app: typer.Typer) -> None:
    runs_app.command(
        "retrieve-failures-by-date",
        help="Dump every failure action on the given date.",
    )(retrieve_failures_by_date)
    runs_app.command(
        "retrieve-failures-by-run",
        help="Dump every failure action of a single run id.",
    )(retrieve_failures_by_run)
