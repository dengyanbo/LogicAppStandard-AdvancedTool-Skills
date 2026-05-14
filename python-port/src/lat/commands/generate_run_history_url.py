"""`GenerateRunHistoryUrl` — emit Azure-portal URLs for failed runs.

Mirrors `Operations/GenerateRunHistoryUrl.cs`. Queries the per-flow
`runs` table for failed runs on a given date, optionally drills into the
per-day `actions` table to filter by a keyword (matched against the
input/output payload, error body, or status code), and writes the
resulting Azure-portal run-monitor URLs to a JSON file.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from urllib.parse import quote

import typer

from ..settings import settings
from ..storage import payloads, tables


def _portal_url(
    workflow_name: str, run_id: str, region: str | None = None
) -> str:
    sub = settings.subscription_id or ""
    rg = settings.resource_group or ""
    la = settings.logic_app_name or ""
    loc = quote(region or settings.region or "", safe="")
    id_ = quote(
        f"/subscriptions/{sub}/resourcegroups/{rg}/providers/microsoft.web/"
        f"sites/{la}/workflows/{workflow_name}",
        safe="",
    )
    resource_id = quote(f"/workflows/{workflow_name}/runs/{run_id}", safe="")
    payload = quote('{"trigger":{"name":""}}', safe="")
    return (
        "https://portal.azure.com/#view/Microsoft_Azure_EMA/WorkflowMonitorBlade"
        f"/id/{id_}/location/{loc}/resourceId/{resource_id}"
        f"/runProperties~/{payload}/isReadOnly~/false"
    )


def _format_iso(value: object) -> str:
    if isinstance(value, _dt.datetime):
        return value.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, str):
        return value
    return ""


def _action_matches(entity: dict, keyword: str) -> bool:
    outputs = payloads.decode_content(entity.get("OutputsLinkCompressed"))
    if outputs.search_keyword(keyword):
        return True
    raw_error = payloads.decode_error(entity.get("Error"))
    if keyword in raw_error:
        return True
    code = entity.get("Code") or ""
    return keyword in str(code)


def generate_run_history_url(
    workflow_name: str = typer.Option(
        ..., "-wf", "--workflow-name", help="Workflow name (FlowName)."
    ),
    date: str = typer.Option(
        ..., "-d", "--date", help="Date in yyyyMMdd format.",
    ),
    filter_keyword: str = typer.Option(
        "", "-f", "--filter",
        help="Optional keyword: only emit runs whose actions match the keyword.",
    ),
    output_folder: Path = typer.Option(
        Path("."), "-o", "--output",
        help="Destination folder for the URL dump (default: current dir).",
    ),
) -> None:
    """Emit Azure-portal monitor URLs for failed runs on the given date."""
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
    run_filter = (
        f"Status eq 'Failed' and CreatedTime ge datetime'{min_iso}' "
        f"and EndTime le datetime'{max_iso}'"
    )

    runs = list(tables.query_run_table(workflow_name, run_filter))
    if not runs:
        raise typer.BadParameter(
            f"No failure runs detected for workflow {workflow_name} "
            f"on {min_ts.strftime('%Y-%m-%d')}"
        )

    results: list[dict] = []
    for run in runs:
        run_id = str(run.get("FlowRunSequenceId") or "")
        start = _format_iso(run.get("CreatedTime"))
        end = _format_iso(run.get("EndTime"))
        if filter_keyword:
            action_filter = (
                f"Status eq 'Failed' and FlowRunSequenceId eq '{run_id}'"
            )
            actions = list(
                tables.query_action_table(workflow_name, date, action_filter)
            )
            if not actions:
                continue
            if not any(_action_matches(a, filter_keyword) for a in actions):
                continue
        results.append(
            {
                "RunID": run_id,
                "StartTime": start,
                "EndTime": end,
                "RunHistoryUrl": _portal_url(workflow_name, run_id),
            }
        )

    if not results:
        raise typer.BadParameter(
            f"There's no failure run detect for filter: {filter_keyword}"
        )

    output_folder.mkdir(parents=True, exist_ok=True)
    out_file = (
        output_folder
        / f"{settings.logic_app_name or 'unknown'}_{workflow_name}_{date}_RunHistoryUrl.json"
    )
    if out_file.exists():
        out_file.unlink()
        typer.echo("File already exists, the previous log file has been deleted")
    out_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
    typer.echo(
        f"Failed run history url generated success, please check file {out_file}"
    )


def register(runs_app: typer.Typer) -> None:
    runs_app.command(
        "generate-run-history-url",
        help="Emit Azure-portal monitor URLs for failed runs on the given date.",
    )(generate_run_history_url)
