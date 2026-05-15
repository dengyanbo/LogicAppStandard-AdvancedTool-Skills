# Logic App Standard Advanced Tool

> ⚠️ **This repository has moved.** The actively maintained version now lives at
> **https://github.com/microsoft/Logic-App-STD-Advanced-Tools** — please use that for the
> latest builds, issues, and pull requests. The content below describes the codebase as it
> exists in this fork for reference.

`LogicAppAdvancedTool` is a self-contained .NET 8 console application that helps
engineers diagnose, recover, and operate **Azure Logic Apps Standard** deployments at a
level below what the Azure portal exposes. It works by talking directly to the Storage
Account that backs the Logic App (Tables, Blobs, Queues, File Share) and to the ARM
management plane via the site's Managed Identity.

Typical use cases:

- Restore an accidentally deleted workflow or roll back to a previous version.
- Recover or re-link run history after a workflow was overwritten (delete + recreate).
- Bulk resubmit, cancel, or audit historical runs.
- Diagnose storage / network / service-provider connectivity from inside the LA Standard host.
- Snapshot and restore `wwwroot` + app settings.
- Clean up old run-history tables and blob containers to control storage cost.

---

## Table of contents

- [How it works](#how-it-works)
- [Prerequisites](#prerequisites)
- [Getting the binary](#getting-the-binary)
- [Running on a Logic App Standard (Kudu)](#running-on-a-logic-app-standard-kudu)
- [Running locally](#running-locally)
- [Required Managed Identity roles](#required-managed-identity-roles)
- [Commands](#commands)
- [Project layout](#project-layout)
- [Safety notes](#safety-notes)
- [Building from source](#building-from-source)
- [Changelog](#changelog)
- [License](#license)

---

## How it works

Logic Apps Standard stores its workflow definitions, run history, action
inputs/outputs, variables, jobs, and queues in **Azure Storage** using opaque, hash-based
naming. Resource names follow the pattern:

```
flow<MurmurHash64(LogicAppName)><MurmurHash64(flowId)><suffix>
```

The tool re-implements the same Murmur32 / Murmur64 hashing the LA runtime uses (see
`Shared/StoragePrefixGenerator.cs`) so it can compute table, container, and queue names
without enumerating storage. Compressed payloads such as `DefinitionCompressed`,
`InputsLinkCompressed`, and `OutputsLinkCompressed` are handled by
`Shared/CompressUtility.cs`, which transparently supports both the legacy Deflate format
and the **ZSTD** format introduced by `ModernCompressionUtility` (Nov 2024). The vendored
`ZstdSharp.dll` and `Microsoft.WindowsAzure.ResourceStack.dll` in `DLLs/` provide those
codecs.

For control-plane operations (reading/writing app settings, restarting the site, batch
resubmit, whitelisting connector IPs, etc.), the tool acquires an AAD token from the
site's Managed Identity (`MSI_ENDPOINT` + `MSI_SECRET`) and calls ARM directly.

---

## Prerequisites

- A **Logic App Standard** site whose backing Storage Account is reachable.
- The site must have a System-assigned (or User-assigned) **Managed Identity** configured.
- For local execution: .NET 8 SDK and the ability to set machine environment variables.

The tool reads its context from these environment variables (they are normally set
automatically by App Service / Functions runtime):

| Variable | Used for |
| --- | --- |
| `AzureWebJobsStorage` | Primary storage connection string |
| `WEBSITE_CONTENTAZUREFILECONNECTIONSTRING` | File share that hosts `wwwroot` |
| `WEBSITE_SITE_NAME` | Logic App name |
| `WEBSITE_RESOURCE_GROUP` | Resource group |
| `WEBSITE_OWNER_NAME` | Used to extract Subscription ID |
| `REGION_NAME` | Azure region |
| `MSI_ENDPOINT`, `MSI_SECRET` | Managed Identity token endpoint |

---

## Getting the binary

You can build from source (see [Building from source](#building-from-source)) or grab the
latest release from the project's GitHub Releases page.

The result is a single folder containing `LogicAppAdvancedTool.exe` plus its
dependencies.

---

## Running on a Logic App Standard (Kudu)

1. Open the Logic App in the Azure portal → **Advanced Tools** → **Go** to open Kudu.
2. Open the **Debug console → CMD**.
3. Navigate to `C:\home\site\wwwroot` (or any sub-folder you prefer).
4. Drag-and-drop the contents of the tool's publish folder into the file pane to upload.
5. Run commands, for example:

   ```cmd
   LogicAppAdvancedTool.exe Backup
   LogicAppAdvancedTool.exe ListVersions -wf MyWorkflow
   LogicAppAdvancedTool.exe Revert -wf MyWorkflow -v 08584...
   ```

> The tool resolves the Logic App name automatically from `WEBSITE_SITE_NAME`, so the
> legacy `-la` option is no longer required.

---

## Running locally

Some commands (e.g. `SyncToLocal`) are designed to run from a workstation. Others can
also be used locally as long as you import the Logic App's app settings into your
machine's environment variables:

1. In the Azure portal, open the Logic App → **Configuration → Advanced edit** and copy
   the JSON of application settings into a file (e.g. `appsettings.json`).
2. Run:

   ```cmd
   LogicAppAdvancedTool.exe Tools ImportAppsettings -f .\appsettings.json
   ```

   This sets each key as a user environment variable on your machine.

3. When done, clean them up:

   ```cmd
   LogicAppAdvancedTool.exe Tools CleanEnvironmentVariable -f .\appsettings.json
   ```

A managed-identity token is cached in `Temp/MIToken.json` for local re-use and is
git-ignored.

---

## Required Managed Identity roles

Different commands require different RBAC roles on the Logic App's MI:

| Scenario | Required role |
| --- | --- |
| Read / write app settings, restart site | **Website Contributor** or **Logic App Standard Contributor** on the LA |
| Detect Storage private endpoint / service tags | **Reader** on the subscription |
| `WhitelistConnectorIP` | Permission to modify firewall on the target Storage Account / Key Vault / Event Hub |
| `BatchResubmit`, `CancelRuns` | Permission to call resubmit / cancel on the LA (Contributor) |

If the MI lacks a needed role, the tool will print a clear warning and skip that step
(e.g. `Backup` still backs up workflow definitions even when it cannot read app settings).

---

## Commands

The application uses `McMaster.Extensions.CommandLineUtils`. Every command supports `-?`
for help and most options accept short (`-x`) or long (`--longname`) forms.

### Workflow definition & version management

| Command | Options | Description |
| --- | --- | --- |
| `Backup` | `-d|--date yyyyMMdd` (optional, default 1970-01-01) | Pulls every workflow definition row from the storage table, decompresses it, and writes it to `./Backup/<workflow>/LastModified_<ts>_<flowId>/<modified>_<flowSequenceId>.json`. Also writes `appsettings.json`. |
| `Revert` | `-wf`, `-v` | Rolls a workflow back to a specific previous version. The current version is overwritten. |
| `Decode` | `-wf`, `-v` | Decompresses and prints a specific historical version as JSON (no write). |
| `Clone` | `-sn`, `-tn`, `-v` (optional) | Clones an existing workflow to a new name within the same Logic App. Run history is not copied. |
| `ConvertToStateful` | `-sn`, `-tn` | Clones a **stateless** workflow into a **stateful** workflow. Some built-in actions (e.g. Service Bus peek-lock) will not run after conversion. |
| `ListVersions` | `-wf` | Lists every historical version of a workflow (including older flow IDs if the workflow was deleted and recreated with the same name). |
| `ListWorkflows` | – | Lists all workflows present in the storage table — both currently deployed and recently deleted (~90-day retention). |
| `RestoreWorkflowWithVersion` | `-wf` | Interactive — pick which historical version of a deleted workflow to restore. Replaces `RestoreSingleWorkflow`. |
| `RestoreSingleWorkflow` | – | **Deprecated.** Use `RestoreWorkflowWithVersion`. |
| `IngestWorkflow` | `-wf` | **Experimental.** Reads `<workflow>/workflow.json` from `wwwroot` and writes it to the storage table **without runtime validation**. Useful when valid runtime definitions fail design-time validation. |
| `ValidateWorkflows` | – | Runs the runtime's definition validator against every workflow under `wwwroot` and reports the result. |

### Run history & failure triage

| Command | Options | Description |
| --- | --- | --- |
| `RetrieveFailures Date` | `-wf`, `-d` | Lists every failed action for the workflow on the given UTC day. |
| `RetrieveFailures Run` | `-wf`, `-id` | Lists every failed action for a single run. |
| `SearchInHistory` | `-wf`, `-d`, `-k`, `-b` (optional) | Searches run-history rows for a keyword. With `-b`, also scans blob payloads smaller than 1 MB. |
| `GenerateRunHistoryUrl` | `-wf`, `-d`, `-f` (optional) | Generates clickable Azure portal run-history URLs for failed runs of the day, optionally filtered by an exception message substring. |
| `RetrieveActionPayload` | `-wf`, `-d`, `-a` | Dumps the inline `Inputs` / `Outputs` of every execution of an action on the day. Payloads stored in blobs are skipped. |
| `BatchResubmit` | `-wf`, `-st`, `-et`, `-ignore` (optional, default `true`), `-s` (optional, default `Failed`) | Resubmits runs matching a status (`Failed` / `Succeeded` / `Cancelled`) within a time range. Internally handles ARM throttling (~50 calls / 5 min) by pausing. |
| `CancelRuns` | `-wf` | Cancels every running or waiting instance of the workflow. **Causes data loss for in-flight runs.** |
| `MergeRunHistory` | `-sw`, `-tw` (optional), `-st yyyyMMdd`, `-et yyyyMMdd` | Re-links run history of a deleted workflow into a live one by rewriting `FlowId` / `RowKey` / `PartitionKey` across the `runs`, `flows`, `histories`, `…actions`, `…variables` tables. If `-tw` is omitted, a new placeholder stateful workflow is created. **Irreversible** — prompts for confirmation. |
| `ClearJobQueue` | – | **Deprecated.** Purges the LA job queue to recover from infinite-restart loops. Use `CancelRuns` instead. |

### Storage cleanup

| Command | Options | Description |
| --- | --- | --- |
| `CleanUpContainers` | `-d`, `-wf` (optional) | Deletes blob containers older than the given date (per workflow, or all workflows). Also cleans up containers from deleted workflows. |
| `CleanUpTables` | `-d`, `-wf` (optional) | Deletes per-day run-history tables (`…<yyyyMMdd>actions`, `…<yyyyMMdd>variables`, etc.) older than the given date. |
| `CleanUpRunHistory` | `-d`, `-wf` (optional) | Convenience — runs `CleanUpTables` and `CleanUpContainers` together. |

### Connectivity & configuration validation

| Command | Options | Description |
| --- | --- | --- |
| `ValidateStorageConnectivity` | – | Resolves and probes blob / table / queue / file endpoints derived from `AzureWebJobsStorage`. Validates DNS, TCP connect, SSL handshake, and (with subscription Reader) reports whether the SA is behind a private endpoint or a service-tag rule. |
| `ValidateSPConnectivity` | – | Reads `connections.json` and runs DNS / TCP / SSL probes against every Service Provider endpoint (except SAP, JDBC, FileSystem). |
| `EndpointValidation` | `-url` | DNS, TCP and SSL handshake check for any HTTPS endpoint. |
| `ScanConnections` | – | Lists API connections and Service Providers in `connections.json` that no workflow actually references — candidates for removal. |
| `WhitelistConnectorIP` | `-id` | Looks up the regional managed-connector outbound IPs and adds them to the firewall of the target ARM resource. Supports Storage Account, Key Vault, Event Hub only. |

### Site / file management

| Command | Options | Description |
| --- | --- | --- |
| `Snapshot Create` | – | Copies `wwwroot` to a local `Snapshot_<ts>/` folder and appends current app settings. API connection resources are not captured. |
| `Snapshot Restore` | `-p` | Restores `wwwroot` from a snapshot folder and pushes the snapshot's app settings back to ARM (auto-restart). |
| `SyncToLocal Normal` | `-sn`, `-cs`, `-path` | Pulls the remote file-share `wwwroot` to a local folder interactively. |
| `SyncToLocal Auto` | `-sn`, `-cs`, `-path`, `-ex` (optional) | Same as Normal but non-interactive, suitable for scheduled tasks. `.git` and `.vscode` are excluded by default; add more with `-ex`. |
| `SyncToLocal Batch` | `-cf` | Runs Auto-mode sync for many Logic Apps from a JSON config file. See `Sample/BatchSync_SampleConfig.json`. |
| `FilterHostLogs` | – | Filters error/warning lines from the host log under `LogFiles/Application/Functions/Host` and writes them to a fresh log file next to the tool. |
| `GenerateTablePrefix` | `-wf` (optional) | Prints the hashed storage prefix for the Logic App, and optionally for a workflow. Useful for ad-hoc Storage Explorer queries. |

### `Tools` (utilities & debug helpers)

| Sub-command | Options | Description |
| --- | --- | --- |
| `Tools ImportAppsettings` | `-f` | Imports each key of an app-settings JSON as a user environment variable on the local machine. |
| `Tools CleanEnvironmentVariable` | `-f` | Removes those environment variables. |
| `Tools GetMIToken` | `-a` (optional, default `https://management.azure.com`) | Acquires and prints a Managed Identity token. Must run inside Kudu. |
| `Tools Restart` | – | Calls ARM `POST /sites/<name>/restart`. |
| `Tools GeneratePrefix` | `-la`, `-wf` (optional) | Computes the storage prefix hash for any Logic App / workflow ID, on any machine — no Azure access required. |
| `Tools RunIDToDateTime` | `-id` | Decodes a workflow run ID (e.g. `08584737551867954143243946780CU57`) back into its trigger UTC time and scale unit affinity. |
| `Tools DecodeZSTD` | `-c` | Decompresses a base64 `DefinitionCompressed` / `InputsLinkCompressed` / `OutputsLinkCompressed` value copied from Storage Explorer. |

---

## Project layout

```
LogicAppAdvancedTool/
├─ Program.cs                # Command line entry point, all command bindings
├─ LogicAppAdvancedTool.csproj
├─ DLLs/                     # Vendored binaries (ZSTD, ResourceStack)
├─ Enum/                     # Enum types used across operations
├─ Operations/               # One file per top-level command
├─ Tools/                    # Sub-commands under the `Tools` umbrella
├─ Shared/                   # AppSettings, MSI token, HTTP helpers,
│                            #   table operations, compression, hashing,
│                            #   network/DNS/SSL validators, service tags
├─ Structures/               # POCO models for ARM, MI, run history,
│                            #   service provider, storage connection
├─ Resources/                # Embedded EmptyDefinition.json, RegisteredProvider.json
├─ Sample/                   # BatchSync_SampleConfig.json
└─ Properties/               # AssemblyInfo, app.manifest
```

---

## Safety notes

- **Always run `Snapshot Create` before destructive operations** such as
  `MergeRunHistory`, `IngestWorkflow`, `Revert`, or any of the cleanup commands.
- `MergeRunHistory`, `ClearJobQueue`, and `CancelRuns` are irreversible and can cause
  data loss for running workflow instances. The tool prompts for explicit confirmation
  before executing them.
- `IngestWorkflow` bypasses workflow definition validation; a broken definition can
  prevent the Logic App runtime from starting.
- Destructive cleanup commands (`CleanUp*`) operate on **dates** in UTC and are not
  reversible — double-check the `-d` value before running.

---

## Building from source

```cmd
git clone https://github.com/dengyanbo/LogicAppStandard-AdvancedTool-Skills.git
cd LogicAppStandard-AdvancedTool-Skills\archive\dotnet
dotnet build -c Release
dotnet publish -c Release -o ./publish
```

The result is a portable folder in `./publish` — copy or zip the entire folder into
`C:\home\site\wwwroot` (or anywhere on the LA Standard host) and run
`LogicAppAdvancedTool.exe` from there.

Target framework: **.NET 8.0**. Main NuGet dependencies:

- `Azure.Data.Tables`, `Azure.Storage.Blobs`, `Azure.Storage.Files.Shares`, `Azure.Storage.Queues`
- `Microsoft.Azure.WebJobs`
- `McMaster.Extensions.CommandLineUtils`
- `Newtonsoft.Json`

---

## Changelog

See [`CHANGELOG.md`](./CHANGELOG.md) for the full history (this fork was originally
called `LAVersionReverter` and grew into a full management tool in early 2023).

---

## License

This fork is provided as-is without warranty. For licensing terms please refer to the
upstream repository at
[microsoft/Logic-App-STD-Advanced-Tools](https://github.com/microsoft/Logic-App-STD-Advanced-Tools).
