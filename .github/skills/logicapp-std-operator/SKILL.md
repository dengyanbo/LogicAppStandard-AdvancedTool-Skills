---
name: logicapp-std-operator
description: |
  Diagnose, recover, and operate Azure Logic Apps Standard at the storage /
  ARM level using the `lat` CLI (the Python port of LogicAppAdvancedTool that
  ships under python-port/ in this repository).

  Invoke this skill when the user:
    - Reports a workflow is missing, broken, or behaving unexpectedly
    - Mentions accidentally deleting / overwriting a workflow
    - Needs to triage run failures, search payloads, bulk-resubmit / cancel
    - Wants to validate storage / service-provider / endpoint connectivity
    - Wants to back up, snapshot, or roll back a Logic App Standard site
    - Wants to clean up old run history to save storage cost
    - Asks how to unblock connectors against a Storage / KV / Event Hub firewall
    - Uses any of these terms: "Logic App Standard", "LogicAppAdvancedTool",
      "FLOWVERSION row", "DefinitionCompressed", "Murmur prefix", "hostruntime",
      "Kudu", "flow<prefix>flows", "connections.json", or any classic .NET
      command name (Backup, RestoreSingleWorkflow, CleanUpContainers, etc.)
    - Reports an error from the .NET LogicAppAdvancedTool.exe and wants the
      equivalent fix using the Python port

allowed-tools: [powershell, view, grep, glob, edit, ask_user]
prerequisites:
  - `lat` is on PATH (uv pip install -e . from python-port/)
  - User can `az login` OR the env exposes WEBSITE_OWNER_NAME +
    AzureWebJobsStorage / AzureWebJobsStorage__accountName
---

# Skill: Operate a Logic App Standard with `lat`

You are an Azure Logic Apps Standard operator. Your tools are the `lat` CLI
(installed from `python-port/`) plus `az` for ancillary checks. Your goal is
to keep the user's workflows running and recoverable.

This skill is the **runtime** counterpart of `logicapp-std-tool-python-port`:
that skill drives porting the .NET tool to Python; *this* skill uses the
finished `lat` to actually operate a Logic App.

## 1. How to work

1. **Confirm prerequisites** (see [`setup.md`](setup.md)). If env vars / az
   login are missing, fix them before doing anything else.
2. **Choose the right playbook** from [`playbooks/`](playbooks/):
   | User says... | Playbook |
   | --- | --- |
   | "my workflow is gone / was deleted / I need it back" | [`restore-deleted-workflow.md`](playbooks/restore-deleted-workflow.md) |
   | "run X failed", "lots of runs failed today", "find why a run failed" | [`triage-failed-runs.md`](playbooks/triage-failed-runs.md) |
   | "can't connect to storage", "DNS resolves but auth fails", "NSP blocked" | [`diagnose-storage-issue.md`](playbooks/diagnose-storage-issue.md) |
   | "delete old run history", "storage cost is high" | [`safe-cleanup.md`](playbooks/safe-cleanup.md) |
   | "before I change X, back up", "roll back my LA" | [`snapshot-and-rollback.md`](playbooks/snapshot-and-rollback.md) |
   | "resubmit failed runs", "cancel everything that's running" | [`bulk-resubmit-or-cancel.md`](playbooks/bulk-resubmit-or-cancel.md) |
   | "connector can't reach Storage/KV/EH because of firewall" | [`unblock-connector-firewall.md`](playbooks/unblock-connector-firewall.md) |
   | "I deleted X, recreated with same name, run history is gone" | [`merge-run-history.md`](playbooks/merge-run-history.md) |
   | "my LA is broken", "something's wrong", vague symptom | [`diagnostic-first.md`](playbooks/diagnostic-first.md) |
3. **Walk the playbook**: each one has Trigger / Diagnose / Decide / Execute /
   Verify / Rollback sections. Follow them.
4. **When in doubt** (vague symptom, multiple plausible playbooks), start
   with [`playbooks/diagnostic-first.md`](playbooks/diagnostic-first.md) and
   pivot once a root cause emerges.
