# Playbook: Diagnostic-first (vague-symptom umbrella)

## Trigger conditions

Catch-all when the user reports a problem without enough detail to route
directly to a specific playbook:

- "Something's wrong with my Logic App, help me"
- "My LA is broken / acting weird / not working"
- "Just figure out what's wrong and fix it"
- "Help me debug" with no specifics
- Any prompt where you'd otherwise pick a playbook by guessing

## The diagnostic-first contract

Never reach for a destructive command on a vague symptom. Run the read-only
sweep first, narrow the search, then pivot to the specific playbook for the
root cause class you've identified.

## The standard sweep

Run these five in order. Stop at the first one that surfaces a clear cause
and skip ahead to the matching playbook.

### Step 1 — Storage layer

```powershell
lat validate storage-connectivity --skip-pe-check
```

```bash
lat validate storage-connectivity --skip-pe-check
```

Diagnoses DNS + TCP + OAuth for Blob / Queue / Table / File. If any row
shows `Failed`, the LA cannot reach its own backing storage — nothing else
will work until this is fixed.

**Pivot:** → [`diagnose-storage-issue.md`](diagnose-storage-issue.md)

### Step 2 — Service-provider connectivity

```powershell
lat validate sp-connectivity
```

DNS + TCP probe for every Service Provider in `connections.json`. Failures
here mean specific connectors (SFTP, Service Bus, SQL, etc.) can't reach
their endpoints.

**Pivot:** → [`diagnose-storage-issue.md`](diagnose-storage-issue.md) Layer 2

### Step 3 — Workflow validity

```powershell
lat validate workflows
```

POSTs every `workflow.json` to the runtime validator. Failures here are
designer-side bugs (parameter binding, action shape) that the portal's
design-time validation doesn't catch.

**Pivot:** Fix `workflow.json` (designer or editor); no `lat` playbook —
this is a content fix.

### Step 4 — Workflow inventory

```powershell
lat workflow list-workflows-summary
```

Confirms every expected workflow is in the storage table. If a workflow
the user knows should be there is missing, that's deletion / overwrite.

**Pivot:** → [`restore-deleted-workflow.md`](restore-deleted-workflow.md)
or [`merge-run-history.md`](merge-run-history.md)

### Step 5 — Recent failures

```powershell
$today = (Get-Date).ToUniversalTime().ToString("yyyyMMdd")
# Pick the suspect workflow first; if user can't name one, ask
lat runs retrieve-failures-by-date -wf <suspect-workflow> -d $today
```

```bash
today=$(date -u +%Y%m%d)
lat runs retrieve-failures-by-date -wf <suspect-workflow> -d "$today"
```

Reveals concrete run-level error messages.

**Pivot:** → [`triage-failed-runs.md`](triage-failed-runs.md)

### Step 6 (optional) — Host logs

```powershell
lat site filter-host-logs
```

Only works if the LA's wwwroot is accessible. Surfaces runtime-level error
/ warning entries that aren't tied to a specific workflow run (trigger
issues, host startup problems, etc.).

**Pivot:** Inspect the log lines and follow whichever component they point
at — usually back to one of the playbooks above.

## Root-cause pivot table

After the sweep, classify what you found and pick the matching playbook:

| What the sweep revealed | Pivot to |
| --- | --- |
| Storage `Failed` at DNS / TCP layer | [`diagnose-storage-issue.md`](diagnose-storage-issue.md) (Layer 1) + [`../references/nsp-troubleshooting.md`](../references/nsp-troubleshooting.md) |
| Storage `Failed` at Auth layer | [`diagnose-storage-issue.md`](diagnose-storage-issue.md) (Layer 1) + [`../references/aad-vs-connstring.md`](../references/aad-vs-connstring.md) |
| Service-provider `Failed` | [`diagnose-storage-issue.md`](diagnose-storage-issue.md) (Layer 2) |
| HTTP-action endpoint unreachable | `lat validate endpoint -e <url>` + [`diagnose-storage-issue.md`](diagnose-storage-issue.md) (Layer 3) |
| Workflow validator returns 400 | content fix in `workflow.json` (designer); not a `lat` playbook |
| Expected workflow missing from inventory | [`restore-deleted-workflow.md`](restore-deleted-workflow.md) |
| Workflow exists but old run history is gone (was deleted+recreated) | [`merge-run-history.md`](merge-run-history.md) |
| Many failed runs same workflow, same error | [`triage-failed-runs.md`](triage-failed-runs.md) → then maybe [`bulk-resubmit-or-cancel.md`](bulk-resubmit-or-cancel.md) (Path A) after fixing |
| Many runs stuck Running / Waiting | [`bulk-resubmit-or-cancel.md`](bulk-resubmit-or-cancel.md) (Path B — destructive) |
| Connector blocked by downstream firewall | [`unblock-connector-firewall.md`](unblock-connector-firewall.md) |
| About to make a big change, want to back up | [`snapshot-and-rollback.md`](snapshot-and-rollback.md) |
| Storage cost too high from old run history | [`safe-cleanup.md`](safe-cleanup.md) |
| Sweep passes everything; user still reports a problem | Ask for a specific run id / timestamp / error message; you don't have enough signal yet |

## Single-workflow variant

If the user already named a specific workflow ("workflow X is broken"),
narrow the sweep:

```powershell
lat validate workflows --root <wwwroot>   # may show X-specific design errors
lat workflow list-versions -wf <X>        # recent definition changes?
lat runs retrieve-failures-by-date -wf <X> -d $today
lat runs retrieve-failures-by-date -wf <X> -d (yesterday)
```

This tells you (in order):

1. Is the current `workflow.json` for X even valid?
2. Has it been modified recently (could be a regression from a recent
   change → consider `revert`)?
3. What are today's failures? Yesterday's?

## What never to do in this playbook

- Don't run `revert`, `restore-*`, `cleanup *`, `ingest-workflow`,
  `merge-run-history`, `cancel-runs`, or `snapshot-restore` without
  pivoting to that operation's own playbook first.
- Don't assume — if the sweep doesn't surface a clear cause, ask the user
  for more info ("any specific run id?", "when did it start?", "what
  changed recently?").
- Don't tell the user "everything looks fine, it's not a `lat` problem"
  if the sweep passes. Their problem is real; the right next step is to
  go look at Application Insights / portal run history with their input.

## Common patterns

### Pattern A: "It worked yesterday, broken today"

- Step 4 — was a workflow modified between yesterday and today?
  `list-versions` will show recent ChangedTime
- If a version landed today and runs started failing, consider `revert`

### Pattern B: "Trigger never fires"

- Step 6 — host logs often show trigger-evaluation errors that don't
  produce runs
- Or the trigger's underlying service provider — Step 2

### Pattern C: "Runs start but never finish"

- Step 5 — look at action-level payloads for the stuck action
- If hung in Waiting state, the downstream service is probably the issue;
  consider `lat validate endpoint -e <url>` for HTTP actions
