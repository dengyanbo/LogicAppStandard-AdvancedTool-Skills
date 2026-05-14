# Overview — `LogicAppAdvancedTool` (.NET 8)

This document is a condensed model of the source application the agent is
porting. It is intentionally shorter than the source's `README.md`; read it
first to build the mental model, then dive into the source for any specific
command.

## 1. What the tool is

`LogicAppAdvancedTool.exe` is a Windows-only .NET 8 console application that
manages an Azure Logic Apps Standard (LA Std) site at a level below what the
Azure portal exposes. It is normally deployed into the site's `wwwroot` (or
run from a workstation that has the site's app settings imported as env
vars) and operated by support engineers.

The tool's job boils down to:

1. Compute the same hashed storage-resource names the LA runtime uses.
2. Read / write those storage tables and blobs directly.
3. Where storage alone is not enough (app settings, restart, resubmit),
   call ARM with a Managed Identity bearer token.

## 2. Source repository layout (cited as `path:line` throughout the skill)

```
Logic-App-STD-Advanced-Tools/
├─ Program.cs                  # Single ~1000-line file binding CLI to commands
├─ LogicAppAdvancedTool.csproj # net8.0; deps: Azure.Data.Tables 12.2,
│                              #   Azure.Storage.Blobs 12.16, Files.Shares 12.13,
│                              #   Queues 12.12, McMaster.CommandLineUtils 4.0.2,
│                              #   Newtonsoft.Json 13, ZstdSharp (vendored)
├─ DLLs/                       # Vendored: Microsoft.WindowsAzure.ResourceStack,
│                              #   ZstdSharp, System.Configuration.ConfigurationManager
├─ Operations/                 # One file per top-level command (~35 files)
├─ Tools/                      # 7 Tools sub-commands
├─ Shared/                     # AppSettings, MSITokenService, HttpOperations,
│                              #   TableOperations, PageableTableQuery,
│                              #   StoragePrefixGenerator, CompressUtility,
│                              #   ContentDecoder, NetworkValidator,
│                              #   ServiceTagRetriever, WorkflowSelector,
│                              #   WorkflowInfoQuery, ConsoleTable,
│                              #   CustomExceptions, Common.cs, DecodeMetadata.cs
├─ Structures/                 # POCOs: AzureResource, MIToken,
│                              #   RunHistory, ServiceProvider, StorageConnection,
│                              #   Workflow
├─ Resources/                  # EmptyDefinition.json, RegisteredProvider.json
├─ Sample/                     # BatchSync_SampleConfig.json
└─ Enum/                       # Single Enum.cs
```

## 3. Runtime context (environment variables it reads)

The tool resolves all context from environment variables. The Python port
must mirror this in `src/lat/settings.py` (see `Shared/AppSettings.cs:9-89`):

| Env var | C# property | Used for |
| --- | --- | --- |
| `AzureWebJobsStorage` | `ConnectionString` | All storage table/blob/queue access |
| `WEBSITE_CONTENTAZUREFILECONNECTIONSTRING` | `FileShareConnectionString` | `wwwroot` file share (SyncToLocal) |
| `WEBSITE_OWNER_NAME` | `SubscriptionID` (split by `+`) | ARM URL building |
| `WEBSITE_RESOURCE_GROUP` | `ResourceGroup` | ARM URL building |
| `REGION_NAME` | `Region` | Connector IP lookup, service tags |
| `WEBSITE_SITE_NAME` | `LogicAppName` | Storage prefix, ARM URL building |
| `MSI_ENDPOINT` | `MSIEndpoint` | MI token retrieval |
| `MSI_SECRET` | `MSISecret` | MI token retrieval header |
| (none; hardcoded) | `RootFolder = C:\home\site\wwwroot` | File ops |
| (derived) | `ManagementBaseUrl = https://management.azure.com/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Web/sites/{laName}` |

> The Python port uses POSIX path separators and parameterizes `RootFolder`
> via a flag, because the port may run on Linux for parity tests.

## 4. The hashed storage naming scheme (the heart of the tool)

Every per-Logic-App resource in storage is named:

```
flow<MurmurHash64-trimmed-to-15-of-LogicAppName>
    <MurmurHash64-trimmed-to-15-of-flowId-lowercased>
    <suffix>
```

* `<suffix>` is one of: `flows`, `runs`, `histories`, `<yyyyMMdd>actions`,
  `<yyyyMMdd>variables`, plus per-workflow blob containers and queues.
* The trim rule (`TrimStorageKeyPrefix`) takes the hex hash and shortens it
  to `limit - 17` chars; in practice both invocations use `limit = 32` →
  trimmed to 15 chars and lowercased.
* The main definition table is *Logic-App-scoped*, not flow-scoped, and is
  called `flow<la-hash>flows` (NB: this clashes with the per-flow `flows`
  table — disambiguated by the inclusion of the flow hash).

