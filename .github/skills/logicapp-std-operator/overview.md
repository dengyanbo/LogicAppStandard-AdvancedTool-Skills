# `lat` overview — what this tool gives you over the Azure portal

Five-minute read for an agent picking up the skill.

## The premise

Azure Logic Apps Standard runs on top of an **Azure Storage account** that
holds workflow definitions, run history, action inputs/outputs, variables,
job queues, and the wwwroot file share. The portal exposes maybe 30% of what
that storage account actually contains, and *none* of the recovery /
forensics paths you need when something goes wrong.

`lat` (Python port of `LogicAppAdvancedTool`) re-implements the runtime's
exact storage-naming algorithms (Murmur32/64 + a custom ZSTD framing) so it
can read and write the same tables, blobs, and queues directly. This unlocks
operations that have no portal equivalent.

## Six sub-apps, 41 commands

| Sub-app | Purpose | Read-only commands | Destructive |
| --- | --- | --- | --- |
| `workflow` | Workflow definition + version mgmt | list-workflows[-summary], list-versions, backup, decode | revert, clone, convert-to-stateful, restore-workflow-with-version, ingest-workflow ⛔, merge-run-history ⛔ |
| `runs` | Run-history triage | retrieve-failures-by-{date,run}, retrieve-action-payload, search-in-history, generate-run-history-url | batch-resubmit, cancel-runs ⛔ |
| `cleanup` | Old-data eviction | (none) | containers ⛔, tables ⛔, run-history ⛔ |
| `validate` | Connectivity + config sanity | endpoint, storage-connectivity, sp-connectivity, workflows, scan-connections | scan-connections --apply ⚠️, whitelist-connector-ip ⚠️ |
| `site` | Site / file ops | filter-host-logs | snapshot-create, snapshot-restore ⚠️, sync-to-local-{normal,auto,batch} ⚠️ |
| `tools` | Utility / debug | generate-prefix, generate-table-prefix, runid-to-datetime, decode-zstd, get-mi-token | restart ⚠️, import-appsettings, clean-environment-variable |

Legend: ⛔ irreversible · ⚠️ destructive but recoverable · (everything else
is safe / read-only).

## What you can do that the portal can't

| Need | `lat` command | Why portal can't |
| --- | --- | --- |
| Recover a deleted workflow | `workflow restore-workflow-with-version` | Portal has no "undelete"; runtime keeps history in storage for ~90 days |
| Roll a workflow back to last week | `workflow revert -v <FlowSequenceId>` | Portal only shows current version |
| Bulk resubmit 2000 failed runs from Tuesday | `runs batch-resubmit ... --status Failed --from ... --to ...` | Portal makes you click each run |
| Search action payloads for a specific token | `runs search-in-history -k <keyword>` | Portal has no payload search |
| Diagnose "my LA can't reach its own storage" | `validate storage-connectivity` | Portal hides backing storage |
| Compute the storage-table name for a workflow | `tools generate-table-prefix -wf <name>` | Portal never reveals the prefix |
| Free up 50 GB of run-history blobs older than Q1 | `cleanup run-history -d 20250101` | Portal can't bulk-delete run-history containers |
| Validate every workflow.json without a "Run" click | `validate workflows` | Portal designer validation is a subset |
| Add the Azure Connector IP range to a downstream KV firewall | `validate whitelist-connector-ip` | Portal doesn't surface "the connector tag for my region" |

## What you can do that KQL / Log Analytics can't

- Read **inputs and outputs** directly (not just metadata)
- Decompress `DefinitionCompressed` to recover historical workflow JSON
- Re-key run history when a workflow was deleted + recreated with the same
  name (`workflow merge-run-history`)

## What `lat` does *not* do

- Create / destroy Azure resources (use Bicep / Terraform / `az`)
- Modify ARM-level config like ASP plan, networking, MI assignments
  (use `az`)
- Author workflows (use the designer / VS Code extension)
- Run a workflow on demand (use the portal "Run" button or the LA runtime
  trigger)
- Talk to non-Standard plans (Consumption Logic Apps have a different
  storage model)

## Authentication models

| LA's storage config | What `lat` does |
| --- | --- |
| Legacy: `AzureWebJobsStorage` = `...AccountKey=...` | Uses the connection string directly |
| Modern: `AzureWebJobsStorage__accountName` + managed identity | Uses `DefaultAzureCredential` (picks up `az login` locally, MSI inside Kudu) |
| Hostruntime / ARM calls | Always uses a bearer token from `DefaultAzureCredential` |

See [`references/aad-vs-connstring.md`](references/aad-vs-connstring.md) for
the decision tree.

## When to suspect `lat` is not the right answer

- The user wants to change *connector configuration* — that's
  `connections.json` editing in VS Code or the designer
- The user wants ASP scaling, deployment slots, traffic shaping — that's
  `az webapp` / Bicep
- The user wants to grant RBAC — that's `az role assignment`
- The user wants application-level observability (custom telemetry,
  traces) — that's Application Insights / KQL
