"""`Revert` — overwrite local workflow.json with a specific FLOWVERSION row.

Mirrors `Operations/Revert.cs`. Reads the main table for the requested
`FlowSequenceId`, decompresses `DefinitionCompressed`, and writes it as
`workflow.json` under `<wwwroot>/<workflowName>/`.

The .NET tool prompts before overwriting. We expose a `--yes` flag to
suppress the prompt for scripted use.
"""
from __future__ import annotations

import typer

from ..settings import settings
from ..storage import tables


def revert(
    workflow_name: str = typer.Option(
        ..., "-wf", "--workflow-name", help="Workflow name to revert."
    ),
    version: str = typer.Option(
        ..., "-v", "--version", help="FlowSequenceId of the version to restore.",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the overwrite confirmation prompt.",
    ),
) -> None:
    """Revert the local workflow.json to a previous FLOWVERSION."""
    rows = list(
        tables.query_main_table(
            f"FlowSequenceId eq '{version}'",
            select=["DefinitionCompressed", "Kind"],
        )
    )
    if not rows:
        raise typer.BadParameter(
            f"No workflow definition found with version: {version}"
        )

    if not yes:
        typer.confirm(
            f"The current workflow: {workflow_name} will be overwritten. Continue?",
            abort=True,
        )

    target_folder = settings.root_folder / workflow_name
    tables.save_definition(target_folder, "workflow.json", rows[0])
    typer.echo("Revert finished, please refresh the workflow page")


def register(workflow_app: typer.Typer) -> None:
    workflow_app.command(
        "revert",
        help="Revert workflow.json to a previous FLOWVERSION.",
    )(revert)
