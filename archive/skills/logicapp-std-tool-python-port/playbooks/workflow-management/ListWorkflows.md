# Playbook — `ListWorkflows`

## 1. Identity

| Field | Value |
| --- | --- |
| .NET command | `ListWorkflows` |
| Category | workflow-management |
| C# entry binding | `Program.cs:277-288` |
| C# implementation | `Operations/ListWorkflows.cs`, `Shared/WorkflowInfoQuery.cs` |
| Python target | `src/lat/commands/list_workflows.py` → `workflow_app` |
| Risk level | safe (read-only, but **interactive**) |

## 2. CLI options

None (the C# version is fully interactive). The Python port should add:

| Flag | Required | Type | Notes |
| --- | --- | --- | --- |
| `--workflow / -wf` | no | str | If given, skip first prompt. |
| `--flow-id / -id` | no | str | If given, skip second prompt. |
| `--no-interactive` | no | bool | Print first table only and exit. |

## 3. Behavior summary

Three-step drill-down:
1. Print a table of distinct workflow names with `Last Updated` and
   `Workflow Count` (how many flowIds share that name across history).
2. Prompt the user to select one → print a table of all flowIds for that
   name, marking the current one as "In Use" and the rest as "Deleted".
3. Prompt the user to select one flowId → print every historical
   `FLOWVERSION` row for that flowId with `Last Updated` timestamps.

## 4. C# walk-through

1. `Operations/ListWorkflows.cs:14` — `WorkflowsInfoQuery.ListAllWorkflows("FlowName")`
   queries the main table and groups by `FlowName`.
2. `:16-29` — build first ConsoleTable (Workflow Name, Last Updated UTC,
   Workflow Count) with auto-index column enabled.
3. `:31-33` — `CommonOperations.PromptInput(...)` blocks for an index;
   convert to 0-based.
4. `:35-49` — list flowIds for that workflow name, mark current vs
   deleted by comparing with `QueryCurrentWorkflowByName`.
5. `:51-62` — prompt for flowId index → `ListVersionsByID` → print.

## 5. Python outline

```python
# src/lat/commands/list_workflows.py
import typer
from rich.table import Table
from rich.console import Console
from ..storage import tables

def register(parent: typer.Typer) -> None:
    @parent.command("list-workflows")
    def _cmd(
        workflow: str | None = typer.Option(None, "--workflow", "-wf"),
        flow_id: str | None  = typer.Option(None, "--flow-id", "-id"),
        no_interactive: bool = typer.Option(False, "--no-interactive"),
    ) -> None:
        # Step 1: list distinct FlowName + last ChangedTime + count of flowIds
        ...
        # Step 2: if --workflow given, skip prompt; else interactive prompt
        ...
        # Step 3: if --flow-id given, skip prompt; else interactive
        ...
```

> Use `typer.prompt(..., type=int)` for the index prompts, validate range,
> 1-based input → 0-based index (trap #14).

## 6. Side effects

Read-only.

## 7. Safety

Always safe.

## 8. Output

Three rich tables, two interactive prompts between them.

## 9. Failure modes

* Empty main table → no-op + message.
* User cancels (Ctrl+C / empty input) → `UserCanceledException` → exit 1.

## 10. Parity test

Hard to fully automate because of prompts. Use `--workflow` and
`--flow-id` flags to run non-interactively, capture all three tables,
compare with .NET counterpart driven via stdin scripting.

## 11. Registration

```python
from .commands.list_workflows import register as _reg_lw
_reg_lw(workflow_app)
```
