"""`ConvertToStateful` — clone the FLOWIDENTIFIER row into a new folder.

Mirrors `Operations/ConvertToStateful.cs`. The .NET tool only writes
the source workflow's FLOWIDENTIFIER definition into a new folder; the
runtime treats the new workflow as a fresh entity and the user is
expected to flip the kind manually in the cloned `workflow.json` if
that's needed.
"""
from __future__ import annotations

import typer

from ..settings import settings
from ..storage import tables


def convert_to_stateful(
    source_name: str = typer.Option(
        ..., "-s", "--source-name", help="Source workflow name."
    ),
    target_name: str = typer.Option(
        ..., "-t", "--target-name", help="Destination workflow name."
    ),
) -> None:
    """Convert a workflow to stateful by cloning its FLOWIDENTIFIER row."""
    rows = [
        r
        for r in tables.query_main_table(
            f"FlowName eq '{source_name}'",
            select=["RowKey", "DefinitionCompressed", "Kind"],
        )
        if "FLOWIDENTIFIER" in str(r.get("RowKey", ""))
    ]
    if not rows:
        raise typer.BadParameter(
            f"Workflow: {source_name} cannot be found in storage table, "
            "please check your input."
        )

    target_folder = settings.root_folder / target_name
    if target_folder.exists():
        raise typer.BadParameter(
            "Workflow already exists, workflow will not be cloned. "
            "Please use another target name."
        )

    tables.save_definition(target_folder, "workflow.json", rows[0])
    typer.echo("Convert finished, please refresh workflow page")


def register(workflow_app: typer.Typer) -> None:
    workflow_app.command(
        "convert-to-stateful",
        help="Clone a workflow's FLOWIDENTIFIER row into a new folder.",
    )(convert_to_stateful)
