# Playbook: Triage failed runs

## Trigger conditions

- "Workflow X has been failing", "lots of failures today"
- "What happened in run <run-id>?"
- "Find me runs that hit error 'foo'"
- "Generate a list of portal URLs for failed runs yesterday"
- Classic .NET names: `RetrieveFailures`, `SearchInHistory`,
  `RetrieveActionPayload`, `GenerateRunHistoryUrl`

## Pick the right command

The choice depends on what the user knows:

| User knows | Use |
| --- | --- |
| Just the workflow and a date | `runs retrieve-failures-by-date` |
| A specific run id | `runs retrieve-failures-by-run` |
| A keyword (error message, token, customer id) | `runs search-in-history` |
| Just wants portal links for clickthrough | `runs generate-run-history-url` |
| Wants one specific action's input/output | `runs retrieve-action-payload` |

## Diagnose

Start with whatever the user can tell you. If they only have "it's broken,
fix it":

1. Get a workflow name shortlist:

   ```powershell
   lat workflow list-workflows-summary | Select-Object -First 30
   ```

2. Ask which workflow.

3. Get a date — usually "today" or "yesterday" (UTC). Confirm timezone.

## Path A — "list all failures on <date>"

```powershell
# PowerShell
lat runs retrieve-failures-by-date -wf <WorkflowName> -d <YYYYMMDD> -o .
```

```bash
# bash
lat runs retrieve-failures-by-date -wf <WorkflowName> -d <YYYYMMDD> -o .
```

Output: `<LA>_<wf>_<date>_FailureLogs.json` grouped by run id, with the
error message, action inputs/outputs, and (compressed) error code per row.
Control-action failures ("An action failed. No dependent actions
succeeded.") are filtered automatically — those are noise.

## Path B — "explain run <run-id>"

```powershell
lat runs retrieve-failures-by-run -wf <WorkflowName> -r <RunID>
```

The command looks up the run's `CreatedTime` from the runs table to find the
right per-day actions table automatically. Output:
`<LA>_<wf>_<RunID>_FailureLogs.json`.

## Path C — "find runs that mention <keyword>"

```powershell
lat runs search-in-history -wf <WorkflowName> -d <YYYYMMDD> -k "<keyword>"
```

Searches inlined input/output payloads on the given date for the substring.
Output:
- stdout table of matching run ids
- `<LA>_<wf>_<date>_SearchResults.json` (records grouped by run id)

**Caveat:** the Python port currently only matches inlined content. Payloads
that overflow to blob storage (>~1 MB) are not searched. If the user expects
a hit and gets nothing, mention this.

## Path D — "give me portal URLs to click"

```powershell
lat runs generate-run-history-url -wf <WorkflowName> -d <YYYYMMDD> [-f <keyword>]
```

The `-f` filter is optional; when supplied, it walks the actions table and
only emits runs whose output / error / status code matches. Output:
`<LA>_<wf>_<date>_RunHistoryUrl.json` with one entry per matching run.

Open the JSON, copy `RunHistoryUrl`, paste into a browser → goes straight to
the run-monitor blade.

## Path E — "I want the inputs/outputs of action 'doStuff' on <date>"

```powershell
lat runs retrieve-action-payload `
    -wf <WorkflowName> -d <YYYYMMDD> -a <ActionName> -o .
```

Output: `<wf>_<date>_<action>.json` with one entry per occurrence of that
action on the date (the action may have run many times, once per workflow
run).

## When you have findings

Summarize for the user:

1. **Counts** — how many runs failed, how many matched the keyword
2. **Pattern** — what error code / message recurs
3. **One concrete example** — paste the most representative run's error +
   input snippet
4. **Recommended next step**:
   - All failed at the same external API → fix the API / connection (not
     `lat`'s job)
   - All failed with timeout → designer-side: bump the timeout or retry
     policy
   - All failed because of a specific input shape → run
     `lat runs batch-resubmit` after the fix is in place (see
     [`bulk-resubmit-or-cancel.md`](bulk-resubmit-or-cancel.md))

## What this playbook will NOT find

- Failures in **trigger** evaluation that never produced a run (those don't
  hit the runs table). Look at `LogFiles\Application\Functions\Host\` via
  `lat site filter-host-logs` instead.
- Failures older than ~90 days (storage table eviction).
- Designer-time validation errors — run `lat validate workflows` for those.

## Related .NET names

- `RetrieveFailures` → Path A / Path B
- `SearchInHistory` → Path C
- `GenerateRunHistoryUrl` → Path D
- `RetrieveActionPayload` → Path E
