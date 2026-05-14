# Playbook: Bulk resubmit or cancel runs

## Trigger conditions

- **Resubmit:** "Re-run all the failed runs from <date>", "I fixed the bug,
  retry everything that failed today", "Replay run id <X>"
- **Cancel:** "Cancel everything that's stuck running", "There's an infinite
  loop, stop it"
- Classic .NET names: `BatchResubmit`, `CancelRuns`

## Decide which command

| Intent | Command | Safety class |
| --- | --- | --- |
| Resubmit (creates new run instances; originals stay) | `runs batch-resubmit` | ⚠️ Destructive (recoverable via cancel) |
| Cancel in-flight runs (Running / Waiting → Cancelled) | `runs cancel-runs` | ⛔ Irreversible |

The two are not opposites — resubmit *adds* new runs, cancel *terminates*
existing in-flight ones. They are often used together: cancel the stuck
ones, fix the workflow, resubmit the originally-failed ones.

## Path A — Bulk resubmit

### Diagnose

1. How many runs match the proposed filter?

   ```powershell
   lat runs retrieve-failures-by-date -wf <wf> -d <yyyyMMdd> -o $env:TEMP\preview
   $count = (Get-Content $env:TEMP\preview\*FailureLogs.json | ConvertFrom-Json |
             Get-Member -MemberType NoteProperty | Measure-Object).Count
   "Will resubmit ~$count runs"
   ```

   ```bash
   tmp=$(mktemp -d)
   lat runs retrieve-failures-by-date -wf <wf> -d <yyyyMMdd> -o "$tmp"
   count=$(jq 'keys | length' "$tmp"/*FailureLogs.json)
   echo "Will resubmit ~$count runs"
   ```

2. **Throttle awareness:** the LA runtime accepts 50 resubmit calls per 5
   minutes per workflow. `lat runs batch-resubmit` paces itself, but a
   batch of 2000 will take ~3.5 hours wall-clock. Surface this to the user.

3. **Check the root cause is actually fixed.** If you resubmit before the
   workflow / connection / external system is fixed, all you get is 2000
   new failures.

### Decide

Ask via `ask_user`:
- **Workflow name** — exactly one workflow per invocation
- **Date range** — `--from YYYY-MM-DD` / `--to YYYY-MM-DD`
- **Status filter** — usually `Failed`, sometimes `Cancelled` or
  `TimedOut`
- **Estimated count** — show the user before they confirm
- **Whether the underlying bug is verified fixed** — important sanity check

### Execute

```powershell
# PowerShell
lat runs batch-resubmit `
    -wf <WorkflowName> `
    --from 2026-05-01 --to 2026-05-13 `
    --status Failed
```

```bash
# bash
lat runs batch-resubmit \
    -wf <WorkflowName> \
    --from 2026-05-01 --to 2026-05-13 \
    --status Failed
```

The command prints "Resubmitting run X / N" as it goes; the throttle is
50 / 5min so a long batch is a long wait. Don't kill the process — it has no
checkpoint, so resuming means re-running from the start (and that's fine
because resubmits are idempotent at the workflow level).

### Verify

After the batch finishes:

```powershell
lat runs retrieve-failures-by-date -wf <wf> -d <today's yyyyMMdd>
```

The new resubmitted runs appear as fresh entries with **today's** date
(not the original failure date), so use today's date in the verification
filter. Ideally the count of failures from these resubmits is much smaller
than the original count.

### Rollback

If the resubmits themselves are bad (e.g. you re-ran with a still-broken
connection), the new in-flight runs can be cancelled:

```powershell
lat runs cancel-runs -wf <wf> --yes
```

— but this cancels ALL Running/Waiting runs, including legitimate ones
that weren't part of your resubmit batch. There's no per-batch cancel.

## Path B — Cancel running / waiting runs

### ⛔ Irreversible — data loss

`cancel-runs` flips `Status` to `Cancelled` directly in the per-flow runs
table. The in-flight workflow execution is abandoned mid-stream; any
partial output, locked queues, or pending actions are NOT cleaned up. The
.NET tool's help text says it best:

> Cancelling all the running instances will cause data lossing for any
> running/waiting instances. Run history and resubmit feature will be
> unavailable for all waiting runs.

### Diagnose

```powershell
# How many would be cancelled?
lat runs retrieve-failures-by-date -wf <wf> -d <today>   # gives a feel
# But the real preview is via the runs table; query it directly:
```

There's no built-in `--dry-run`, but you can run the underlying query via
`az`:

```powershell
$prefix = lat tools generate-table-prefix -wf <wf> | Select-String 'Combined' |
          ForEach-Object { ($_ -split ': ')[1].Trim() }
$table = "flow${prefix}runs"
az storage entity query --account-name <acct> --auth-mode login `
    --table-name $table `
    --filter "Status eq 'Running' or Status eq 'Waiting'" `
    --query "items | length(@)"
```

### Decide

Via `ask_user` — show the count, quote the data-loss warning, and require
the user to type-confirm. If the count is > ~50, ask again.

### Execute

```powershell
lat runs cancel-runs -wf <WorkflowName> --yes
```

Output: "N runs cancelled successfully" + possibly "M runs cancelled failed
due to status changed" (those are runs that transitioned between SELECT and
UPDATE; re-run the command if needed to catch them).

### Verify

```powershell
lat runs retrieve-failures-by-date -wf <wf> -d <today>
```

The runs you just cancelled show up with `Status = Cancelled`.

### Rollback

**None.** Cancelled runs cannot be resumed. To re-execute the same input,
trigger the workflow afresh or use `batch-resubmit` if the originals are in
the runs table.

## Common combinations

### "Fix and replay" pattern

1. Identify the bad runs: `retrieve-failures-by-date`
2. Fix the workflow / connection / external system
3. (Optional) `cancel-runs` to stop any still-running bad ones
4. `batch-resubmit` for the fixed date range
5. Verify: re-check `retrieve-failures-by-date` for today

### "Emergency stop" pattern

1. `cancel-runs` to halt everything in flight (data loss; user must accept)
2. Fix
3. Manually trigger one canary run to confirm fix
4. (If applicable) `batch-resubmit` originals once confidence is restored

## Related .NET names

- `BatchResubmit` → `lat runs batch-resubmit`
- `CancelRuns` → `lat runs cancel-runs`
