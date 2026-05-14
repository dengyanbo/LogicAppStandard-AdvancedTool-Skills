# Playbook — `Decode`

## 1. Identity

| Field | Value |
| --- | --- |
| .NET command | `Decode` |
| Category | workflow-management |
| C# entry binding | `Program.cs:68-86` |
| C# implementation | `Operations/Decode.cs` |
| Python target | `src/lat/commands/decode.py` → `workflow_app` |
| Risk level | safe (read-only, stdout-only) |

## 2. CLI options

| Flag | Required | Type |
| --- | --- | --- |
| `--workflow / -wf` | yes | str |
| `--version  / -v`  | yes | str (FlowSequenceId) |

## 3. Behavior summary

Print a pretty-printed JSON of a specific historical workflow definition
to stdout. No files written. Used to inspect a version before reverting.

## 4. C# walk-through

1. `Operations/Decode.cs:13` — query main table for
   `FlowName eq '<wf>' and FlowSequenceId eq '<v>'`, select
   `DefinitionCompressed`, `Kind`, `RuntimeContext`.
2. `:15-18` — throw if not found.
3. `:20-22` — decompress `DefinitionCompressed`.
4. `:23` — wrap as `{"definition": <decoded>, "kind": "<Kind>"}`.
5. `:25-28` — JSON pretty-print and `Console.Write`.

## 5. Python outline

```python
# src/lat/commands/decode.py
import json, typer
from ..storage import tables
from ..storage.compression import decompress

def register(parent: typer.Typer) -> None:
    @parent.command("decode")
    def _cmd(
        workflow: str = typer.Option(..., "--workflow", "-wf"),
        version: str  = typer.Option(..., "--version", "-v"),
    ) -> None:
        entity = next(iter(tables.query_main_table(
            f"FlowName eq '{workflow}' and FlowSequenceId eq '{version}'",
            ["DefinitionCompressed", "Kind", "RuntimeContext"],
        )), None)
        if entity is None:
            raise typer.BadParameter(
                f"{workflow} with version {version} not found in storage table"
            )
        decoded = decompress(entity["DefinitionCompressed"])
        envelope = {"definition": json.loads(decoded), "kind": entity["Kind"]}
        typer.echo(json.dumps(envelope, indent=2), nl=False)
```

## 6. Side effects

* Reads main definition table. No writes.

## 7. Safety

Always safe. No prompts.

## 8. Output

Pretty-printed JSON to stdout (no trailing newline, mirroring C#'s
`Console.Write`).

## 9. Failure modes

Wrong `-wf`/`-v` combo → `BadParameter`.

## 10. Parity test

Run both tools with the same args, capture stdout, normalize whitespace
in JSON (load+dump), assert byte-equal.

## 11. Registration

```python
from .commands.decode import register as _reg_decode
_reg_decode(workflow_app)
```
