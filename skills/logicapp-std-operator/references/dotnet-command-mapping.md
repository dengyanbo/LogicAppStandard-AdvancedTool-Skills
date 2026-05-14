# Reference: .NET → `lat` command mapping

Users coming from `LogicAppAdvancedTool.exe` will type the classic PascalCase
command names. Translate silently and mention the mapping once in the reply.

## Complete mapping

| .NET command | `lat` equivalent | Notes |
| --- | --- | --- |
| `Backup -d <date>` | `lat workflow backup --date <date>` | `-o` / `--output` to redirect from `./Backup` |
| `Revert -wf X -v Y` | `lat workflow revert -wf X -v Y` | Add `--yes` for non-interactive |
| `Decode -wf X -v Y` | `lat workflow decode -wf X -v Y` | Stdout JSON |
| `Clone -s X -t Y [-v V]` | `lat workflow clone -s X -t Y [-v V]` | New folder under wwwroot |
| `ConvertToStateful -s X -t Y` | `lat workflow convert-to-stateful -s X -t Y` | Clones FLOWIDENTIFIER row only |
| `IngestWorkflow -wf X` | `lat workflow ingest-workflow -wf X` | Experimental; add `--yes` to skip prompt |
| `MergeRunHistory ...` | `lat workflow merge-run-history -s SRC -t TGT --start YYYYMMDD --end YYYYMMDD` | Auto-create-target branch NOT ported |
| `ListVersions -wf X` | `lat workflow list-versions -wf X` | |
| `ListWorkflows` | `lat workflow list-workflows` | Interactive prompts |
| `ListWorkflows` (script-friendly) | `lat workflow list-workflows-summary` | Non-interactive, one row per name (new in Python port) |
| `RestoreSingleWorkflow -wf X` | `lat workflow restore-workflow-with-version -wf X` | The .NET name was deprecated; `lat` only has the version-aware variant |
| `RestoreWorkflowWithVersion -wf X` | `lat workflow restore-workflow-with-version -wf X` | Add `--flow-id` and `-v` to skip prompts |
| `RetrieveFailures -wf X -d Y` | `lat runs retrieve-failures-by-date -wf X -d Y` | |
| `RetrieveFailures -wf X -r RUN` | `lat runs retrieve-failures-by-run -wf X -r RUN` | |
| `RetrieveActionPayload -wf X -d D -a A` | `lat runs retrieve-action-payload -wf X -d D -a A` | |
| `SearchInHistory -wf X -d D -k K` | `lat runs search-in-history -wf X -d D -k K` | |
| `GenerateRunHistoryUrl -wf X -d D [-f F]` | `lat runs generate-run-history-url -wf X -d D [-f F]` | |
| `BatchResubmit -wf X --from F --to T --status S` | `lat runs batch-resubmit -wf X --from F --to T --status S` | Throttle: 50 / 5 min |
| `CancelRuns -wf X` | `lat runs cancel-runs -wf X` | ⛔ Irreversible; add `--yes` only when you mean it |
| `CleanUpContainers -d D [-wf X]` | `lat cleanup containers -d D [-wf X]` | |
| `CleanUpTables -d D [-wf X]` | `lat cleanup tables -d D [-wf X]` | |
| `CleanUpRunHistory -d D [-wf X]` | `lat cleanup run-history -d D [-wf X]` | Composite |
| `Snapshot -mode Create` | `lat site snapshot-create` | |
| `Snapshot -mode Restore` | `lat site snapshot-restore` | |
| `SyncToLocal -mode Normal -sn S -cs CS -path P` | `lat site sync-to-local-normal -sn S -cs CS -path P` | Interactive prompts |
| `SyncToLocal -mode Auto -sn S -cs CS -path P` | `lat site sync-to-local-auto -sn S -cs CS -path P` | Non-interactive |
| `SyncToLocal -mode Batch -cf CONFIG` | `lat site sync-to-local-batch -cf CONFIG` | JSON config |
| `FilterHostLogs` | `lat site filter-host-logs` | |
| `EndpointValidation -e URL` | `lat validate endpoint -e URL` | |
| `ValidateStorageConnectivity` | `lat validate storage-connectivity` | Add `--skip-pe-check` if no Reader on sub |
| `ValidateSPConnectivity` | `lat validate sp-connectivity` | |
| `ValidateWorkflows` | `lat validate workflows` | |
| `ScanConnections [--apply]` | `lat validate scan-connections [--apply]` | |
| `WhitelistConnectorIP -id ID` | `lat validate whitelist-connector-ip -id ID` | Add `--dry-run` to preview |
| `GenerateTablePrefix [-wf X]` | `lat tools generate-table-prefix [-wf X]` | Note: `lat tools generate-prefix` is a *different* command (offline Murmur, no table lookup) |
| `Tools GeneratePrefix -la LA [-wf WF]` | `lat tools generate-prefix -la LA [-wf WF]` | Offline; matches the .NET `Tools` sub-command |
| `Tools RunIDToDateTime -id ID` | `lat tools runid-to-datetime -id ID` | |
| `Tools DecodeZSTD -d DATA` | `lat tools decode-zstd -d DATA` | |
| `Tools GetMIToken` | `lat tools get-mi-token` | |
| `Tools Restart` | `lat tools restart` | ⚠️ Causes ~30s downtime |
| `Tools ImportAppsettings -f FILE` | `lat tools import-appsettings -f FILE` | Windows admin |
| `Tools CleanEnvironmentVariable -f FILE` | `lat tools clean-environment-variable -f FILE` | Windows admin |

