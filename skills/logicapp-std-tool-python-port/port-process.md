# Port Process

Step-by-step procedure for porting `LogicAppAdvancedTool` to Python. Execute
the phases in order. Do not jump ahead — earlier phases produce artifacts
later phases depend on.

## Pre-flight: verify you have the source

```powershell
# The source repo should be cloned and reachable. The skill's reference docs
# cite paths relative to the repo root (e.g. Shared/AppSettings.cs:9-89).
git clone https://github.com/Drac-Zhang/Logic-App-STD-Advanced-Tools.git
# Or the canonical fork:
git clone https://github.com/microsoft/Logic-App-STD-Advanced-Tools.git
```

If both are present, prefer the `microsoft/` fork — it has fixes the
Drac-Zhang fork lacks. Note any divergences in a `DIVERGENCES.md` in the
output project.

---

## Phase 1 — Scaffold the Python project

1. `cp -r skills/logicapp-std-tool-python-port/scaffolding/* <output-project>/`
2. Edit `pyproject.toml`:
   * Set `name`, `version`, `authors`.
   * Confirm Python version pin (`>=3.11`).
3. Create a virtualenv and install in editable mode:
   ```bash
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1     # or `source .venv/bin/activate` on POSIX
   pip install -e ".[dev]"
   ```
4. Verify the bare CLI works:
   ```bash
   lat --help
   ```
   Should list a placeholder command list. No business logic yet.

## Phase 2 — Implement shared utilities

Order matters — later utilities depend on earlier ones.

| Module | Reference | C# source |
| --- | --- | --- |
| `lat/settings.py` | n/a | `Shared/AppSettings.cs` |
| `lat/storage/prefix.py` | `references/01-storage-prefix-hashing.md`, `references/02-partition-key.md` | `Shared/StoragePrefixGenerator.cs` |
| `lat/storage/compression.py` | `references/03-compression-codec.md` | `Shared/CompressUtility.cs`, `Shared/ContentDecoder.cs` |
| `lat/storage/tables.py` | `references/04-table-schema.md` | `Shared/TableOperations.cs`, `Shared/PageableTableQuery.cs` |
| `lat/storage/blobs.py` | n/a | (used inline in many Operations/*.cs) |
| `lat/storage/shares.py` | n/a | (used by SyncToLocal, Snapshot) |
| `lat/storage/queues.py` | n/a | `Operations/ClearJobQueue.cs` |
| `lat/msi.py` | `references/06-managed-identity.md` | `Shared/MSITokenService.cs` |
| `lat/arm.py` | `references/07-arm-endpoints.md` | `Shared/HttpOperations.cs`, `Shared/AppSettings.cs:91-115` |
| `lat/network.py` | `references/08-network-validation.md` | `Shared/NetworkValidator.cs`, `Shared/ServiceTagRetriever.cs` |

For each: read the C# source line-range cited above, read the matching
reference doc, then implement the Python module. **Write unit tests in
`tests/unit/` for every utility before moving on.** Hash and codec
implementations must have golden-vector tests (you can capture vectors by
running the .NET tool on a sandbox LA Std with debug output).

### Minimum unit-test vectors required before declaring Phase 2 done

* `storage/prefix.py`
  * `MurmurHash32(b"")` → known value (compute once against the .NET impl)
  * `MurmurHash64(b"")` → known value
  * Several real `(LogicAppName, flowId) → table-prefix` pairs harvested
    from a sandbox LA Std
* `storage/compression.py`
  * Round-trip a 1 KB JSON through ZSTD compress+decompress
  * Decode three real `DefinitionCompressed` values harvested from a
    sandbox storage table (both Deflate-era and ZSTD-era values)
* `storage/tables.py`
  * Paged query iterator with a synthetic in-memory table client
  * Transaction batcher honors the 100-entity-per-partition limit
* `msi.py`
  * Mocked MSI endpoint returning a token JSON; verify caching to
    `~/.cache/lat/mi-token.json`

## Phase 3 — Implement commands group by group

Order is chosen so that easier, read-only commands come first, building
confidence and revealing bugs in the shared layer before touching
destructive operations.

1. **Read-only / informational** (start here):
   * `ListWorkflows`, `ListVersions`, `GenerateTablePrefix`,
     `Tools GeneratePrefix`, `Tools RunIDToDateTime`, `Tools DecodeZSTD`,
     `Tools GetMIToken`, `ScanConnections`, `FilterHostLogs`
2. **Validation**:
   * `EndpointValidation`, `ValidateStorageConnectivity`,
     `ValidateSPConnectivity`, `ValidateWorkflows`
3. **Workflow definition mgmt**:
   * `Backup`, `Decode`, `Clone`, `ConvertToStateful`,
     `RestoreWorkflowWithVersion`, `Revert`, `IngestWorkflow`
4. **Run-history triage**:
   * `RetrieveFailures` (Date, Run), `SearchInHistory`,
     `GenerateRunHistoryUrl`, `RetrieveActionPayload`, `BatchResubmit`,
     `CancelRuns`
5. **Site / file mgmt**:
   * `Snapshot Create/Restore`, `SyncToLocal Normal/Auto/Batch`,
     `Tools ImportAppsettings`, `Tools CleanEnvironmentVariable`,
     `Tools Restart`
6. **Connector firewall**:
   * `WhitelistConnectorIP`
7. **Storage cleanup**:
   * `CleanUpContainers`, `CleanUpTables`, `CleanUpRunHistory`
8. **Destructive / experimental** (last — by now the shared layer is
   battle-tested):
   * `MergeRunHistory`, `ClearJobQueue`

For each command:
1. Open the matching playbook under `playbooks/<group>/<Command>.md`.
2. Read the cited C# source.
3. Implement in `src/lat/commands/<command>.py` exporting a Typer command.
4. Register the command in `src/lat/cli.py`.
5. Add the parity test from `validation/command-checklist.md`.

## Phase 4 — Parity validation

Follow `validation/parity-test-plan.md`. In short:

1. Provision a throwaway Logic App Standard in a dedicated subscription
   with the .NET tool deployed.
2. Capture a "before" snapshot of every storage table the tool touches
   (use `az storage table list` + per-table entity export).
3. Run the .NET tool's command and capture stdout + a "after" snapshot.
4. Restore the "before" snapshot.
5. Run the Python port with the same args and capture stdout + a "after"
   snapshot.
6. Diff the two "after" snapshots; differences other than RFC3339
   formatting and `Timestamp` values are bugs.
7. Diff stdout (whitespace-normalized).

Tick off the command in `validation/command-checklist.md` only when both
diffs pass.

## Phase 5 — Documentation & release

* Generate a top-level `README.md` for the output project (template under
  `scaffolding/README.md`).
* Add a `MIGRATION-NOTES.md` listing intentional deviations (e.g. config
  file path uses XDG instead of `C:\home\site\wwwroot`).
* Tag a `v0.1.0` release once all commands pass parity.

## Phase 6 — When you get stuck

Open [`troubleshooting.md`](./troubleshooting.md). It maps observable
symptoms (wrong table name, garbage decompression, orphaned rows, etc.)
to root causes in the codebase.
