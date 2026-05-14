"""`ValidateWorkflows` — POST every workflow.json to the runtime validator.

Mirrors `Operations/ValidateWorkflows.cs`. The hostruntime API exposes a
`/workflows/{name}/validate` endpoint that returns 200 for valid
definitions and 400 (with a descriptive error body) for invalid ones.

This catches errors the design-time portal validator misses, e.g.
parameter-binding issues that only surface when the runtime instantiates
the workflow.
"""
from __future__ import annotations

import json
from pathlib import Path

import typer

from .. import arm
from ..settings import settings


def validate_workflows(
    root: Path = typer.Option(
        None, "--root",
        help=f"wwwroot containing workflow folders. Defaults to {settings.root_folder}.",
    ),
) -> None:
    """Runtime-validate every workflow.json under wwwroot via the hostruntime API."""
    root_path = root or settings.root_folder
    if not root_path.exists() or not root_path.is_dir():
        raise typer.BadParameter(f"Root folder does not exist: {root_path}")

    workflow_dirs = [
        d for d in sorted(root_path.iterdir())
        if d.is_dir() and (d / "workflow.json").exists()
    ]
    if not workflow_dirs:
        raise typer.BadParameter("No workflows found in Logic App.")

    typer.echo(f"Found {len(workflow_dirs)} workflow(s), start to validate...")

    output_lines: list[str] = []
    for wf_dir in workflow_dirs:
        raw_def = json.loads((wf_dir / "workflow.json").read_text(encoding="utf-8"))
        # The runtime validator expects {"properties": <workflow.json contents>}.
        envelope = {"properties": raw_def}
        ok, msg = arm.validate_workflow_definition(wf_dir.name, envelope)
        if ok:
            output_lines.append(f"{wf_dir.name}: Vaildation passed.")
        else:
            output_lines.append(
                f"{wf_dir.name}: Validation failed - Exception message: {msg}"
            )
    typer.echo("\n".join(output_lines))


def register(validate_app: typer.Typer) -> None:
    validate_app.command(
        "workflows",
        help="Runtime-validate every workflow.json under wwwroot.",
    )(validate_workflows)
