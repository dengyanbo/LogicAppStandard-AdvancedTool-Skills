"""`SearchInHistory` — search run-history action payloads for a keyword.

Mirrors `Operations/SearchInHistory.cs`. Reads the per-day actions
table, decodes each `InputsLinkCompressed` / `OutputsLinkCompressed`
column, and writes every matching row's HistoryRecords dict into a
single JSON file grouped by RunID.
"""
from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ..settings import settings
from ..storage import payloads, tables

console = Console()


def search_in_history(
    workflow_name: str = typer.Option(
        ..., "-wf", "--workflow-name", help="Workflow name (FlowName)."
    ),
    date: str = typer.Option(
        ..., "-d", "--date", help="Date in yyyyMMdd format.",
    ),
    keyword: str = typer.Option(
        ..., "-k", "--keyword",
        help="Substring to search for within inlined payload contents.",
    ),
    output_folder: Path = typer.Option(
        Path("."), "-o", "--output",
        help="Destination folder for the JSON dump (default: current dir).",
    ),
) -> None:
    """Search inlined action payloads on the given date for a keyword."""
    rows = list(
        tables.query_action_table(
            workflow_name,
            date,
            "InputsLinkCompressed ne '' or OutputsLinkCompressed ne ''",
        )
    )

    matched: list[dict] = []
    run_ids: list[str] = []
    for row in rows:
        in_dec = payloads.decode_content(row.get("InputsLinkCompressed"))
        out_dec = payloads.decode_content(row.get("OutputsLinkCompressed"))
        if in_dec.search_keyword(keyword) or out_dec.search_keyword(keyword):
            matched.append(row)
            run_id = str(row.get("FlowRunSequenceId") or "")
            if run_id and run_id not in run_ids:
                run_ids.append(run_id)

    if not matched:
        raise typer.BadParameter(
            f"No run hisotry input/output found with keyword {keyword}"
        )

    output_folder.mkdir(parents=True, exist_ok=True)
    out_file = (
        output_folder
        / f"{settings.logic_app_name or 'unknown'}_{workflow_name}_{date}_SearchResults.json"
    )
    if out_file.exists():
        out_file.unlink()
        typer.echo("File already exists, the previous log file has been deleted")

    grouped: dict[str, list[dict]] = {}
    for row in matched:
        run_id = str(row.get("FlowRunSequenceId") or "")
        grouped.setdefault(run_id, []).append(payloads.history_record(row))
    out_file.write_text(json.dumps(grouped, indent=2), encoding="utf-8")

    rid_table = Table(show_header=True, header_style="bold")
    rid_table.add_column("Run ID")
    for rid in run_ids:
        rid_table.add_row(rid)
    console.print(rid_table)

    typer.echo(f"Log generated, please check the file - {out_file}")


def register(runs_app: typer.Typer) -> None:
    runs_app.command(
        "search-in-history",
        help="Search inlined action payloads for a keyword on a given date.",
    )(search_in_history)
