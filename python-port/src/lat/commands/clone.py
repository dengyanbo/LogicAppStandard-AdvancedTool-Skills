"""`Clone` — copy a workflow's definition into a new workflow folder.

Mirrors `Operations/Clone.cs`. Picks one row from the main definition
table for the source workflow (either the FLOWIDENTIFIER row, or a row
with a specific FlowSequenceId if `--version` is supplied), decompresses
the definition, and writes it as `workflow.json` under
`<wwwroot>/<targetName>/`.
"""
from __future__ import annotations

import typer

from ..settings import settings
from ..storage import tables


def clone(
    source_name: str = typer.Option(
        ..., "-s", "--source-name", help="Source workflow name."
    ),
    target_name: str = typer.Option(
        ..., "-t", "--target-name", help="Destination workflow name."
    ),
    version: str = typer.Option(
        None, "-v", "--version",
        help="Version (FlowSequenceId) to clone. Defaults to current "
        "(FLOWIDENTIFIER row).",
    ),
) -> None:
    """Clone an existing workflow into a new folder under wwwroot."""
    identity_substr = "FLOWIDENTIFIER" if not version else version.upper()
    rows = [
        r
        for r in tables.query_main_table(
            f"FlowName eq '{source_name}'",
            select=["RowKey", "DefinitionCompressed", "Kind"],
        )
        if identity_substr in str(r.get("RowKey", ""))
    ]
    if not rows:
        raise typer.BadParameter(
            "No workflow found, please check provided workflow name and version."
        )

    target_folder = settings.root_folder / target_name
    if target_folder.exists():
        raise typer.BadParameter(
            "Workflow already exists, workflow will not be cloned. "
            "Please use another target name."
        )

    tables.save_definition(target_folder, "workflow.json", rows[0])
    typer.echo("Clone finished, please refresh workflow page")


def register(workflow_app: typer.Typer) -> None:
    workflow_app.command(
        "clone",
        help="Clone a workflow (with optional version) into a new folder.",
    )(clone)
