"""`GenerateTablePrefix` — resolve a workflow name to its storage prefix.

Mirrors `Operations/GenerateTablePrefix.cs`. When called with just a
Logic App name (env var resolved), prints the LA prefix. When called
with a workflow name as well, queries the main definition table to
resolve `FlowName -> FlowId`, then prints both prefixes plus the
concatenated form used for per-workflow tables / containers.
"""
from __future__ import annotations

import typer

from ..settings import settings
from ..storage import tables
from ..storage.prefix import generate


def generate_table_prefix(
    workflow_name: str = typer.Option(
        None, "-wf", "--workflow-name",
        help="Workflow name. When supplied, the workflow prefix is also printed.",
    ),
) -> None:
    """Print the LA prefix (and optionally the workflow prefix) used by the runtime."""
    la_name = settings.logic_app_name
    if not la_name:
        raise typer.BadParameter(
            "WEBSITE_SITE_NAME is not set. Cannot derive Logic App prefix."
        )
    la_prefix = generate(la_name.lower())

    if not workflow_name:
        typer.echo(f"Logic App Prefix: {la_prefix}")
        return

    rows = list(
        tables.query_main_table(
            f"FlowName eq '{workflow_name}'",
            select=["FlowId"],
        )
    )
    if not rows:
        raise typer.BadParameter(
            f"{workflow_name} cannot be found in storage table, please check "
            "whether workflow is correct."
        )
    flow_id = str(rows[0].get("FlowId") or "")
    if not flow_id:
        raise typer.BadParameter("FlowId missing from main table row.")
    wf_prefix = generate(flow_id)
    typer.echo(f"Logic App Prefix: {la_prefix}")
    typer.echo(f"Workflow Prefix: {wf_prefix}")
    typer.echo(f"Combined prefix: {la_prefix}{wf_prefix}")


def register(tools_app: typer.Typer) -> None:
    tools_app.command(
        "generate-table-prefix",
        help="Resolve workflow name to runtime storage prefix.",
    )(generate_table_prefix)
