# Playbook: Merge run history (re-key a deleted workflow's history)

## Trigger conditions

- "I deleted my workflow X, recreated it with the same name, now my run
  history is gone"
- "Merge the old run history into the new workflow"
- "My new workflow has a different FlowId from the old one, can I attach
  the old history to it?"
- Classic .NET name: `MergeRunHistory`

## ⛔ Irreversible — read this first

`workflow merge-run-history` is the **most destructive** command in `lat`.
It re-keys storage records across SIX tables:

- The main definition table (FLOWIDENTIFIER / FLOWLOOKUP / FLOWVERSION rows)
- The per-flow `runs` table
- The per-flow `flows` table
- The per-flow `histories` table
- Every per-day `*actions` table in the chosen date range
- Every per-day `*variables` table in the chosen date range

Each row's `FlowId` is overwritten and its `RowKey` is rewritten with the
source FlowId (uppercase) replaced by the target FlowId (uppercase). The
partition key is recomputed via Murmur32 on the new RowKey.

**There is no undo.** Source rows in the main definition table remain (as
orphans); per-flow tables get NEW rows written into the target's tables.
Storage cost effectively doubles for the merged date range until cleanup.

## Diagnose

### Step 1: Identify source and target by FlowId, not just name

The .NET tool (and `lat`) take workflow *names* as input, but the actual
operation acts on *FlowIds*. If the source name has been used by multiple
FlowIds (because of repeated delete+recreate cycles), you MUST pick the
right one.

```powershell
# PowerShell
lat workflow list-workflows-summary
lat workflow list-versions -wf <SourceName>
lat workflow list-versions -wf <TargetName>
```

```bash
# bash
lat workflow list-workflows-summary
lat workflow list-versions -wf <SourceName>
lat workflow list-versions -wf <TargetName>
```

Note each unique `Workflow ID` (FlowId) in the output. There may be more
than one FlowId per name. Decide with the user which FlowId is "the old
one" (source) and which is "the new one" (target).

### Step 2: Verify the date range covers actual run history

```powershell
# Source has run history in the proposed range?
lat runs retrieve-failures-by-date -wf <SourceName> -d <start-date>
lat runs retrieve-failures-by-date -wf <SourceName> -d <end-date>
# These read the runs/actions tables for the source workflow indirectly via
# the FlowLOOKUP row. If the source row is orphaned (workflow was deleted
# from the portal), the FlowLOOKUP row is gone, and lat will say
# "<SourceName> cannot be found in storage table". In that case, you'll
# need to bypass the lookup — see Diagnose Step 3.
```

### Step 3: Source workflow no longer has a FLOWLOOKUP row

If the source has been overwritten by a new workflow with the same name,
`lat`'s helpers that resolve "name → FlowId" point at the NEW one. To find
the OLD FlowId you have to look at the FLOWVERSION rows directly:

```powershell
# Generate the table prefix for the LA
$prefix = (lat tools generate-table-prefix | Select-String 'Logic App Prefix' |
           ForEach-Object { ($_ -split ': ')[1].Trim() })
# Look for older FlowIds under the source name in the main definition table
az storage entity query --account-name <acct> --auth-mode login `
  --table-name "flow${prefix}flows" `
  --filter "FlowName eq '<SourceName>' and RowKey ge 'MYEDGEENVIRONMENT_FLOWVERSION'" `
  --select FlowId,FlowSequenceId,ChangedTime --query "items[].FlowId" -o tsv |
  Sort-Object -Unique
```

```bash
prefix=$(lat tools generate-table-prefix | awk -F': ' '/Logic App Prefix/ {print $2}')
az storage entity query --account-name <acct> --auth-mode login \
  --table-name "flow${prefix}flows" \
  --filter "FlowName eq '<SourceName>' and RowKey ge 'MYEDGEENVIRONMENT_FLOWVERSION'" \
  --select FlowId,FlowSequenceId,ChangedTime --query "items[].FlowId" -o tsv |
  sort -u
