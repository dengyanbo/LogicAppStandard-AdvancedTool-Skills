# Playbook: Restore a deleted workflow

## Trigger conditions

The user says one of:
- "I deleted workflow X by accident"
- "Workflow X is gone from the portal"
- "Can I get back a deleted workflow?"
- "I need to roll back workflow X" (this is actually a *revert*, see below)
- Uses the classic command name `RestoreSingleWorkflow` or
  `RestoreWorkflowWithVersion`

## Diagnose

1. Confirm the workflow ever existed in storage:

   ```powershell
   lat workflow list-workflows-summary | Select-String <WorkflowName>
   ```

   ```bash
   lat workflow list-workflows-summary | grep <WorkflowName>
   ```

   If absent, two possibilities: the workflow is older than ~90 days (runtime
   has evicted it) or the name is misspelled. Ask the user.

2. List the saved versions:

   ```powershell
   lat workflow list-versions -wf <WorkflowName>
   ```

   The output shows `Workflow ID`, `Version ID` (FlowSequenceId), and
   `Updated Time (UTC)`. There may be multiple FlowIds if the workflow was
   deleted and recreated with the same name; each line is one version on one
   FlowId.

3. (Optional) Decode a candidate version to verify it's the right one:

   ```powershell
   lat workflow decode -wf <WorkflowName> -v <FlowSequenceId> | Select-String -Pattern '"name"', '"actions"' -SimpleMatch
   ```

## Decide

Ask the user via `ask_user`:

1. **Which FlowId?** If `list-versions` showed exactly one FlowId, you can
   skip this and use it directly. Otherwise list each FlowId with its most
   recent version date and ask the user to pick.
2. **Which version?** Default to the most recent unless the user wants to
   roll further back.
3. **Where to write the RuntimeContext dump?** Default `.` (current dir);
   ask if the user wants somewhere else.

## Execute

⚠️ This is a **Destructive (recoverable)** action — it overwrites
`<wwwroot>\<WorkflowName>\workflow.json`. If the user might have a different
version of `workflow.json` locally that they don't want to lose, run a
backup first:

```powershell
# Safety net (skip if you just confirmed nothing local exists)
lat workflow backup --output .\pre-restore-backup
```

Then the actual restore:

```powershell
# PowerShell
lat workflow restore-workflow-with-version `
    -wf <WorkflowName> `
    --flow-id <FlowId> `
    -v <FlowSequenceId> `
    --runtime-context-output .
```

```bash
# bash
lat workflow restore-workflow-with-version \
    -wf <WorkflowName> \
    --flow-id <FlowId> \
    -v <FlowSequenceId> \
    --runtime-context-output .
```

If the user only supplies `-wf` (no FlowId / version), the command will
prompt interactively for both.

## Verify

1. The restore writes two artefacts:
   - `<wwwroot>\<WorkflowName>\workflow.json` — the workflow definition
   - `RuntimeContext_<WorkflowName>_<version>.json` — the API-connection
     metadata
2. Tell the user to **refresh** (F5) the Logic Apps workflow page in the
   portal. The workflow should reappear.
3. Re-run `lat workflow list-versions -wf <WorkflowName>` — the version they
   restored should now be the current one.

## Rollback

If the restore was wrong:

1. The pre-restore backup (if you ran one) is at `.\pre-restore-backup\`.
2. Or: choose a different version and re-run `restore-workflow-with-version`.
3. Or: delete the workflow folder (`rm -rf <wwwroot>/<WorkflowName>`) to
   undo the file write — but the storage table will still have the row.

## Post-restore checklist

Tell the user:

1. **Open `RuntimeContext_<wf>_<ver>.json`** and verify the API connections
   listed there are still present in `connections.json`. If any are missing
   (because the connection was deleted along with the workflow), the
   restored workflow will fail at runtime until the connection is re-added.
2. **Test-run** the workflow once before assuming it works.

## When to NOT use this playbook

- The workflow is older than ~90 days (storage table eviction) — there's
  nothing to restore from. Tell the user.
- The user wants to **revert** an existing workflow to an older version
  (workflow still exists in the portal). Use `lat workflow revert -wf X -v Y`
  instead — it's simpler and doesn't dump RuntimeContext.
- The user wants to copy a workflow into a *different* name. Use
  `lat workflow clone -s OLD -t NEW`.

## Related .NET names

- `RestoreSingleWorkflow` (deprecated upstream) → use this playbook
- `RestoreWorkflowWithVersion` → use this playbook
- `RestoreAll` (removed upstream) → run this playbook in a loop, one workflow
  at a time; do NOT try to do them all at once
