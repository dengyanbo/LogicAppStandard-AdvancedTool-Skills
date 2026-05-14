"""`Decode` — print a specific workflow version's definition.

Mirrors `Operations/Decode.cs`. Reads the FLOWVERSION row matching
`FlowName eq <name>` AND `FlowSequenceId eq <version>`, decompresses
`DefinitionCompressed`, and emits the formatted JSON to stdout.
"""
from __future__ import annotations

import json

import typer

from ..storage import compression, tables


def decode(
    workflow_name: str = typer.Option(
        ..., "-wf", "--workflow-name", help="Workflow name (FlowName)."
    ),
    version: str = typer.Option(
        ..., "-v", "--version", help="FlowSequenceId of the version to decode.",
    ),
) -> None:
    """Print the decoded JSON definition for a specific workflow version."""
    rows = list(
        tables.query_main_table(
            f"FlowName eq '{workflow_name}' and FlowSequenceId eq '{version}'",
            select=["DefinitionCompressed", "Kind", "RuntimeContext"],
        )
    )
    if not rows:
        raise typer.BadParameter(
            f"{workflow_name} with version {version} cannot be found in storage table, "
            "please check your input."
        )

    entity = rows[0]
    compressed = entity.get("DefinitionCompressed")
    if isinstance(compressed, str):
        import base64

        compressed = base64.b64decode(compressed)
    if not compressed:
        raise typer.BadParameter(
            "DefinitionCompressed column is empty; cannot decode definition."
        )
    decoded = compression.decompress(compressed)
    if decoded is None:
        raise typer.BadParameter(
            "Failed to decompress DefinitionCompressed."
        )
    kind = entity.get("Kind") or ""
    payload = {"definition": json.loads(decoded), "kind": kind}
    typer.echo(json.dumps(payload, indent=2))


def register(workflow_app: typer.Typer) -> None:
    workflow_app.command(
        "decode",
        help="Decode a workflow version's definition to stdout.",
    )(decode)