```

Take this list to the user. The "old FlowId" is the one not currently in
use (i.e., not equal to the FLOWLOOKUP row's FlowId).

### Step 4: Backup is mandatory

```powershell
lat workflow backup --output .\pre-merge-backup
```

This dumps every workflow definition (including the source's, if its rows
are still in the storage table) plus appsettings. The backup does NOT
include run history — there is no way to back up run history short of
cloning the whole storage account. The user must accept that risk.

## Decide

Before any write, `ask_user` to confirm ALL of:

1. **Source FlowId** (not just name): `<F_src>` from Step 1 or Step 3
2. **Target FlowId**: `<F_tgt>` — must already exist (the .NET tool's
   auto-create-target branch is NOT ported; see
   [`../references/dotnet-command-mapping.md`](../references/dotnet-command-mapping.md))
3. **Date range** for actions/variables tables: `--start YYYYMMDD --end YYYYMMDD`
   - Tight ranges are safer (re-key fewer rows)
   - Future dates are typically a typo — flag if `--end` is after today
4. **Backup verified**: confirm the user has run `lat workflow backup` (or
   has a recent snapshot)
5. **Storage cost awareness**: the merge writes new rows; cleanup of the
   old source rows is the user's responsibility afterwards

If the user only supplies the names, run Step 1 and present:

```
Source workflow `OldFlow` has FlowIds:
  [a] 11111111-... (last seen 2024-03-01)
  [b] 22222222-... (last seen 2024-08-15)
Target workflow `NewFlow` has FlowId:
  33333333-...

Which source FlowId should I merge into NewFlow?
```

## Execute

```powershell
# PowerShell — do NOT add --yes until ask_user has confirmed all 5 items above
lat workflow merge-run-history `
    -s <SourceName> `
    -t <TargetName> `
    --start <YYYYMMDD> `
    --end <YYYYMMDD> `
    --yes
```

```bash
# bash
lat workflow merge-run-history \
    -s <SourceName> \
    -t <TargetName> \
    --start <YYYYMMDD> \
    --end <YYYYMMDD> \
    --yes
```

The command runs in this order:

1. Re-keys main-table rows where `FlowId == source` to belong to the target
   (FlowLookup row gets overwritten in place; FLOWVERSION rows get NEW
   rows added because the RowKey changes)
2. Merges `runs`, `flows`, `histories` tables
3. Merges every `*actions` / `*variables` table whose date suffix is within
   `[--start, --end]`

For large date ranges this is **slow** — many tables, many rows per table,
batches of 100 transactions per partition. A 3-month range with a
moderately busy workflow can take 10-30 minutes.

## Verify

1. After the command finishes:

   ```powershell
   lat workflow list-versions -wf <TargetName>
   # Should now show the historical versions from the source mixed in.

   lat runs retrieve-failures-by-date -wf <TargetName> -d <date-in-range>
   # Should show runs from the source's date range
   ```

2. Open the portal → Logic Apps → workflow page for `<TargetName>` → Run
   History. The historical runs from the source should now appear under
   the target.

3. Source rows in the main table are NOT cleaned up automatically — they
   remain as orphans. If the user wants the source name to disappear from
   `list-workflows-summary`, they need to delete the orphan rows manually
   (or wait for the runtime's ~90-day eviction).

## Rollback

**None.** The pre-merge backup captures definitions only, not run history.

Partial recovery options:

- If the merge wrote to the wrong target FlowId: the orphan rows still
  exist on the source side; you could attempt `merge-run-history` AGAIN in
  the opposite direction (target → another target). This is extremely
  fragile; have the user accept the risk.
- If the merge clearly went wrong: stop, escalate, take the data loss.

## When to NOT use this playbook

- The user just wants to **see** the old run history without merging it.
  → `lat runs retrieve-failures-by-date -wf <OldName> -d <date>` works
  if the old FLOWLOOKUP row still exists. If not, point them at the raw
  `az storage entity query` snippet from Step 3.
- The user only deleted the workflow recently and wants to **restore** it
  (not merge into a new one). → [`restore-deleted-workflow.md`](restore-deleted-workflow.md)
- The user wants to "merge two different workflows" (not delete+recreate
  with the same name). `merge-run-history` assumes the source's RowKey
  embeds the source FlowId — if the workflows are unrelated, the RowKey
  rewrite produces meaningless keys. Do NOT use this playbook for that
  case; tell the user it's not a supported scenario.
- The user wants to merge a date range > 6 months. Strongly suggest
  breaking it into multiple smaller runs to limit blast radius.

## Related .NET names

- `MergeRunHistory` → `lat workflow merge-run-history` (auto-create-target
  branch not ported; target must exist)
