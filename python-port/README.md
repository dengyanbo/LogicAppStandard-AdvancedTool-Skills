## Introduction

`lat` is a Python re-implementation of the [.NET 8 LogicAppAdvancedTool](https://github.com/microsoft/Logic-App-STD-Advanced-Tools).
It exposes the same set of commands for diagnosing, recovering, and operating
**Azure Logic Apps Standard** deployments at a level below what the Azure portal
exposes — workflow restore, version drilldown, run-history triage, storage cleanup,
network validation, etc.

Two reasons to use `lat` over the .NET tool:

1. **It works against modern Logic Apps with Entra ID storage.** The .NET tool only
   speaks the legacy `AzureWebJobsStorage` connection-string form; `lat` recognises
   the Azure Functions runtime convention (`AzureWebJobsStorage__accountName` +
   `DefaultAzureCredential`) so it works on instances configured with managed
   identity for storage.
2. **No installer, no compile.** Just `pip install -e .` (or `uv pip install -e .`)
   and you have `lat` on your PATH.

Please use `lat --help` or `lat <sub-app> <command> --help` for option-level docs.


## Installation

```powershell
# Windows (recommended: uv)
uv venv
.\.venv\Scripts\Activate.ps1
uv pip install -e ".[dev]"

# Or stock Python ≥ 3.11
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

Then `lat --help`.


## Configuration

`lat` reads its context from the same environment variables that the .NET tool
reads (auto-populated inside an Azure App Service / Functions host; export them
manually on a workstation when running against a remote LA):

| Env var | Purpose |
| --- | --- |
| `WEBSITE_SITE_NAME` | Logic App name |
| `WEBSITE_RESOURCE_GROUP` | Resource group |
| `WEBSITE_OWNER_NAME` | Subscription ID (`<sub>+<info>`; everything before `+` is parsed) |
| `REGION_NAME` | Azure region (e.g. `Australia East`) |
| `AzureWebJobsStorage` | Storage connection string (legacy form, required if **not** using managed identity for storage) |
| `AzureWebJobsStorage__accountName` | Storage account name (Entra ID / managed identity form) |
| `AzureWebJobsStorage__credential` | Set to `managedidentity` to opt in explicitly |
| `WEBSITE_CONTENTAZUREFILECONNECTIONSTRING` | Content file share (used by `site sync-to-local-*`) |
| `LAT_ROOT_FOLDER` *(optional)* | Override `C:\home\site\wwwroot` (handy for offline use) |

For local use, `lat` uses `azure-identity`'s `DefaultAzureCredential` chain, so
`az login` (or any other supported credential source) is enough to authenticate
against ARM and storage when in Entra ID mode.


## Commands

`lat` groups commands into six sub-apps. Run `lat <sub-app> --help` for the full
list and `lat <sub-app> <command> --help` for option-level docs.

| Sub-app | Command | Description |
| --- | --- | --- |
| `workflow` | `backup` | Retrieve all definitions in storage table and save as JSON. Also dumps `appsettings.json` via ARM. The storage table keeps deleted workflows for 90 days by default. |
| `workflow` | `decode` | Decode a workflow's `DefinitionCompressed` for a specific version to human-readable JSON on stdout. |
| `workflow` | `clone` | Clone a workflow into a new folder under `wwwroot` (optionally pin to a specific version). Same Logic App, same kind. |
| `workflow` | `convert-to-stateful` | Clone the FLOWIDENTIFIER row of a workflow into a new folder. |
| `workflow` | `revert` | Revert a workflow's `workflow.json` to a previous version. |
| `workflow` | `restore-workflow-with-version` | Restore a deleted workflow at a chosen version, and dump its `RuntimeContext_*.json` (API-connection metadata) for review. |
| `workflow` | `ingest-workflow` | **Experimental.** Force-update the storage tables with a locally-edited `workflow.json`, bypassing definition validation. |
| `workflow` | `merge-run-history` | **Destructive.** When a workflow was deleted and recreated with the same name, you lose run history; this command re-keys the deleted workflow's history to the new FlowId. Irreversible. |
| `workflow` | `list-workflows` | Interactive 3-level drill-down (name → FlowId → version) over every workflow ever seen by the storage table (includes deleted). |
| `workflow` | `list-workflows-summary` | Non-interactive: one row per workflow name. |
| `workflow` | `list-versions` | List every saved version (FLOWVERSION row) for a workflow. |
| `runs` | `retrieve-failures-by-date` | Dump every failure action on a given date to JSON. Filters out control actions that failed only because their inner actions failed. |
| `runs` | `retrieve-failures-by-run` | Dump every failure action of a single run id (looks up the run's date automatically). |
| `runs` | `retrieve-action-payload` | Dump inputs/outputs of a specific action / trigger on a date. |
| `runs` | `search-in-history` | Search inlined action payloads on a date for a keyword; emits matching run ids + a JSON dump grouped by run. |
| `runs` | `generate-run-history-url` | Emit Azure-portal monitor URLs for failed runs on a date, optionally filtered by a payload / error / status-code keyword. |
| `runs` | `batch-resubmit` | Bulk resubmit runs by status + date range. Throttle-aware (50 / 5 min). |
| `runs` | `cancel-runs` | **Destructive.** Cancel every Running / Waiting run of a workflow by writing `Status=Cancelled` directly into the runs table. Causes data loss. |
| `cleanup` | `containers` | Delete run-history blob containers older than a given date. |
| `cleanup` | `tables` | Delete run-history `*actions` / `*variables` storage tables older than a given date. |
| `cleanup` | `run-history` | Composite: tables + containers in one pass. |
| `validate` | `endpoint` | DNS + TCP + SSL handshake check for any HTTP(S) endpoint. |
| `validate` | `storage-connectivity` | DNS + TCP + auth probe for every backing storage service endpoint (Blob/Queue/Table/File). |
| `validate` | `sp-connectivity` | DNS + TCP probe for every Service Provider declared in `connections.json`. |
| `validate` | `workflows` | Runtime-validate every `workflow.json` under wwwroot via the Logic App hostruntime API. Catches errors the design-time portal validator misses. |
| `validate` | `scan-connections` | List connections (API connections + Service Providers) declared in `connections.json` but not used by any workflow. `--apply` removes them. |
| `validate` | `whitelist-connector-ip` | Add the regional Azure Connector IP range to a Storage / Key Vault / Event Hub firewall. The MI must have edit permission on the target service. |
| `site` | `snapshot-create` | Snapshot `wwwroot` + app settings to a local folder. Requires Website Contributor on the LA MI for the appsettings part. |
| `site` | `snapshot-restore` | Restore `wwwroot` + push app settings from a snapshot folder. |
| `site` | `sync-to-local-normal` | Interactive sync of `wwwroot` to a local folder (pulls from the LA's content file share). Run from your workstation. |
| `site` | `sync-to-local-auto` | Non-interactive sync (deletes non-excluded local subfolders first). |
| `site` | `sync-to-local-batch` | Run Auto mode against many Logic Apps from a JSON config. |
| `site` | `filter-host-logs` | Grab error / warning lines from `\LogFiles\Application\Functions\Host\`. |
| `tools` | `generate-prefix` | Offline Murmur prefix calculation (no table lookup). |
| `tools` | `generate-table-prefix` | Resolve a workflow name to its runtime storage prefix (LA prefix + workflow prefix + combined). Looks up FlowId in the main table. |
| `tools` | `runid-to-datetime` | Decode workflow start time from a run ID. |
| `tools` | `decode-zstd` | Decode a base64-encoded ZSTD blob to text (debug helper). |
| `tools` | `get-mi-token` | Acquire and print a Managed Identity / az-login bearer token. |
| `tools` | `restart` | Restart the Logic App site via ARM. |
| `tools` | `import-appsettings` | Import an app-settings JSON as machine env vars (Windows admin). |
| `tools` | `clean-environment-variable` | Remove env vars listed in an appsettings JSON (Windows admin). |

Commands present in the .NET tool but **not** ported here (deprecated or removed
upstream): `ClearJobQueue`, `RestoreSingleWorkflow`, `RestoreRunHistory`,
`RestoreAll`. See [`MIGRATION-NOTES.md`](MIGRATION-NOTES.md) for other
intentional deltas vs. the .NET tool.


## How to use (demo: restore a deleted workflow)

1. `az login` (or set the appropriate env credential), then export the LA env vars:

   ```powershell
   $env:WEBSITE_SITE_NAME      = "MyLogicApp"
   $env:WEBSITE_RESOURCE_GROUP = "my-rg"
   $env:WEBSITE_OWNER_NAME     = "<subscription-id>+<region>-<webspace>"
   $env:REGION_NAME            = "Australia East"
   $env:AzureWebJobsStorage__accountName = "mystorage"   # AAD storage mode
   ```

2. List every workflow ever seen by the storage table (includes deleted):

   ```powershell
   lat workflow list-workflows-summary
   ```

3. Pick the workflow you want to restore and look at its versions:

   ```powershell
   lat workflow list-versions -wf MyDeletedWorkflow
   ```

4. Restore it at a chosen version:

   ```powershell
   lat workflow restore-workflow-with-version `
       -wf MyDeletedWorkflow `
       --flow-id <FlowId-from-step-2> `
       -v <FlowSequenceId-from-step-3>
   ```

5. Refresh the Logic App workflows page in the portal; the workflow is back.
   The command also dumps a `RuntimeContext_<wf>_<ver>.json` next to where you ran
   it; review it and copy any API-connection entries you still need into
   `connections.json`.


## Common issues

1. **`Backup` and `snapshot-create` need to retrieve appsettings.** Done via the
   ARM web SDK, so the credential `lat` is using (MI inside Kudu, or your `az login`
   identity locally) needs Website Contributor or Logic App Standard Contributor on
   the Logic App. Without it, the appsettings dump is skipped with a warning and
   the rest of the command continues.
2. **`whitelist-connector-ip` modifies other resources.** The credential needs
   Storage Account Contributor / Key Vault Contributor / Event Hub Contributor (as
   appropriate) on the target.
3. **Storage account behind a Network Security Perimeter or firewall.** Storage
   data-plane requests will be rejected with `AuthorizationFailure: This request is
   not authorized by network security perimeter`. Either run from inside the
   allowed network range, or temporarily add your client IP to the perimeter's
   inbound access rules. RBAC alone is not sufficient.
4. **AAD storage but ARM still asks for a key.** Older Logic App deployments mix
   `AzureWebJobsStorage` (with key) and `AzureWebJobsStorage__accountName`. `lat`
   prefers the conn-string-with-key form when it sees one; unset
   `AzureWebJobsStorage` to force AAD mode.


## Limitations

1. `revert`, `clone`, `convert-to-stateful`, and `restore-workflow-with-version`
   only modify `workflow.json`. If the API-connection metadata was lost from
   `connections.json`, the restored workflow will not run until you add it back
   (the `RuntimeContext_*.json` dump can help).
2. By default the runtime evicts workflow definitions from the storage table after
   ~90 days of inactivity. After eviction, `decode` / `revert` / `restore-*` cannot
   recover them.
3. `search-in-history` (when `--include-blob` is added) skips run-history payloads
   stored as blobs larger than 1 MB to keep memory bounded. (Note: the
   `--include-blob` path is not yet implemented in this Python port; see
   [`MIGRATION-NOTES.md`](MIGRATION-NOTES.md).)
4. `merge-run-history --auto-create-target` (the .NET behaviour where the target
   workflow is created on the fly) is not implemented; the target workflow must
   already exist. See [`MIGRATION-NOTES.md`](MIGRATION-NOTES.md).
5. `cancel-runs` writes directly to the storage table, not via ARM. Some runs may
   transition state between the SELECT and UPDATE; the command counts those as
   "cancelled failed" and asks you to re-run for verification.


## Status

32 / 32 non-deprecated .NET commands ported. 296 unit tests pass with no Azure
network dependency (the in-memory `FakeTableServiceClient` /
`FakeBlobServiceClient` fixtures in `tests/conftest.py` cover the storage
SDK surface used by the tool). Real-data verified against a sandbox Logic App
running on Australia East with Entra ID storage; see commit history for details.

See [`MIGRATION-NOTES.md`](MIGRATION-NOTES.md) for the curated list of
intentional behavioural deltas vs. the .NET tool.


## License

MIT (same as the .NET source).

