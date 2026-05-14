# Playbook — `ListVersions`

## 1. Identity

| Field | Value |
| --- | --- |
| .NET command | `ListVersions` |
| Category | workflow-management |
| C# entry binding | `Program.cs:112-127` |
| C# implementation | `Operations/ListVersion.cs` |
| Python target | `src/lat/commands/list_versions.py` → `workflow_app` |
| Risk level | safe (read-only) |

## 2. CLI options

| Flag | Required | Type |
| --- | --- | --- |
| `--workflow / -wf` | yes | str |

## 3. Behavior summary

List every historical `FLOWVERSION` row for a workflow name, sorted by
`FlowUpdatedTime` descending. Includes flowIds from prior delete-and-
recreate cycles.

Output columns: `Workflow ID | Version ID | Updated Time (UTC)`.

## 4. C# walk-through

1. `Operations/ListVersion.cs:11-14` — query main table by
   `FlowName eq '<wf>'`, select `RowKey, FlowId, FlowSequenceId,
   FlowUpdatedTime`, in-memory filter to rows whose RowKey contains
   `FLOWVERSION`, sort by `FlowUpdatedTime` descending.
2. `:16-19` — throw if empty.
3. `:21-32` — build a `ConsoleTable` with three columns and print.

## 5. Python outline

```python
# src/lat/commands/list_versions.py
import typer
from rich.table import Table
from rich.console import Console
from ..storage import tables

def register(parent: typer.Typer) -> None:
    @parent.command("list-versions")
    def _cmd(workflow: str = typer.Option(..., "--workflow", "-wf")) -> None:
        rows = [
            e for e in tables.query_main_table(
                f"FlowName eq '{workflow}'",
                ["RowKey", "FlowId", "FlowSequenceId", "FlowUpdatedTime"],
            )
            if "FLOWVERSION" in e["RowKey"]
        ]
        if not rows:
            raise typer.BadParameter(f"{workflow} not found in storage table.")
        rows.sort(key=lambda e: e["FlowUpdatedTime"], reverse=True)
        table = Table(title=f"Versions of {workflow}")
        table.add_column("Workflow ID")
        table.add_column("Version ID")
        table.add_column("Updated Time (UTC)")
        for e in rows:
            table.add_row(
                e["FlowId"], e["FlowSequenceId"],
                e["FlowUpdatedTime"].strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
        Console().print(table)
```

## 6. Side effects

Read-only on main definition table.

## 7. Safety

Always safe.

## 8. Output

Three-column rich table.

## 9. Failure modes

Workflow name typo → `BadParameter`.

## 10. Parity test

Args: `ListVersions -wf <wf>`. Capture stdout from both tools, strip ANSI
codes (the .NET ConsoleTable doesn't emit ANSI; the rich Table does — use
`Console(force_terminal=False)`), normalize whitespace, assert equal.

## 11. Registration

```python
from .commands.list_versions import register as _reg_lv
_reg_lv(workflow_app)
```