Reproduce this exactly. See `references/01-storage-prefix-hashing.md` for
the byte-for-byte algorithm.

## 5. Compressed payload framing

Workflow definitions, action input/output links, and similar large fields
are stored compressed in the storage table. Each compressed value is:

```
<varint length-and-algorithm>  <codec-specific frame>
```

* The very first byte's **low 3 bits** select the codec:
    * `7` → ZSTD (current default since `ModernCompressionUtility`, Nov 2024)
    * `6` → LZ4 (legacy; not supported by the tool, throws)
    * any other value (e.g. `0`) → Deflate (`Microsoft.WindowsAzure.ResourceStack.DeflateCompressionUtility`)
* The varint is little-endian, 7-bit chunks, with the MSB as a continuation
  bit. The uncompressed length is the varint value `>> 3` bits.

The port must implement detection on the first byte and dispatch to either
`zstandard` or stdlib `zlib`. See `references/03-compression-codec.md` for
the exact decoder.

## 6. Auth flows

* **Storage**: connection string from `AzureWebJobsStorage` env var,
  consumed by Azure SDK `TableServiceClient` / `BlobServiceClient` etc.
* **ARM**: site Managed Identity. The tool POSTs to `$MSI_ENDPOINT` with
  header `Secret: $MSI_SECRET` and query `api-version=2017-09-01` +
  `resource=https://management.azure.com`. Token JSON is cached locally
  under `Temp/MIToken.json` for offline rerun. See
  `Shared/MSITokenService.cs` and `references/06-managed-identity.md`.

## 7. Command categories

Group | Count | Examples
--- | --- | ---
Workflow definition / version mgmt | 11 | `Backup`, `Revert`, `Decode`, `Clone`, `ConvertToStateful`, `ListVersions`, `ListWorkflows`, `RestoreWorkflowWithVersion`, `IngestWorkflow`, `ValidateWorkflows`, `RestoreSingleWorkflow` (deprecated)
Run-history / triage | 9 | `RetrieveFailures` (Date/Run), `SearchInHistory`, `GenerateRunHistoryUrl`, `RetrieveActionPayload`, `BatchResubmit`, `CancelRuns`, `MergeRunHistory`, `ClearJobQueue` (deprecated)
Storage cleanup | 3 | `CleanUpContainers`, `CleanUpTables`, `CleanUpRunHistory`
Connectivity validation | 5 | `ValidateStorageConnectivity`, `ValidateSPConnectivity`, `EndpointValidation`, `ScanConnections`, `WhitelistConnectorIP`
Site / file mgmt | 7 | `Snapshot Create/Restore`, `SyncToLocal Normal/Auto/Batch`, `FilterHostLogs`, `GenerateTablePrefix`
`Tools` sub-commands | 7 | `ImportAppsettings`, `CleanEnvironmentVariable`, `GetMIToken`, `Restart`, `GeneratePrefix`, `RunIDToDateTime`, `DecodeZSTD`

Total: **42 invocations** (counting sub-commands). The Python port must
expose each as a Typer command or sub-command with the same flags.

## 8. Notable behaviors to preserve

* **Confirmation prompts** on destructive ops (`Revert`, `IngestWorkflow`,
  `MergeRunHistory`, `Cleanup*`, `CancelRuns`, `ClearJobQueue`,
  `Snapshot Restore`). Implement with `typer.confirm` + `--yes` flag.
* **Experimental banner** (`CommonOperations.AlertExperimentalFeature`)
  printed before `IngestWorkflow`, `MergeRunHistory`. Port to a helper in
  `src/lat/cli.py`.
* **Pageable queries** to bound memory — never load entire tables into a
  list. `Shared/PageableTableQuery.cs` streams pages; in Python use
  `TableClient.query_entities(...)` iterator directly.
* **Transaction batching** of 100 entities per partition key for upserts;
  exceeding this returns HTTP 400 from Storage. See
  `Operations/MergeRunHistory.cs:144-149`.
* **ARM throttle handling** in `BatchResubmit`: sleep 2 minutes and retry
  when responses indicate quota exhaustion. See
  `Operations/BatchResubmit.cs`.
* **Console output**: the .NET tool uses `ConsoleTable` (Shared/ConsoleTable.cs)
  for pretty-printed result tables. Port to `rich.table.Table` for parity.

## 9. Out-of-scope

* The ClickOnce-flavored `.csproj` metadata (signing thumbprints, bootstrappers).
* The `_TemporaryKey.pfx` manifest cert — not needed in Python.
* The vendored ResourceStack DLL itself — replaced by `zstandard` + stdlib
  `zlib`.
* The `#if DEBUG` `Tools.FeatureTesting()` scratch harness in `Program.cs:22`.

---

Next: read [`port-process.md`](./port-process.md).
