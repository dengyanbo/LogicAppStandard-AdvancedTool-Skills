# Command safety matrix

The safety class determines whether an agent may run a command without
explicit user confirmation.

| Class | Meaning | Confirmation required? |
| --- | --- | --- |
| ✅ **Safe** | Read-only, idempotent, no side effects beyond local stdout / files | No |
| 📁 **Local-write** | Writes to a local folder (e.g. backup, snapshot) but nothing in Azure changes | No, but warn if overwriting |
| ⚠️ **Destructive (recoverable)** | Modifies Azure state but is recoverable from a recent snapshot/backup | **Yes** |
| ⛔ **Irreversible** | Modifies or deletes Azure state with no automated undo | **Yes, with strong warning + recent backup confirmed** |

## Full matrix

| Command | Class | What it writes to | How to undo | Confirm before running? |
| --- | --- | --- | --- | --- |
| `workflow list-versions` | ✅ Safe | stdout | — | No |
| `workflow list-workflows` | ✅ Safe | stdout | — | No |
| `workflow list-workflows-summary` | ✅ Safe | stdout | — | No |
| `workflow decode` | ✅ Safe | stdout | — | No |
| `workflow backup` | 📁 Local-write | `./Backup/` (or `--output`) | Delete the folder | No |
| `workflow revert` | ⚠️ Destructive | `<wwwroot>/<wf>/workflow.json` | `backup` first; copy back | **Yes** |
| `workflow clone` | ⚠️ Destructive | `<wwwroot>/<new-wf>/` | `rm -rf <new-wf>` | Yes (cheap fix though) |
| `workflow convert-to-stateful` | ⚠️ Destructive | `<wwwroot>/<new-wf>/` | `rm -rf <new-wf>` | Yes (cheap fix though) |
| `workflow restore-workflow-with-version` | ⚠️ Destructive | `<wwwroot>/<wf>/workflow.json` + `./RuntimeContext_*.json` | `backup` first; copy back | **Yes** |
| `workflow ingest-workflow` | ⛔ Irreversible | Main definition table + per-workflow table | None (overwrites multiple rows in place) | **Yes + require recent backup** |
| `workflow merge-run-history` | ⛔ Irreversible | Main table + per-source-workflow runs / flows / histories / actions / variables tables | None (re-keys storage records) | **Yes + require recent backup + show source / target FlowIds** |
| `runs retrieve-failures-by-date` | 📁 Local-write | `./<LA>_<wf>_<date>_FailureLogs.json` | Delete the file | No |
| `runs retrieve-failures-by-run` | 📁 Local-write | `./<LA>_<wf>_<runId>_FailureLogs.json` | Delete the file | No |
| `runs retrieve-action-payload` | 📁 Local-write | `./<wf>_<date>_<action>.json` | Delete the file | No |
| `runs search-in-history` | 📁 Local-write | `./<LA>_<wf>_<date>_SearchResults.json` | Delete the file | No |
| `runs generate-run-history-url` | 📁 Local-write | `./<LA>_<wf>_<date>_RunHistoryUrl.json` | Delete the file | No |
| `runs batch-resubmit` | ⚠️ Destructive | LA runtime (creates new run instances) | Cancel re-runs if needed; original failed runs remain | **Yes — show count of runs to resubmit** |
| `runs cancel-runs` | ⛔ Irreversible | Per-flow `*runs` table (Status=Cancelled) | None (Running/Waiting runs lose state) | **Yes + strong warning about data loss** |
| `cleanup containers` | ⛔ Irreversible | Deletes blob containers | None | **Yes + show full list / count before deletion** |
| `cleanup tables` | ⛔ Irreversible | Deletes storage tables | None | **Yes + show full list / count before deletion** |
| `cleanup run-history` | ⛔ Irreversible | Both of the above | None | **Yes + show total count + ask for re-confirmation** |
| `validate endpoint` | ✅ Safe | stdout | — | No |
| `validate storage-connectivity` | ✅ Safe | stdout (with `--skip-pe-check` if no Reader on sub) | — | No |
| `validate sp-connectivity` | ✅ Safe | stdout | — | No |
| `validate workflows` | ✅ Safe | stdout (calls hostruntime, side-effect-free) | — | No |
| `validate scan-connections` | ✅ Safe (without `--apply`) | stdout only | — | No |
| `validate scan-connections --apply` | ⚠️ Destructive | Removes unused entries from `connections.json` in wwwroot | Restore from backup | **Yes + show entries to be removed** |
| `validate whitelist-connector-ip` | ⚠️ Destructive | Target Storage / KV / EH firewall (`ipRules`) | Remove the added entries from the target | **Yes + use `--dry-run` first** |
| `site filter-host-logs` | 📁 Local-write | stdout / file | — | No |
| `site snapshot-create` | 📁 Local-write | Snapshot folder | Delete folder | No |
| `site snapshot-restore` | ⚠️ Destructive | `wwwroot` (overwrites every file) + appsettings (replaces them) | `snapshot-create` first; restore from that | **Yes** |
| `site sync-to-local-normal` | 📁 Local-write (interactive) | Local folder | Delete folder | No (prompt is inline) |
| `site sync-to-local-auto` | 📁 Local-write | Local folder | Delete folder | No, but warn if `local` exists |
| `site sync-to-local-batch` | 📁 Local-write | Multiple local folders | Delete folders | No |
| `tools generate-prefix` | ✅ Safe | stdout | — | No |
| `tools generate-table-prefix` | ✅ Safe | stdout | — | No |
| `tools runid-to-datetime` | ✅ Safe | stdout | — | No |
| `tools decode-zstd` | ✅ Safe | stdout | — | No |
| `tools get-mi-token` | ✅ Safe | stdout | — | No |
| `tools restart` | ⚠️ Destructive | LA site state (restart) | None (just causes ~30s downtime) | **Yes** |
| `tools import-appsettings` | ⚠️ Destructive | Machine env vars (Windows admin) | Manual env-var cleanup | **Yes** |
| `tools clean-environment-variable` | ⚠️ Destructive | Machine env vars (Windows admin) | Re-import | **Yes** |

## Pre-destructive checklist

For every ⛔ Irreversible command, before running:

1. **Verify** a recent backup exists (run `lat workflow backup` if unsure)
2. **Show** the user the exact resource ID(s) / FlowId(s) / count being
   touched
3. **Quote** the relevant warning text from the command's `--help`
4. **Ask** explicit confirmation via `ask_user` — never assume

For every ⚠️ Destructive command, before running:

1. Show the exact `lat ...` invocation
2. State what will change (which file / which resource / which appsetting)
3. Ask confirmation via `ask_user`

## When the user pushes back on confirmations

If the user says "skip the confirmation" or "just do it":
- Politely refuse once: "I have to confirm destructive operations; the rule
  is in the skill manifest. If you need to skip, please run the command
  yourself."
- Offer to show them the exact command line so they can paste it.
- Do **not** comply by running it anyway.
