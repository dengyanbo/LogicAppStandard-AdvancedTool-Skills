# `lat` — Logic App Standard Advanced Tool (Python port)

A Python re-implementation of the .NET 8 [`LogicAppAdvancedTool`](https://github.com/microsoft/Logic-App-STD-Advanced-Tools)
console application. Manages Azure Logic Apps Standard at the storage / ARM
level with full command parity to the original `LogicAppAdvancedTool.exe`.

**Status:** 32 / 32 non-deprecated .NET commands ported. 285 unit tests
passing, zero Azure-network dependencies (storage tables and blob containers
are mocked via the in-memory fixture in [`tests/conftest.py`](tests/conftest.py)).

The commands omitted are the ones explicitly removed or marked deprecated in
the .NET source: `ClearJobQueue`, `RestoreSingleWorkflow`, `RestoreRunHistory`,
`RestoreAll`.

See [`MIGRATION-NOTES.md`](MIGRATION-NOTES.md) for the curated list of
intentional deltas vs. the .NET tool (paths, cache locations, etc.).

## Installation

```powershell
# Windows (recommended: uv)
uv venv
.\.venv\Scripts\Activate.ps1
uv pip install -e ".[dev]"

# Or stock Python
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

```bash
# POSIX
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Then:

```powershell
lat --help
```

## Configuration

The CLI reads its context from the same environment variables that the .NET
tool reads (auto-populated inside an Azure App Service / Functions host;
export them manually on a workstation when running against a remote LA):

| Env var | Purpose |
| --- | --- |
| `AzureWebJobsStorage` | Primary storage connection string |
| `WEBSITE_CONTENTAZUREFILECONNECTIONSTRING` | Content file share (used by `site sync-to-local-*`) |
| `WEBSITE_SITE_NAME` | Logic App name |
| `WEBSITE_RESOURCE_GROUP` | Resource group |
| `WEBSITE_OWNER_NAME` | Subscription ID (split on `+`) |
| `REGION_NAME` | Azure region |
| `MSI_ENDPOINT`, `MSI_SECRET` | Managed Identity token endpoint (set inside App Service automatically) |
| `LAT_ROOT_FOLDER` *(optional)* | Override `C:\home\site\wwwroot` (handy for tests / offline use) |

## Command reference

`lat` groups commands into six sub-apps. Quick overview — run
`lat <sub-app> --help` for option-level docs.

### `lat workflow` — workflow definition / version management

| Command | What it does | .NET equivalent |
| --- | --- | --- |
| `list-versions` | List every `FLOWVERSION` row for a workflow name. | `ListVersions` |
| `list-workflows` | Interactive 3-level drill-down (name → FlowId → version). | `ListWorkflows` |
| `list-workflows-summary` | Non-interactive: one row per workflow name. | `ListWorkflows` (printed table only) |
| `backup` | Back up workflow definitions + appsettings to a local folder. | `Backup` |
| `decode` | Decode a specific workflow version's definition to stdout. | `Decode` |
| `revert` | Revert local `workflow.json` to a previous `FLOWVERSION`. | `Revert` |
| `clone` | Clone an existing workflow into a new folder (optional version). | `Clone` |
| `convert-to-stateful` | Clone the `FLOWIDENTIFIER` row into a new folder. | `ConvertToStateful` |
| `restore-workflow-with-version` | Restore a historical version + dump `RuntimeContext_*.json`. | `RestoreWorkflowWithVersion` |
| `ingest-workflow` *(experimental)* | Force-update the storage tables with a locally-edited `workflow.json`. | `IngestWorkflow` |
| `merge-run-history` *(destructive)* | Re-key one workflow's run history into another. | `MergeRunHistory` |

### `lat runs` — run-history triage

| Command | What it does | .NET equivalent |
| --- | --- | --- |
| `batch-resubmit` | Bulk resubmit runs by status + date range (throttle-aware). | `BatchResubmit` |
| `retrieve-action-payload` | Dump inputs/outputs for an action on a date. | `RetrieveActionPayload` |
| `generate-run-history-url` | Emit Azure-portal monitor URLs for failed runs. | `GenerateRunHistoryUrl` |
| `search-in-history` | Search inlined action payloads for a keyword. | `SearchInHistory` |
| `retrieve-failures-by-date` | Dump every failure on a date (filters control-action noise). | `RetrieveFailures` (date mode) |
| `retrieve-failures-by-run` | Dump every failure within one run id. | `RetrieveFailures` (run mode) |
| `cancel-runs` *(experimental)* | Flip `Running` / `Waiting` rows to `Cancelled` in the runs table. | `CancelRuns` |

### `lat cleanup` — storage cleanup

| Command | What it does | .NET equivalent |
| --- | --- | --- |
| `containers` | Delete run-history blob containers older than a date. | `CleanUpContainers` |
| `tables` | Delete run-history action/variable tables older than a date. | `CleanUpTables` |
| `run-history` | Composite: tables + containers in one pass. | `CleanUpRunHistory` |

### `lat validate` — connectivity / configuration validation

| Command | What it does | .NET equivalent |
| --- | --- | --- |
| `endpoint` | DNS + TCP + SSL handshake check for any HTTP(S) endpoint. | `EndpointValidation` |
| `scan-connections` | Find connections declared but unused by any workflow. | `ScanConnections` |
| `sp-connectivity` | DNS + TCP probe for every Service Provider in `connections.json`. | `ValidateSPConnectivity` |
| `storage-connectivity` | DNS + TCP + auth probe for every backing storage service endpoint. | `ValidateStorageConnectivity` |
| `workflows` | Runtime-validate every `workflow.json` under wwwroot. | `ValidateWorkflows` |
| `whitelist-connector-ip` | Add Azure Connector IP range to a Storage / KV / EventHub firewall. | `WhitelistConnectorIP` |

### `lat site` — site / file management

| Command | What it does | .NET equivalent |
| --- | --- | --- |
| `filter-host-logs` | Filter error/warning lines from host logs. | `FilterHostLogs` |
| `snapshot-create` | Snapshot wwwroot + app settings to a local folder. | `Snapshot Create` |
| `snapshot-restore` | Restore wwwroot + push app settings from a snapshot folder. | `Snapshot Restore` |
| `sync-to-local-normal` | Interactive sync of wwwroot to a local folder. | `SyncToLocal Normal` |
| `sync-to-local-auto` | Non-interactive sync (cleans non-excluded subfolders first). | `SyncToLocal Auto` |
| `sync-to-local-batch` | Run Auto mode for many LAs from a JSON config. | `SyncToLocal Batch` |

### `lat tools` — utility / debug helpers

| Command | What it does | .NET equivalent |
| --- | --- | --- |
| `generate-prefix` | Offline Murmur prefix (no table lookup). | `Tools GeneratePrefix` |
| `runid-to-datetime` | Decode workflow start time from a run ID. | `Tools RunIDToDateTime` |
| `decode-zstd` | Decode a base64 compressed value. | `Tools DecodeZSTD` |
| `get-mi-token` | Acquire and print a Managed Identity token. | `Tools GetMIToken` |
| `restart` | Restart the Logic App site via ARM. | `Tools Restart` |
| `import-appsettings` | Import an app-settings JSON as machine env vars (Windows admin). | `Tools ImportAppsettings` |
| `clean-environment-variable` | Remove env vars listed in an appsettings JSON (Windows admin). | `Tools CleanEnvironmentVariable` |
| `generate-table-prefix` | Resolve workflow name to runtime storage prefix (table lookup). | `GenerateTablePrefix` |

## Development

```powershell
# Run the test suite
python -m pytest tests/unit

# Run a single test file
python -m pytest tests/unit/commands/test_backup.py -v

# Lint + type-check (optional)
ruff check src tests
mypy src
```

### Project layout

```
python-port/
├── pyproject.toml          # Hatchling build, deps, ruff/mypy/pytest config
├── README.md
├── MIGRATION-NOTES.md
└── src/lat/
    ├── cli.py              # Typer entry point + sub-app wiring
    ├── settings.py         # Env-var facade (mirrors AppSettings.cs)
    ├── auth.py             # azure.identity ManagedIdentityCredential wrapper
    ├── arm.py              # ARM helpers (web SDK + raw HTTPS for hostruntime)
    ├── logging_.py         # Logging configuration
    ├── network.py          # DNS / TCP / SSL probes
    ├── commands/           # One module per CLI command
    └── storage/
        ├── prefix.py       # Murmur32/64 + resource naming
        ├── compression.py  # ZSTD / Deflate codecs
        ├── tables.py       # Table CRUD + WorkflowsInfoQuery equivalents
        ├── payloads.py     # ContentDecoder + HistoryRecords
        ├── blobs.py        # Blob helpers (container list/delete, content fetch)
        ├── queues.py       # (stub)
        └── shares.py       # (stub)

tests/
├── conftest.py             # FakeTableServiceClient + FakeBlobServiceClient
│                           # + OData filter parser + fake_tables/fake_blobs/lat_env
└── unit/commands/          # One test file per command (or grouped by area)
```

### Adding a new command

1. Implement it in `src/lat/commands/<name>.py`.
2. The module must expose a `register(sub_app)` function that decorates a
   Typer callable with `@sub_app.command("<verb>", help="…")`.
3. Wire `register` into `src/lat/cli.py` (import + call).
4. Add unit tests in `tests/unit/commands/test_<name>.py`. Use the
   `fake_tables`, `fake_blobs`, and `lat_env` fixtures from `conftest.py`.

### Test conventions

- All Azure SDK calls are routed through helper functions in
  `lat/storage/*.py` and `lat/arm.py`, so tests can monkey-patch at module
  level rather than mocking the SDK directly.
- The `fake_tables` fixture supports the OData subset the .NET tool actually
  emits (`eq / ne / ge / gt / le / lt`, `and / or`, `datetime'...'`, string
  and integer literals). New filter shapes go in `tests/conftest.py`
  `_tokenize` / `_eval_filter`.
- Tests must not hit the network. Anything live goes behind a `@pytest.mark.live`
  marker and runs only when `pytest -m live` is invoked.

## Architecture notes

- **Authentication.** `auth.py` uses `azure.identity.ManagedIdentityCredential`
  inside an App Service host and falls back to `DefaultAzureCredential` on a
  workstation. The .NET tool's hand-rolled IMDS code path (`msi.py`) was
  intentionally dropped — `azure.identity` already handles the same cases.
- **ARM operations.** Site-level ops go through
  `azure.mgmt.web.WebSiteManagementClient`; hostruntime ops (`/runtime/...`
  validators, run resubmit / cancel) still use direct HTTPS with a bearer
  token because there's no SDK equivalent.
- **Storage tables.** Custom `TableClient` calls only; partition keys are
  derived via `storage/prefix.py::partition_key()` (Murmur32 % 2^20, 5-hex
  uppercase) and resource names via `main_definition_table()` /
  `per_flow_table()` / `per_day_action_table()`.
- **Compression parity.** The runtime stores definitions and run-history
  payloads with a custom ZSTD framing (algorithm byte in the low 3 bits of a
  LEB128 length prefix). `storage/compression.py` implements that exact
  framing — **do not** swap it for raw `zstandard.compress`.

## Migration notes vs. the .NET tool

The Python port is byte-for-byte parity for hashes, partition keys, and
compression. Behavioural deltas — paths, cache locations, prompts — are
documented in [`MIGRATION-NOTES.md`](MIGRATION-NOTES.md).

## License

MIT (same as the .NET source).

