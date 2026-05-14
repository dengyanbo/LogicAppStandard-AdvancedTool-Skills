"""`RestoreWorkflowWithVersion` — interactive restore of a specific version.

Mirrors `Operations/RestoreWorkflowWithVersion.cs`. Prompts the user to
pick a FlowId (when multiple exist for the workflow name) and a
FlowSequenceId, then:

  * Writes the decoded definition to `<wwwroot>/<workflowName>/workflow.json`.
  * Dumps the row's `RuntimeContext` column (API-connection metadata) to
    `RuntimeContext_<workflowName>_<version>.json` in the current
    directory.

A `--flow-id` / `--version` pair can be supplied to skip the prompts.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import typer

from ..settings import settings
from ..storage import compression, tables


def _fmt_dt(value: object) -> str:
    if isinstance(value, _dt.datetime):
        return value.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value or "")


def _pick_flow_id(workflow_name: str) -> str:
    flows = tables.list_workflows_by_name(workflow_name)
    if len(flows) == 1:
        return str(flows[0].get("FlowId") or "")
    typer.echo(f"Multiple FlowIds found for {workflow_name}:")
    for i, f in enumerate(flows):
        typer.echo(
            f"  [{i}] FlowId={f.get('FlowId')} "
            f"ChangedTime={_fmt_dt(f.get('ChangedTime'))} "
            f"Kind={f.get('Kind')}"
        )
    idx = typer.prompt("Pick a FlowId by index", type=int)
    if idx < 0 or idx >= len(flows):
        raise typer.BadParameter(f"Index {idx} out of range")
    return str(flows[idx].get("FlowId") or "")


def _pick_version(workflow_name: str, flow_id: str) -> str:
    versions = tables.list_versions_by_id(flow_id)
    if len(versions) == 1:
        return str(versions[0].get("FlowSequenceId") or "")
    typer.echo(f"Versions for FlowId={flow_id}:")
    for i, v in enumerate(versions):
        typer.echo(
            f"  [{i}] FlowSequenceId={v.get('FlowSequenceId')} "
            f"ChangedTime={_fmt_dt(v.get('ChangedTime'))}"
        )
    idx = typer.prompt("Pick a version by index", type=int)
    if idx < 0 or idx >= len(versions):
        raise typer.BadParameter(f"Index {idx} out of range")
    return str(versions[idx].get("FlowSequenceId") or "")


def restore_workflow_with_version(
    workflow_name: str = typer.Option(
        ..., "-wf", "--workflow-name", help="Workflow name (FlowName)."
    ),
    flow_id: str = typer.Option(
        None, "--flow-id",
        help="FlowId to restore. If omitted, the user is prompted "
        "(or auto-selected when only one exists).",
    ),
    version: str = typer.Option(
        None, "-v", "--version",
        help="FlowSequenceId to restore. Defaults to interactive picker.",
    ),
    runtime_context_folder: Path = typer.Option(
        Path("."), "--runtime-context-output",
        help="Folder to write the RuntimeContext_*.json dump (default: cwd).",
    ),
) -> None:
    """Restore a specific historical workflow version to wwwroot."""
    selected_flow = flow_id or _pick_flow_id(workflow_name)
    selected_version = version or _pick_version(workflow_name, selected_flow)
    typer.echo(
        f"Restoring workflow {workflow_name} with ID {selected_flow} "
        f"and version ID {selected_version}."
    )

    rows = list(
        tables.query_main_table(
            f"FlowName eq '{workflow_name}' "
            f"and FlowId eq '{selected_flow}' "
            f"and FlowSequenceId eq '{selected_version}'",
            select=["FlowName", "ChangedTime", "DefinitionCompressed", "Kind",
                    "RuntimeContext"],
        )
    )
    if not rows:
        raise typer.BadParameter(
            f"No row found for {workflow_name}/{selected_flow}/{selected_version}"
        )
    entity = rows[0]

    flow_name = str(entity.get("FlowName") or workflow_name)
    target_folder = settings.root_folder / flow_name
    tables.save_definition(target_folder, "workflow.json", entity)
    typer.echo(
        f"Workflow: {flow_name} restored successfully, please refresh your "
        "workflow page."
    )

    runtime_ctx_bytes = entity.get("RuntimeContext")
    if isinstance(runtime_ctx_bytes, str):
        import base64

        runtime_ctx_bytes = base64.b64decode(runtime_ctx_bytes)
    if runtime_ctx_bytes:
        raw = compression.decompress(runtime_ctx_bytes) or ""
        if raw:
            runtime_context_folder.mkdir(parents=True, exist_ok=True)
            ctx_path = (
                runtime_context_folder
                / f"RuntimeContext_{workflow_name}_{selected_version}.json"
            )
            ctx_path.write_text(
                json.dumps(json.loads(raw), indent=2), encoding="utf-8"
            )
            typer.echo(
                f"Runtime context (API connection related information) for "
                f"{workflow_name} with version ID {selected_version} saved to "
                f"{ctx_path}. Please review and decide whether need to be "
                "manually added in connections.json."
            )


def register(workflow_app: typer.Typer) -> None:
    workflow_app.command(
        "restore-workflow-with-version",
        help="Restore a historical workflow version (+ dump RuntimeContext).",
    )(restore_workflow_with_version)
