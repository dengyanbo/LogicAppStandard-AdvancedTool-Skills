# Playbook — `RestoreWorkflowWithVersion`

## 1. Identity

| Field | Value |
| --- | --- |
| .NET command | `RestoreWorkflowWithVersion` |
| Category | workflow-management |
| C# entry binding | `Program.cs:818-833` |
| C# implementation | `Operations/RestoreWorkflowWithVersion.cs`, `Shared/WorkflowSelector.cs` |
| Python target | `src/lat/commands/restore_workflow_with_version.py` → `workflow_app` |
| Risk level | mutating (writes workflow.json + RuntimeContext file) |

## 2. CLI options

| Flag | Required | Type |
| --- | --- | --- |
| `--workflow / -wf` | yes | str |

The C# command also performs *interactive* selection of FlowId and
Version. The Python port should add:

| `--flow-id / -id`     | no | str | Bypass FlowId prompt |
| `--version / -v`      | no | str | Bypass Version prompt |
| `--yes`               | no | bool | Skip confirmation |

## 3. Behavior summary

Recreate a deleted workflow (or rewind an existing one) using a specific
historical FlowId + Version. Also extracts and saves the `RuntimeContext`
column (API connection metadata) to a sibling file the operator can fold
back into `connections.json` manually.

## 4. C# walk-through

1. `Operations/RestoreWorkflowWithVersion.cs:16` —
   `WorkflowSelector.SelectFlowIDByName(workflowName)` (interactive).
2. `:18` — `SelectVersionByFlowID(...)` (interactive).
3. `:22` — query main table with full filter
   `FlowName == X and FlowId == Y and FlowSequenceId == Z`.
4. `:25-28` — write `workflow.json` via `SaveDefinition`.
5. `:30-36` — decompress the `RuntimeContext` binary, pretty-print, write
   to `RuntimeContext_<workflowName>_<versionId>.json` in cwd.

## 5. Python outline

```python
# src/lat/commands/restore_workflow_with_version.py
import json, typer
from pathlib import Path
from ..settings import settings
from ..storage import tables
from ..storage.compression import decompress

def _select_flow_id(workflow: str, override: str | None) -> str:
    """Interactive flowId picker; honors override flag."""
    if override:
        return override
    # list distinct flowIds; show table; prompt user
    ...

def _select_version(workflow: str, flow_id: str, override: str | None) -> str:
    """Interactive version picker; honors override flag."""
    ...

def register(parent: typer.Typer) -> None:
    @parent.command("restore-workflow-with-version")
    def _cmd(
        workflow: str = typer.Option(..., "--workflow", "-wf"),
        flow_id: str | None = typer.Option(None, "--flow-id", "-id"),
        version: str | None = typer.Option(None, "--version", "-v"),
        yes: bool = typer.Option(False, "--yes"),
    ) -> None:
        fid = _select_flow_id(workflow, flow_id)
        ver = _select_version(workflow, fid, version)
        if not yes:
            typer.confirm(
                f"Restore workflow '{workflow}' (FlowId={fid}, Version={ver})?",
                abort=True,
            )
        entity = next(iter(tables.query_main_table(
            f"FlowName eq '{workflow}' and FlowId eq '{fid}' "
            f"and FlowSequenceId eq '{ver}'",
            ["FlowName", "ChangedTime", "DefinitionCompressed", "Kind",
             "RuntimeContext"],
        )), None)
        if entity is None:
            raise typer.BadParameter("No matching version found")

        decoded = decompress(entity["DefinitionCompressed"])
        envelope = {"definition": json.loads(decoded), "kind": entity["Kind"]}
        target = settings.root_folder / workflow / "workflow.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(envelope, indent=2))
        typer.echo(f"Workflow '{workflow}' restored.")

        runtime = decompress(entity.get("RuntimeContext"))
        if runtime:
            path = Path(f"RuntimeContext_{workflow}_{ver}.json")
            path.write_text(json.dumps(json.loads(runtime), indent=2))
            typer.echo(
                f"Runtime context saved to {path}. Review and manually update "
                "connections.json if needed."
            )
```

## 6. Side effects

* Writes `<root>/<workflow>/workflow.json`.
* Writes `RuntimeContext_<workflow>_<version>.json` in cwd.

## 7. Safety

* Interactive selection prevents accidental wrong-flowId restore.
* Add `--yes` to skip the final confirmation for CI.

## 8. Output

Two log lines + one runtime-context-saved note.

## 9. Failure modes

* No flowIds for the workflow name → empty selector → exit.
* `RuntimeContext` column missing on old rows → skip silently.

## 10. Parity test

Args: `RestoreWorkflowWithVersion -wf <wf> -id <id> -v <ver> --yes`.
Assert workflow.json bytes match and `RuntimeContext_*.json` content
matches.

## 11. Registration

```python
from .commands.restore_workflow_with_version import register as _reg_rwwv
_reg_rwwv(workflow_app)
```