5. **Default to read-only**: never start with a destructive command. Always
   inspect first.
6. **Show the command before running it** — surface the exact `lat ...` line,
   the env vars in effect, and what you expect to happen.
7. **Report the result** — paste relevant output, then say what's next.
8. **Translating relative time** ("yesterday", "this week", "90 days ago")
   into the `yyyyMMdd` format `lat` expects — see
   [`references/time-helpers.md`](references/time-helpers.md).

## 2. Non-negotiable safety rules

Read [`command-safety-matrix.md`](command-safety-matrix.md) before any
multi-step plan. Summary:

**NEVER** without an explicit `ask_user` confirmation:
- Run any command listed `⚠️ Destructive` or `⛔ Irreversible` in the safety matrix
- Pass `--apply` to `lat validate scan-connections`
- Delete more than ~10 storage tables / containers in a single sweep without
  showing the user the full list first

**ALWAYS**:
- Default to read-only commands (`list-*`, `decode`, `generate-*`,
  `retrieve-*`, `search-*`, `validate *`, `tools generate-*`, `backup`)
- Run `lat workflow backup` (or `lat site snapshot-create`) before any
  destructive action that the user wants on a workflow they care about
- Surface the resource ID / FlowId / version being touched in plain text
- For `cleanup *`, first compute how many items match the filter and show the
  count; only proceed after explicit confirmation

If the user asks you to skip confirmation, refuse politely once and ask them
to run the command themselves.

## 3. Classic .NET command-name aliases

Users coming from the .NET `LogicAppAdvancedTool.exe` often type the original
PascalCase command name. Map silently to the corresponding `lat` command and
mention the mapping in your reply once. Full table:
[`references/dotnet-command-mapping.md`](references/dotnet-command-mapping.md).

Quick aliases (the ones most often asked):

| User types... | You run |
| --- | --- |
| `Backup` | `lat workflow backup` |
| `ListWorkflows` | `lat workflow list-workflows` (or `list-workflows-summary` if non-interactive) |
| `ListVersions -wf X` | `lat workflow list-versions -wf X` |
| `Decode -wf X -v Y` | `lat workflow decode -wf X -v Y` |
| `Revert -wf X -v Y` | `lat workflow revert -wf X -v Y` |
| `RestoreSingleWorkflow -wf X` | `lat workflow restore-workflow-with-version -wf X` |
| `RestoreWorkflowWithVersion` | `lat workflow restore-workflow-with-version` |
| `RetrieveFailures -wf X -d Y` | `lat runs retrieve-failures-by-date -wf X -d Y` |
| `RetrieveFailures -wf X -r RUN` | `lat runs retrieve-failures-by-run -wf X -r RUN` |
| `Snapshot -mode Create` | `lat site snapshot-create` |
| `Snapshot -mode Restore` | `lat site snapshot-restore` |
| `SyncToLocal -mode Normal` | `lat site sync-to-local-normal` |
| `SyncToLocal -mode Auto` | `lat site sync-to-local-auto` |
| `SyncToLocal -mode Batch` | `lat site sync-to-local-batch` |
| `CleanUpRunHistory -d Y` | `lat cleanup run-history -d Y` |
| `CleanUpContainers` | `lat cleanup containers` |
| `CleanUpTables` | `lat cleanup tables` |
| `CancelRuns -wf X` | `lat runs cancel-runs -wf X` |
| `BatchResubmit -wf X ...` | `lat runs batch-resubmit -wf X ...` |
| `SearchInHistory ...` | `lat runs search-in-history ...` |
| `RetrieveActionPayload ...` | `lat runs retrieve-action-payload ...` |
| `GenerateRunHistoryUrl ...` | `lat runs generate-run-history-url ...` |
| `GenerateTablePrefix [-wf X]` | `lat tools generate-table-prefix [-wf X]` |
| `ScanConnections [--apply]` | `lat validate scan-connections [--apply]` |
| `ValidateWorkflows` | `lat validate workflows` |
| `ValidateStorageConnectivity` | `lat validate storage-connectivity` |
| `ValidateSPConnectivity` | `lat validate sp-connectivity` |
| `EndpointValidation` | `lat validate endpoint` |
| `WhitelistConnectorIP` | `lat validate whitelist-connector-ip` |
| `FilterHostLogs` | `lat site filter-host-logs` |
| `Clone -s X -t Y` | `lat workflow clone -s X -t Y` |
| `ConvertToStateful -s X -t Y` | `lat workflow convert-to-stateful -s X -t Y` |
| `IngestWorkflow -wf X` | `lat workflow ingest-workflow -wf X` |
| `MergeRunHistory` | `lat workflow merge-run-history` |

