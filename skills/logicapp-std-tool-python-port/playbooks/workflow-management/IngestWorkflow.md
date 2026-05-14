# Playbook — `IngestWorkflow` (experimental)

## 1. Identity

| Field | Value |
| --- | --- |
| .NET command | `IngestWorkflow` |
| Category | workflow-management |
| C# entry binding | `Program.cs:393-407` |
| C# implementation | `Operations/IngestWorkflow.cs` |
| Python target | `src/lat/commands/ingest_workflow.py` → `workflow_app` |
| Risk level | **experimental** + **destructive** (bypasses runtime validation; corrupted workflow can prevent LA from starting) |

## 2. CLI options

| Flag | Required | Type |
| --- | --- | --- |
| `--workflow / -wf` | yes | str |
| `--yes` | no | bool (skip confirmation banner) |

## 3. Behavior summary

Read `<wwwroot>/<workflow>/workflow.json`, ZSTD-compress its `definition`
field, and *merge-write* the compressed blob into the most recent
FLOWVERSION rows of both the main definition table and the per-flow
`…flows` table — **without** validating the JSON. Used when a workflow is
semantically valid at runtime but fails design-time validation (e.g.
dynamic `@parameters('apiConnection')`).

## 4. C# walk-through

1. `Operations/IngestWorkflow.cs:15` — `AlertExperimentalFeature()` (red
   prompt, must answer "y").
2. `:17-24` — verify `<root>\<wf>\workflow.json` exists.
3. `:26-30` — parse the file as `WorkflowTemplate`, extract `definition`
   (object), serialize back to JSON string, ZSTD-compress.
4. `:32-33` — `BackupCurrentSite()` zips wwwroot to a sibling backup.
5. `:35-50` — query main definition table for the 4 most recent rows
   (`FLOWVERSION`, `FLOWIDENTIFIER`, `FLOWLOOKUP` mix sorted by
   `ChangedTime`), `MergeUpdate` each one's `DefinitionCompressed` and
   `ChangedTime` using ETag concurrency.
6. `:52-63` — same against the per-flow `…flows` table for the 2 most
   recent rows.

## 5. Python outline

```python
# src/lat/commands/ingest_workflow.py
import json, typer
from datetime import datetime, timezone
from azure.data.tables import UpdateMode
from ..settings import settings
from ..storage import tables
from ..storage.compression import compress
from ._common import experimental_alert, backup_site

def register(parent: typer.Typer) -> None:
    @parent.command("ingest-workflow")
    def _cmd(
        workflow: str = typer.Option(..., "--workflow", "-wf"),
        yes: bool = typer.Option(False, "--yes"),
    ) -> None:
        experimental_alert(yes=yes)
        wf_path = settings.root_folder / workflow / "workflow.json"
        if not wf_path.exists():
            typer.echo(f"Cannot find {wf_path}", err=True)
            raise typer.Exit(1)

        envelope = json.loads(wf_path.read_text())
        definition = envelope["definition"]
        compressed = compress(json.dumps(definition))

        backup = backup_site()
        typer.echo(f"wwwroot backup: {backup}")

        now = datetime.now(timezone.utc)
        table = tables.table_client(tables.main_definition_table(settings.logic_app_name))

        # Main table: top 4 rows by ChangedTime
        main_rows = sorted(
            tables.query_main_table(f"FlowName eq '{workflow}'"),
            key=lambda e: e["ChangedTime"],
            reverse=True,
        )[:4]
        for e in main_rows:
            ent = {
                "PartitionKey": e["PartitionKey"],
                "RowKey": e["RowKey"],
                "DefinitionCompressed": compressed,
                "ChangedTime": now,
            }
            table.update_entity(ent, mode=UpdateMode.MERGE, etag=e.metadata["etag"],
                                match_condition="IfMatch")

        # Per-flow flows table: top 2
        # ... resolve flow_id via query_current_workflow_by_name → workflow_table()
        # ... repeat MERGE update
```

## 6. Side effects

* **Writes 4 rows in the main definition table.**
* **Writes 2 rows in the per-flow flows table.**
* Creates a wwwroot zip backup in cwd.

## 7. Safety

* Always prints experimental banner; `--yes` bypasses prompt.
* Backs up wwwroot before mutating tables.
* Cannot be undone — restore from the backup zip + `Snapshot Restore`.

## 8. Output

```
IMPORTANT!!! This is an experimental feature ...
Y/N> y
Backup current workflows, you can find in path: <path>
```

## 9. Failure modes

* `workflow.json` malformed → JSON decode error → exit 1.
* ETag mismatch (someone edited concurrently) → re-fetch and retry once;
  fail on second mismatch (the C# code throws).
* Trap #4 — byte-perfect hash; double-check the main table name first by
  calling `table_exists`.

## 10. Parity test

Sandbox-only. Compare table contents before/after — only
`DefinitionCompressed`, `ChangedTime`, and `Timestamp` (system) should
differ.

## 11. Registration

```python
from .commands.ingest_workflow import register as _reg_ing
_reg_ing(workflow_app)
```
