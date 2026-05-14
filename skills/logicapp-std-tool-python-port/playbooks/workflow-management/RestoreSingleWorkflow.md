# Playbook — `RestoreSingleWorkflow` (deprecated)

## 1. Identity

| Field | Value |
| --- | --- |
| .NET command | `RestoreSingleWorkflow` |
| Status | **deprecated** (see `Program.cs:254-274`, `CHANGELOG.md` 2024-06-07) |
| Replacement | `RestoreWorkflowWithVersion` |

## 2. Required behavior in the Python port

For full parity, expose a stub command that prints the same deprecation
notice as the .NET tool and exits 0:

```python
# src/lat/commands/restore_single_workflow.py
import typer

def register(parent: typer.Typer) -> None:
    @parent.command("restore-single-workflow", hidden=True)
    def _cmd(
        workflow: str = typer.Option(..., "--workflow", "-wf"),
    ) -> None:
        """Deprecated — use restore-workflow-with-version instead."""
        typer.echo(
            'This command has been deprecated, please use '
            '"RestoreWorkflowWithVersion" instead.'
        )
```

The C# implementation lives in `Operations/RestoreSingleWorkflow.cs` but
its `OnExecute` handler is commented out (`Program.cs:264-271`), so we
mirror the no-op exit semantics. Hide from `--help` (`hidden=True`).

## 3. Parity test

Args: `RestoreSingleWorkflow -wf any`.

Capture stdout from both tools and assert equality (single line of
deprecation text).

## 4. Registration

```python
from .commands.restore_single_workflow import register as _reg_rsw
_reg_rsw(workflow_app)
```