## Deprecated / removed in upstream .NET (do NOT execute)

If the user types any of these, explain politely that they were removed
upstream and offer the closest live equivalent.

| .NET command | Status | Closest `lat` equivalent |
| --- | --- | --- |
| `ClearJobQueue` | Deprecated | None — manipulating the job queue is no longer safe |
| `RestoreSingleWorkflow` | Deprecated | `lat workflow restore-workflow-with-version` |
| `RestoreRunHistory` | `#region REMOVED` in `Program.cs` | None — the auto-create-and-rekey behaviour is fragile by design; consider `merge-run-history` instead |
| `RestoreAll` | `#region REMOVED` in `Program.cs` | None — restoring every deleted workflow at once is rarely what you want; restore individual workflows with `restore-workflow-with-version` |

## Behavioural deltas the user should know

| .NET behaviour | `lat` behaviour |
| --- | --- |
| `Backup` always writes to `./Backup` | Default `./Backup`; `-o` flag to override |
| `RetrieveFailures` writes to current directory | Default current dir; `-o` flag to override |
| All destructive ops use interactive prompts | Interactive prompts kept + `--yes` for scripts |
| `MergeRunHistory` auto-creates the target workflow when missing | Not implemented; target must exist |
| `SearchInHistory --includeBlob` recurses into blob payloads | Not implemented (the blob credential plumbing is a stub) |
| `ListWorkflows` is always interactive | Two variants: `list-workflows` (interactive) + `list-workflows-summary` (script-friendly) |
| `Snapshot -mode X` is one command | Two commands: `snapshot-create` + `snapshot-restore` |
| `SyncToLocal -mode X` is one command | Three commands: `sync-to-local-normal` / `-auto` / `-batch` |
| `RetrieveFailures` is one command with date/run dispatch | Two commands: `retrieve-failures-by-date` + `retrieve-failures-by-run` |
| Token cache at `<temp>/MIToken.json` | `%LOCALAPPDATA%\lat\mi-token.json` (Windows) / `~/.cache/lat/mi-token.json` (POSIX) |
| Only reads `AzureWebJobsStorage` conn string | Also reads `AzureWebJobsStorage__accountName` etc. (AAD mode) |

When in doubt, link the user to
[`python-port/MIGRATION-NOTES.md`](../../python-port/MIGRATION-NOTES.md).
