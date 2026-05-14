# Playbook: Snapshot and rollback

## Trigger conditions

- "Back up everything before I deploy / migrate / change X"
- "Roll my LA back to <date / before the change>"
- "I broke something, restore the previous state"
- Classic .NET names: `Snapshot -mode Create`, `Snapshot -mode Restore`

## When to use this playbook (vs alternatives)

| Goal | Use |
| --- | --- |
| Capture **wwwroot + appsettings** to a local folder for safekeeping | `site snapshot-create` |
| Restore **wwwroot + appsettings** from a previous snapshot | `site snapshot-restore` |
| Capture only **workflow definitions** (no appsettings, no other files) | `workflow backup` |
| Pull a remote LA's wwwroot to your laptop for offline editing | `site sync-to-local-*` |
| Revert one workflow to a previous version | `workflow revert` |

`snapshot-*` is the heaviest tool — it touches **every file** in `wwwroot`
and **all** appsettings. Use it before risky operations (migrations,
appsetting overhauls, ASP plan changes); use the more targeted commands for
day-to-day work.

## Snapshot create

### Diagnose

Confirm the LA's wwwroot is reachable from where you're running `lat`:

```powershell
# If you're running locally (not in Kudu)
lat site filter-host-logs   # quick sanity that the LA SCM endpoint works
```

If running inside Kudu, the wwwroot is the local file system — always
reachable.

### Decide

Ask the user:
- **Snapshot folder location** (default: `./Snapshot_<yyyyMMddHHmmss>`)
- **Whether to include appsettings** (default: yes; needs Website Contributor
  on MI)

### Execute

```powershell
# PowerShell
lat site snapshot-create --output .\Snapshot_$(Get-Date -Format yyyyMMddHHmmss)
```

```bash
# bash
lat site snapshot-create --output ./Snapshot_$(date +%Y%m%d%H%M%S)
```

The command copies every file under wwwroot to the snapshot folder and
dumps appsettings to `<snapshot>/appsettings.json`. If the appsettings call
fails (RBAC), the command warns and continues with just the files.

### Verify

```powershell
Get-ChildItem -Recurse <snapshot> | Measure-Object -Property Length -Sum
```

Compare to the LA's wwwroot size — they should be very close. The appsettings
JSON should have all the expected keys.

## Snapshot restore

### ⚠️ Read this first

`snapshot-restore` **overwrites every file in wwwroot** with the snapshot
contents AND **replaces appsettings** with the snapshot's snapshot. Anything
in wwwroot that's not in the snapshot is deleted. Anything in appsettings
that's not in the snapshot's appsettings is removed.

This is **Destructive (recoverable)**: recoverable only if you have an even
older snapshot to fall back to. Always take a fresh `snapshot-create` *of
the current state* before running `snapshot-restore`, so you can roll back
the rollback if needed.

### Diagnose

1. The user must have a snapshot folder. Confirm it exists and looks valid:

   ```powershell
   Test-Path "<snapshot>/appsettings.json"
   Get-ChildItem "<snapshot>" -Recurse -File | Measure-Object | Select-Object Count
   ```

2. Compare to the live state:

   ```powershell
   $live  = (lat workflow list-workflows-summary | Measure-Object).Count
   $local = (Get-ChildItem "<snapshot>" -Directory | Where-Object Name -ne ".git" |
             Where-Object { Test-Path (Join-Path $_.FullName "workflow.json") } |
             Measure-Object).Count
   "Live workflows: $live   Snapshot workflows: $local"
   ```

   A wildly different count is a red flag — confirm with the user before
   proceeding.

### Decide

Via `ask_user`:

1. Confirm the snapshot path
2. Confirm the user understands: this OVERWRITES the live LA. Wwwroot files
   not in the snapshot will be DELETED. Appsetting keys not in the snapshot
   will be REMOVED.
3. Get a fresh "before" snapshot — required:

   ```powershell
   lat site snapshot-create --output .\PreRestore_$(Get-Date -Format yyyyMMddHHmmss)
   ```

4. Now run the restore (with `--yes` only after explicit ask_user):

   ```powershell
   lat site snapshot-restore --input <snapshot> --yes
   ```

### Verify

Pushing new appsettings causes the LA to auto-restart. After ~30 seconds:

```powershell
lat workflow list-workflows-summary | Select-Object -First 5
lat validate workflows
```

Tell the user to refresh the portal and verify the workflow page reflects
the snapshot.

### Rollback

If the restore was wrong:

```powershell
lat site snapshot-restore --input .\PreRestore_<yyyyMMddHHmmss> --yes
```

You took that pre-restore snapshot precisely for this case.

## Common pitfalls

| Pitfall | Mitigation |
| --- | --- |
| Snapshot doesn't include the LA's MI assignments / ASP plan / network config | Those are ARM-level; `lat` doesn't touch them. Use `az` or Bicep to capture |
| `connections.json` references API connections that have been deleted since the snapshot | After restore, ensure the referenced connection resources still exist in the RG |
| Auto-restart fails the next trigger fire | The LA's runtime catches up within ~60 seconds; rerun the trigger after a minute |
| User wants a "rolling backup" not a one-off | Schedule `snapshot-create` from a CI job; rotate folders manually |

## Related .NET names

- `Snapshot -mode Create` → `lat site snapshot-create`
- `Snapshot -mode Restore` → `lat site snapshot-restore`
