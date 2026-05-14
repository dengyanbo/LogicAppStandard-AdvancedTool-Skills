# Playbook — `Revert`

## 1. Identity

| Field | Value |
| --- | --- |
| .NET command | `Revert` |
| Category | workflow-management |
| C# entry binding | `Program.cs:47-65` |
| C# implementation | `Operations/Revert.cs` |
| Python target | `src/lat/commands/revert.py` → `workflow_app` |
| Risk level | mutating (overwrites the live workflow.json) |

## 2. CLI options

| .NET flag | Python flag | Required | Type |
| --- | --- | --- | --- |
| `-wf/--workflow` | `--workflow / -wf` | yes | str |
| `-v/--version` | `--version / -v` | yes | str (FlowSequenceId) |

## 3. Behavior summary

Locate the table row whose `FlowSequenceId == <version>`, decompress its
`DefinitionCompressed`, and overwrite `<wwwroot>/<workflow>/workflow.json`.

## 4. C# walk-through

1. `Operations/Revert.cs:14` — query main table by
   `FlowSequenceId eq '{version}'` → first row.
2. `:16-19` — throw `UserInputException` if not found.
3. `:21` — `CommonOperations.PromptConfirmation(...)` (banner: *"The
   current workflow: <name> will be overwrite!"*).
4. `:23` — `CommonOperations.SaveDefinition(<root>\\<workflow>,
   "workflow.json", entity)` — decompresses, wraps as `{"definition": ...,
   "kind": "..."}`, prettifies, writes.

## 5. Python implementation outline

```python
# src/lat/commands/revert.py
import json, typer
from ..settings import settings
from ..storage import tables
from ..storage.compression import decompress

def register(parent: typer.Typer) -> None:
    @parent.command("revert")
    def _cmd(
        workflow: str = typer.Option(..., "--workflow", "-wf"),
        version: str  = typer.Option(..., "--version", "-v"),
        yes: bool = typer.Option(False, "--yes", help="Skip confirmation."),
    ) -> None:
        entity = next(iter(tables.query_main_table(
            f"FlowSequenceId eq '{version}'")), None)
        if entity is None:
            raise typer.BadParameter(f"No workflow definition with version {version}")
        if not yes:
            typer.confirm(
                f"The current workflow '{workflow}' will be OVERWRITTEN. Continue?",
                abort=True,
            )
        decoded = decompress(entity["DefinitionCompressed"])
        envelope = {"definition": json.loads(decoded), "kind": entity["Kind"]}
        target = settings.root_folder / workflow / "workflow.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(envelope, indent=2))
        typer.echo("Revert finished, please refresh the workflow page")
```

## 6. Side effects & preconditions

* Reads main definition table.
* Writes `<root>/<workflow>/workflow.json`.
* The workflow folder must exist (otherwise we create it — the C# does too
  via `SaveDefinition`).

## 7. Safety

* Confirmation prompt always; bypass with `--yes` for CI.
* No experimental banner.
* Reversible only via another `Revert -v <olderVersion>` if the previous
  version is still in the main table (90-day retention).

## 8. Output

```
Revert finished, please refresh the workflow page
```

## 9. Failure modes

* Version typo → `UserInputException` ("No workflow definition found…").
* Trap #6 — Deflate decompression must remain enabled for old rows.

## 10. Parity test

Args: `Revert -wf <wf> -v <oldVersion> --yes`.
Assert `<root>/<wf>/workflow.json` content matches what the .NET tool wrote.

## 11. Registration

```python
from .commands.revert import register as _reg_revert
_reg_revert(workflow_app)
```
