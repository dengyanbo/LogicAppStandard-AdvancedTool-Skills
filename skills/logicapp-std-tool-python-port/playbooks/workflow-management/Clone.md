# Playbook — `Clone`

## 1. Identity

| Field | Value |
| --- | --- |
| .NET command | `Clone` |
| Category | workflow-management |
| C# entry binding | `Program.cs:89-109` |
| C# implementation | `Operations/Clone.cs` |
| Python target | `src/lat/commands/clone.py` → `workflow_app` |
| Risk level | mutating (creates new workflow in `wwwroot`) |

## 2. CLI options

| Flag | Required | Type | Notes |
| --- | --- | --- | --- |
| `--sourcename / -sn` | yes | str | existing workflow |
| `--targetname / -tn` | yes | str | must not exist |
| `--version / -v` | no | str (FlowSequenceId) | latest if absent |

## 3. Behavior summary

Take the definition of an existing workflow (latest, or a specified
version), and write it as a new workflow folder under `wwwroot`. Run
history is *not* copied — the new workflow gets a fresh flowId from the
runtime.

## 4. C# walk-through

1. `Operations/Clone.cs:12` — `identity = version?.ToUpper() ?? "FLOWIDENTIFIER"`.
   The "latest" mode looks for the FLOWIDENTIFIER row; a specific
   `-v` looks for a row whose RowKey contains the uppercased version.
2. `:14-16` — query main table by `FlowName == sourceName` and filter
   in-memory to rows whose RowKey contains `identity`.
3. `:18-21` — throw if none found.
4. `:23-28` — target path is `<root>\<targetName>`; refuse if it exists.
5. `:30` — `SaveDefinition` writes `workflow.json` (decompress + envelope).

## 5. Python outline

```python
# src/lat/commands/clone.py
import json, typer
from ..settings import settings
from ..storage import tables
from ..storage.compression import decompress

def register(parent: typer.Typer) -> None:
    @parent.command("clone")
    def _cmd(
        source: str  = typer.Option(..., "--sourcename", "-sn"),
        target: str  = typer.Option(..., "--targetname", "-tn"),
        version: str | None = typer.Option(None, "--version", "-v"),
    ) -> None:
        identity = version.upper() if version else "FLOWIDENTIFIER"
        entity = next(
            (e for e in tables.query_main_table(f"FlowName eq '{source}'")
             if identity in e["RowKey"]),
            None,
        )
        if entity is None:
            raise typer.BadParameter(
                "No workflow found; check workflow name and version."
            )
        target_path = settings.root_folder / target
        if target_path.exists():
            raise typer.BadParameter(
                "Workflow already exists; choose another target name."
            )
        target_path.mkdir(parents=True)
        decoded = decompress(entity["DefinitionCompressed"])
        envelope = {"definition": json.loads(decoded), "kind": entity["Kind"]}
        (target_path / "workflow.json").write_text(json.dumps(envelope, indent=2))
        typer.echo("Clone finished, please refresh workflow page")
```

## 6. Side effects

* Reads main definition table.
* Creates `<root>/<target>/workflow.json`.

## 7. Safety

* No confirmation prompt (the existence check is the guard).
* Trap #14 — index-vs-name; not applicable here since we use names.

## 8. Output

```
Clone finished, please refresh workflow page
```

## 9. Failure modes

* Target exists → `BadParameter`.
* `<root>` not writable (rare on Kudu) → `OSError`.

## 10. Parity test

Args: `Clone -sn <existing> -tn <fresh-name>`.
Assert `<root>/<fresh-name>/workflow.json` exists and matches expected
JSON envelope.

## 11. Registration

```python
from .commands.clone import register as _reg_clone
_reg_clone(workflow_app)
```