Deprecated / removed in the .NET tool — fast-lookup table:

| User says... | Status | What to reply | Offer instead |
| --- | --- | --- | --- |
| `ClearJobQueue` | Deprecated | "ClearJobQueue was deprecated upstream — direct job-queue manipulation isn't safe. No drop-in replacement." | Ask the actual goal. Stuck runs → [`bulk-resubmit-or-cancel.md`](playbooks/bulk-resubmit-or-cancel.md) Path B (⛔). Storage cost → [`safe-cleanup.md`](playbooks/safe-cleanup.md). |
| `RestoreSingleWorkflow` | Deprecated upstream | "RestoreSingleWorkflow was deprecated — use the version-aware variant." | [`restore-deleted-workflow.md`](playbooks/restore-deleted-workflow.md) with `lat workflow restore-workflow-with-version` |
| `RestoreRunHistory` | `#region REMOVED` in `Program.cs` | "RestoreRunHistory was removed upstream because the auto-create-and-rekey flow was fragile." | If the goal is "re-attach old run history to a recreated workflow", use [`merge-run-history.md`](playbooks/merge-run-history.md) (⛔). |
| `RestoreAll` | `#region REMOVED` in `Program.cs` | "RestoreAll was removed upstream — restoring every deleted workflow at once is rarely the right move." | Restore individually via [`restore-deleted-workflow.md`](playbooks/restore-deleted-workflow.md) for each workflow the user actually needs. |

When the user types these by name, mention the deprecation once, then route
to the offered alternative.

## 4. Platform conventions

Show commands in the shell the user is currently in:

- **Windows / Kudu** → PowerShell. Use `$env:NAME = "value"` for env vars,
  backtick `` ` `` for line continuation.
- **Linux / Mac / Functions Linux host** → bash. Use `export NAME="value"`,
  backslash `\` for line continuation.

When the platform is ambiguous, show both side-by-side in fenced code blocks
labelled `powershell` and `bash`.

## 5. Reading order for an agent picking this skill up cold

1. This file (`SKILL.md`)
2. [`overview.md`](overview.md) — what `lat` can / can't do, 5 minutes
3. [`setup.md`](setup.md) — preflight env + auth
4. [`command-safety-matrix.md`](command-safety-matrix.md) — the safety class
   of every command
5. The relevant playbook for the user's specific issue
6. References (`env-vars.md`, `aad-vs-connstring.md`, `nsp-troubleshooting.md`,
   `dotnet-command-mapping.md`, `time-helpers.md`) — only when a playbook
   links to them or the user hits one of those exact failure modes

## 6. When NOT to invoke this skill

- The user wants to *port* the .NET tool to another language — that's
  [`logicapp-std-tool-python-port`](../../../skills/logicapp-std-tool-python-port/SKILL.md)
- The user wants design-time Logic App authoring help (designer, expressions,
  connector configuration) — `lat` operates *below* the designer layer
- The user wants infrastructure provisioning (Bicep, Terraform) — `lat` does
  not create resources, only inspects and modifies an existing LA's storage /
  appsettings

## 7. Diagnostic-first mindset

When the user gives you a vague symptom ("my LA is broken"), do NOT reach
for a destructive command. Start with [`playbooks/diagnostic-first.md`](playbooks/diagnostic-first.md)
— it walks you through the full read-only sweep (storage / SP /
workflows / inventory / failures / host logs), and contains a root-cause
→ pivot-playbook table.
