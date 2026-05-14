# Migration notes: `lat` (Python port) vs. `LogicAppAdvancedTool.exe` (.NET)

This document catalogues every intentional behavioural delta between the
Python port and the canonical .NET tool. Hashing (Murmur32 / Murmur64),
partition-key derivation, compression framing, and storage-resource
naming are all **byte-for-byte identical** — any drift in those is a bug.

The deltas below are limited to UX, paths, caches, prompts, and
optional flags that were added to make scripted use easier.

## Authentication

| Concern | .NET tool | Python port |
| --- | --- | --- |
| Token acquisition | Hand-rolled IMDS HTTP call via `MSI_ENDPOINT` + `MSI_SECRET` | `azure.identity.ManagedIdentityCredential` (App Service) / `DefaultAzureCredential` (workstation) |
| Token cache location | `<tempdir>/MIToken.json` | `%LOCALAPPDATA%/lat/mi-token.json` (Windows), `~/.cache/lat/mi-token.json` (POSIX) |
| ARM operations | Direct HTTPS for every call | `azure.mgmt.web.WebSiteManagementClient` for site ops; direct HTTPS for hostruntime (`/runtime/...`) and run resubmit / cancel |

The new path means the .NET and Python tools do **not** share a token
cache. Run `lat tools get-mi-token` once to prime the new location.

## Output paths

| Command | .NET output | Python output |
| --- | --- | --- |
| `backup` | `./Backup/` | `./Backup/` (`--output` overrides) |
| `retrieve-action-payload` | `./<wf>_<date>_<action>.json` | `./<wf>_<date>_<action>.json` (`--output` overrides) |
| `generate-run-history-url` | `./<LA>_<wf>_<date>_RunHistoryUrl.json` | same (`--output` overrides) |
| `search-in-history` | `./<LA>_<wf>_<date>_SearchResults.json` | same (`--output` overrides) |
| `retrieve-failures-by-date` | `./<LA>_<wf>_<date>_FailureLogs.json` | same (`--output` overrides) |
| `retrieve-failures-by-run` | `./<LA>_<wf>_<runId>_FailureLogs.json` | same (`--output` overrides) |
| `restore-workflow-with-version` (`RuntimeContext_*.json`) | current directory | current directory (`--runtime-context-output` overrides) |

The `--output` flags are new in the Python port; defaults match the .NET
tool exactly.

## Confirmation prompts

The Python port adds a `--yes` / `-y` flag to every interactive
confirmation so the same command can be used in scripts and CI:

| Command | Default UX | `--yes` bypasses |
| --- | --- | --- |
| `workflow revert` | Confirm before overwriting `workflow.json` | the prompt |
| `workflow ingest-workflow` | Experimental warning | the prompt |
| `workflow merge-run-history` | Experimental warning | the prompt |
| `runs cancel-runs` | Experimental warning | the prompt |
| `cleanup containers` / `tables` / `run-history` | "Deleted those … data lossing …" warning | the prompts |
| `site sync-to-local-normal` | Two-step overwrite + cleanup prompt | the prompts (and selects "no cleanup") |

## Interactive selectors

The .NET tool prompts via `Console.ReadLine()`. The Python port keeps the
prompt for parity but also accepts explicit options to skip them:

| Command | New non-interactive option(s) |
| --- | --- |
| `workflow restore-workflow-with-version` | `--flow-id`, `--version` |
| `workflow list-workflows` | Use `list-workflows-summary` instead |

## Command additions / splits

| .NET command | Python split | Reason |
| --- | --- | --- |
| `SyncToLocal` (mode flag at runtime) | `site sync-to-local-normal` / `-auto` / `-batch` | Typer prefers verb-style sub-commands over a `--mode` switch |
| `Snapshot` (Create/Restore actions) | `site snapshot-create` / `snapshot-restore` | same reason |
| `RetrieveFailures` (date or run mode) | `runs retrieve-failures-by-date` / `-by-run` | same reason |
| `ListWorkflows` | `workflow list-workflows` (interactive) + `list-workflows-summary` (non-interactive) | summary mode is new; useful for scripts |

## Skipped commands

The following are marked deprecated or `#region REMOVED` in
`Program.cs` — the Python port does not implement them:

| .NET command | Why skipped |
| --- | --- |
| `ClearJobQueue` | Deprecated |
| `RestoreSingleWorkflow` | Deprecated; functionality covered by `restore-workflow-with-version` |
| `RestoreRunHistory` | Removed from `Program.cs` (`#region REMOVED`) |
| `RestoreAll` | Removed from `Program.cs` (`#region REMOVED`) |

## Partial implementations

| Concern | Status |
| --- | --- |
| `merge-run-history --auto-create-target` | Not implemented. The .NET tool creates an empty workflow and waits for the runtime to ingest it into the storage table (retry loop, up to 10 × 5s). This timing can't be simulated offline, so the Python port requires the target workflow to already exist. |
| `ContentDecoder.SearchKeyword(includeBlob=True)` | Not implemented. `payloads.search_keyword()` only checks inlined content; the .NET tool optionally fetches the blob URI and recurses. Adding this requires a working `storage/blobs.py::_shared_key_credential()` (currently a stub). Real-world use is rare enough that this can wait for a parity request. |
| `storage/queues.py`, `storage/shares.py` | Stub files. No command currently uses them at the storage-helper level (`sync-to-local-*` uses the SDK directly). |

## Test-only behaviour

Nothing in the production code path. Tests rely on the in-memory
`FakeTableServiceClient` and `FakeBlobServiceClient` defined in
`tests/conftest.py`; production calls land on the real Azure SDK.

## Versioning

| Aspect | Value |
| --- | --- |
| Python | ≥ 3.11 (pyproject `requires-python = ">=3.11"`) |
| Package version | `0.1.0` (see `pyproject.toml`) |
| Compatibility target | LogicAppAdvancedTool `.NET 8` as of commit `a4577c9` (master before the python-port branch landed) |
