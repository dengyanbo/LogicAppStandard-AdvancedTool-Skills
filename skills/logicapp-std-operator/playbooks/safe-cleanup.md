# Playbook: Safe cleanup of old run-history

## Trigger conditions

- "Storage cost is high"
- "How do I delete old run history?"
- "Clean up logs older than <date>"
- Classic .NET names: `CleanUpContainers`, `CleanUpTables`, `CleanUpRunHistory`

## ⛔ Irreversible — read this first

These commands DELETE blob containers and storage tables. There is no
recycle bin, no automated undo, no "deleted_at" marker. Anything you delete
is gone.

The `lat` command flow has built-in safeguards (preview count + confirmation
prompt). Your job as an agent is to:

1. Walk the user through the preview *before* `--yes`
2. Confirm the date threshold makes sense
3. Confirm the user has a recent `workflow backup` (definitions live in a
   different table — `cleanup` does NOT touch those — but run history is
   gone forever)

## Diagnose: what's actually old?

The LA's run-history names embed `yyyyMMdd` at offset 34 of the resource
name. Anything strictly **before** `--date` (yyyyMMdd) is deletion-eligible.

### List candidates without deleting

There's no built-in `--dry-run` on `cleanup *`, but you can preview via the
underlying SDK:

```powershell
# PowerShell — preview tables that would be deleted
$prefix = "flow$(lat tools generate-table-prefix | Select-String 'Logic App Prefix' | ForEach-Object { ($_ -split ': ')[1].Trim() })"
$target = 20240101
az storage table list `
    --account-name <storage-acct> --auth-mode login `
    --query "[?starts_with(name, '$prefix') && (ends_with(name, 'actions') || ends_with(name, 'variables')) && to_number(substr(name, 34, 8)) < ``$target``].name" `
    -o tsv
```

```bash
# bash
prefix="flow$(lat tools generate-table-prefix | awk -F': ' '/Logic App Prefix/ {print $2}')"
target=20240101
az storage table list \
    --account-name <storage-acct> --auth-mode login \
    --query "[?starts_with(name, '$prefix') && (ends_with(name, 'actions') || ends_with(name, 'variables')) && to_number(substr(name, 34, 8)) < \`$target\`].name" \
    -o tsv
```

Adjust the path for blob containers:

```powershell
az storage container list --account-name <storage-acct> --auth-mode login `
    --query "[?starts_with(name, '$prefix') && to_number(substr(name, 34, 8)) < ``$target``].name" -o tsv
```

## Decide

Ask the user via `ask_user`:

1. **Threshold date** — UTC `yyyyMMdd`. The runtime's own default eviction
   is ~90 days; deleting younger than that is unusual.
2. **Scope** — entire Logic App, or one specific workflow?
3. **Tables only, containers only, or both?**

Use the preview above to compute counts. Show the user:

```
You are about to delete from storage account <acct>:
  - <N1> blob containers (sample: <c1>, <c2>, <c3>, ...)
  - <N2> storage tables   (sample: <t1>, <t2>, <t3>, ...)
older than <date>. This is IRREVERSIBLE.
```

`ask_user` to confirm with the exact count. If the user says "go" without
having seen the preview, refuse and re-preview.

## Execute

| User intent | Command |
| --- | --- |
| Both tables + containers, whole LA | `lat cleanup run-history -d <YYYYMMDD>` |
| Only blob containers | `lat cleanup containers -d <YYYYMMDD>` |
| Only storage tables | `lat cleanup tables -d <YYYYMMDD>` |
| Scope to one workflow | Add `-wf <WorkflowName>` to any of the above |

Each command shows its match count and prompts before deleting. Pass `--yes`
only after the user confirmed via `ask_user`.

```powershell
lat cleanup run-history -d 20240101 --yes
```

## Verify

1. Re-run the preview query — the count should now be 0 for that date
   range:

   ```powershell
   az storage container list --account-name <acct> --auth-mode login `
       --query "length([?starts_with(name, '$prefix') && to_number(substr(name, 34, 8)) < ``$target``])"
   ```

2. Quick sanity that the Logic App still works:

   ```powershell
   lat workflow list-workflows-summary | Select-Object -First 5
   lat validate workflows
   ```

   `cleanup` only touches per-day run-history tables / containers (suffix
   `actions` / `variables` / per-flow blob containers). The main definition
   table (`flow<prefix>flows`) is untouched, so workflow definitions are
   safe.

## Rollback

**There is none.** Deleted run history is gone.

Recovery from a serious miss:
- Re-run the workflows from the source events if you have them.
- If the storage account has **point-in-time restore** enabled, the storage
  admin can roll back via PIR.
- Otherwise, accept the loss and update process so the cleanup threshold is
  more conservative next time.

## Recommended cadence

- Monthly: delete data older than 90 days (matches LA's own eviction
  default; very low risk).
- Quarterly: delete data older than 30 days, only when storage cost is
  actually a problem.
- Ad-hoc: never delete younger than 7 days without a strong reason — recent
  runs are often the ones being investigated.

## Related .NET names

- `CleanUpContainers` → `lat cleanup containers`
- `CleanUpTables` → `lat cleanup tables`
- `CleanUpRunHistory` → `lat cleanup run-history`
