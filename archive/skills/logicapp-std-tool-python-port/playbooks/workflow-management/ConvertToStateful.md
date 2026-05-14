# Playbook — `ConvertToStateful`

## 1. Identity

| Field | Value |
| --- | --- |
| .NET command | `ConvertToStateful` |
| Category | workflow-management |
| C# entry binding | `Program.cs:220-238` |
| C# implementation | `Operations/ConvertToStateful.cs` |
| Python target | `src/lat/commands/convert_to_stateful.py` → `workflow_app` |
| Risk level | mutating (creates a new workflow with kind=Stateful) |

## 2. CLI options

| Flag | Required | Type |
| --- | --- | --- |
| `--sourcename / -sn` | yes | str (stateless workflow) |
| `--targetname / -tn` | yes | str (must not exist) |

## 3. Behavior summary

Clones a stateless workflow into a new workflow file, the runtime will
re-ingest it as **Stateful** because the LA runtime infers `Kind` from the
new workflow's path. **The C# code does not currently change the `Kind`
field** — it just calls `SaveDefinition` with the source entity (which has
`Kind=Stateless`). The Python port should fix this by overriding `Kind`
to `Stateful` in the envelope (verify against the canonical `microsoft/`
fork first).

> ⚠️ Some built-in actions (Service Bus peek-lock, etc.) won't run in a
> stateful workflow. Warn the user explicitly.

## 4. C# walk-through

1. `Operations/ConvertToStateful.cs:12-14` — find the FLOWIDENTIFIER row
   for `sourceName`.
2. `:16-19` — throw if missing.
3. `:21-26` — refuse if target folder exists.
4. `:28` — `SaveDefinition` — **bug**: this writes the source's
   `Kind=Stateless` verbatim. The fix in the Python port: substitute
   `Kind = "Stateful"` before writing.

## 5. Python outline

```python
# src/lat/commands/convert_to_stateful.py
import json, typer
from ..settings import settings
from ..storage import tables
from ..storage.compression import decompress

def register(parent: typer.Typer) -> None:
    @parent.command("convert-to-stateful")
    def _cmd(
        source: str = typer.Option(..., "--sourcename", "-sn"),
        target: str = typer.Option(..., "--targetname", "-tn"),
    ) -> None:
        entity = next(
            (e for e in tables.query_main_table(f"FlowName eq '{source}'")
             if "FLOWIDENTIFIER" in e["RowKey"]),
            None,
        )
        if entity is None:
            raise typer.BadParameter(f"Workflow {source} not found")
        target_path = settings.root_folder / target
        if target_path.exists():
            raise typer.BadParameter("Workflow already exists")
        target_path.mkdir(parents=True)
        decoded = decompress(entity["DefinitionCompressed"])
        envelope = {"definition": json.loads(decoded), "kind": "Stateful"}
        (target_path / "workflow.json").write_text(json.dumps(envelope, indent=2))
        typer.echo("Convert finished, please refresh workflow page")
        typer.echo(
          "WARNING: some built-in actions (Service Bus peek-lock, etc.) will "
          "not run in stateful mode; verify your trigger and actions are "
          "compatible.", err=True
        )
```

## 6. Side effects

Reads main table; writes `<root>/<target>/workflow.json`.

## 7. Safety

No confirmation prompt. Existence check guards accidental overwrite.

## 8. Output

```
Convert finished, please refresh workflow page
WARNING: …
```

## 9. Failure modes

Source missing / target exists → `BadParameter`.

## 10. Parity test

Two-step:
1. Run both .NET and Python with `-sn <stateless> -tn <fresh>`.
2. Diff resulting `workflow.json`. Expect the *Python* port to set
   `"kind": "Stateful"`; the .NET tool may leave it as `Stateless` (a
   pre-existing bug). Document this divergence in `MIGRATION-NOTES.md`.

## 11. Registration

```python
from .commands.convert_to_stateful import register as _reg_cts
_reg_cts(workflow_app)
```
