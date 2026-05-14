# Playbook — `Backup`

## 1. Identity

| Field | Value |
| --- | --- |
| .NET command | `Backup` |
| Category | workflow-management |
| C# entry binding | `Program.cs:28-44` |
| C# implementation | `Operations/Backup.cs` |
| Python target | `src/lat/commands/backup.py`, registered on `workflow_app` |
| Risk level | safe (read-only against storage; writes only local files) |

## 2. CLI options

| .NET flag | Python flag | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `-d/--date <yyyyMMdd>` | `--date / -d` | no | str (yyyymmdd) | `19700101` |

## 3. Behavior summary

For every workflow row in the **main definition table** whose `ChangedTime
>= date`, decompress `DefinitionCompressed`, prettify, and save to
`./Backup/<flowName>/LastModified_<ts>_<flowId>/<changedTime>_<flowSequenceId>.json`.
Also fetches site app settings via ARM and writes `./Backup/appsettings.json`
(non-fatal if the MI lacks the role).

## 4. C# logic walk-through

1. `Operations/Backup.cs:16-17` — create `./Backup` folder.
2. `Operations/Backup.cs:21-31` — try `AppSettings.GetRemoteAppsettings()`,
   write to `appsettings.json`; on failure log and continue.
3. `Operations/Backup.cs:33` — parse the `yyyyMMdd` date to
   `"yyyy-MM-ddT00:00:00Z"`.
4. `Operations/Backup.cs:39-41` — query main table filtered to
   `ChangedTime >= <date>` and `RowKey starts with MYEDGEENVIRONMENT_FLOWVERSION`
   (the post-filter is in-memory; the `$filter` only constrains by time).
5. `Operations/Backup.cs:43-46` — compute the latest `ChangedTime` per
   `FlowId` (used to name the per-flowId folder).
6. `Operations/Backup.cs:51-68` — for each entity: build the folder path
   `Backup/<flowName>/LastModified_<latestTs>_<flowId>`, filename
   `<entityTs>_<flowSequenceId>.json`; skip if the file already exists; call
   `CommonOperations.SaveDefinition(...)` which decompresses, wraps as
   `{"definition": <decoded>, "kind": "<Kind>"}`, pretty-prints, and writes.

## 5. Python implementation outline

```python
# src/lat/commands/backup.py
from datetime import datetime, timezone
from pathlib import Path
import json
import typer
from ..arm import get_appsettings
from ..storage import tables
from ..storage.compression import decompress

def register(parent: typer.Typer) -> None:
    @parent.command("backup")
    def _cmd(
        date: str = typer.Option(
            "19700101", "--date", "-d",
            help="Retrieve workflows modified on/after this UTC date (yyyyMMdd).",
        ),
        out_dir: Path = typer.Option(Path("./Backup"), "--out-dir"),
    ) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            settings_dict = get_appsettings()
            (out_dir / "appsettings.json").write_text(
                json.dumps(settings_dict, indent=2)
            )
        except Exception as e:
            typer.echo(f"[warn] cannot back up app settings: {e}", err=True)

        iso = datetime.strptime(date, "%Y%m%d").replace(tzinfo=timezone.utc).isoformat()
        iso = iso.replace("+00:00", "Z")

        entities = [
            e for e in tables.query_main_table(
                f"ChangedTime ge datetime'{iso}'",
                ["FlowName", "FlowSequenceId", "ChangedTime", "FlowId", "RowKey",
                 "DefinitionCompressed", "Kind"],
            )
            if e["RowKey"].startswith("MYEDGEENVIRONMENT_FLOWVERSION")
        ]

        latest_by_flow = {}
        for e in entities:
            cur = latest_by_flow.get(e["FlowId"])
            if cur is None or e["ChangedTime"] > cur:
                latest_by_flow[e["FlowId"]] = e["ChangedTime"]

        for e in entities:
            flow_id = e["FlowId"]
            flow_name = e["FlowName"]
            modified = e["ChangedTime"].strftime("%Y%m%d%H%M%S")
            latest = latest_by_flow[flow_id].strftime("%Y%m%d%H%M%S")
            folder = out_dir / flow_name / f"LastModified_{latest}_{flow_id}"
            file = folder / f"{modified}_{e['FlowSequenceId']}.json"
            if file.exists():
                continue
            folder.mkdir(parents=True, exist_ok=True)
            decoded = decompress(e["DefinitionCompressed"])
            envelope = {"definition": json.loads(decoded), "kind": e["Kind"]}
            file.write_text(json.dumps(envelope, indent=2))
        typer.echo(f"Backed up {len(entities)} workflow definition(s).")
```

## 6. Side effects & preconditions

* Reads main definition table; calls ARM `GET appsettings`.
* Writes `./Backup/**`.
* Requires `AzureWebJobsStorage`, `WEBSITE_SITE_NAME`. ARM call additionally
  needs the standard ARM env vars and a MI with **Website Contributor** or
  **Logic App Standard Contributor**.

## 7. Safety

* Safe. No confirmation prompts. No experimental banner.
* Skips existing files (idempotent re-runs).

## 8. Output format

Streamed log lines:

```
Retrieving appsettings...
Backup for appsettings succeeded.
Retrieving workflow definitions...
Found N workflow definitions, saving to folder...
Backup for workflow definitions succeeded.
```

## 9. Failure modes

* `WEBSITE_SITE_NAME` unset → raise `typer.BadParameter`.
* MI role missing → warning logged, continue without app settings dump.
* Trap #6 (Deflate path returns null) — if you see empty JSON envelopes
  for old flows, restore the Deflate fallback per
  `references/03-compression-codec.md` §2.

## 10. Parity test

Args: `Backup -d 20200101`.

Compare: `./Backup/` directory tree contents byte-for-byte (treat
`appsettings.json` as opaque; only assert it exists and is valid JSON).
For each `<workflow>/LastModified_*/<ts>_<seq>.json` file, assert the
parsed JSON is structurally equal.

## 11. Registration

```python
from .commands.backup import register as _reg_backup
_reg_backup(workflow_app)
```
