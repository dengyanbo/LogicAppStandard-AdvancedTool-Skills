# Reference 05 — Resource Naming (tables, blobs, queues, file shares)

Quick lookup for *every* storage resource the tool can address. All naming
derives from the hashes in `references/01-storage-prefix-hashing.md`.

Symbols used below:

| Symbol | Definition |
| --- | --- |
| `laH` | `MurmurHash64(LogicAppName.ToLower())` trimmed to 15 lower-hex |
| `wfH` | `MurmurHash64(flowId.ToLower())` trimmed to 15 lower-hex |
| `D` | UTC date as `yyyyMMdd` |

## Tables

| Purpose | Name |
| --- | --- |
| Main workflow definition table | `flow{laH}flows` |
| Per-flow `flows` (mirror) | `flow{laH}{wfH}flows` |
| Per-flow `runs` | `flow{laH}{wfH}runs` |
| Per-flow `histories` | `flow{laH}{wfH}histories` |
| Per-flow per-day actions | `flow{laH}{wfH}{D}t000000zactions` |
| Per-flow per-day variables | `flow{laH}{wfH}{D}t000000zvariables` |
| Job queue triggers | `flow{laH}jobtriggers` |
| Job queue jobs | `flow{laH}jobs` |
| Job queue partitions | `flow{laH}jobdefinitions` |

## Blob containers

| Purpose | Name |
| --- | --- |
| Per-flow run-history payloads | `flow{laH}{wfH}` (the bare prefix is the container name) |
| Logic App general | `azure-webjobs-hosts`, `azure-webjobs-secrets`, `scm-releases`, etc. (App Service standard) |

`CleanUpContainers` iterates all blob containers and matches by prefix.

## Queues

| Purpose | Name |
| --- | --- |
| Workflow trigger queue | `flow{laH}{wfH}` (same name as blob container) |
| Job queue | `flow{laH}jobs` (also exists as table) |

## File Share

The Logic App's `wwwroot` lives in the **content** file share addressed by
`WEBSITE_CONTENTAZUREFILECONNECTIONSTRING`. The share name is in the
`WEBSITE_CONTENTSHARE` env var (not currently read by the tool — passed in
by the user to `SyncToLocal`). Typical default: `<site-name>-content`.

## ARM resources

| Purpose | Pattern |
| --- | --- |
| Logic App site | `/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Web/sites/{site}` |
| Site app settings | `…/config/appsettings` |
| Site app settings (list) | `…/config/appsettings/list` |
| Site restart | `…/restart` |
| Workflow runs (resubmit) | `…/hostruntime/runtime/webhooks/workflow/api/management/workflows/{wf}/runs/{runId}/resubmit` |
| Workflow runs (list) | `…/hostruntime/runtime/webhooks/workflow/api/management/workflows/{wf}/runs` |
| Service tags | `/subscriptions/{sub}/providers/Microsoft.Network/locations/{region}/serviceTags?api-version=2023-09-01` |

See `references/07-arm-endpoints.md` for the full URL templates and the
api-version pinning each endpoint requires.

## Helper to put it all together

```python
# src/lat/storage/prefix.py (continuation)

def per_flow_container(la_name: str, flow_id: str) -> str:
    return f"flow{logic_app_prefix(la_name)}{workflow_prefix(flow_id)}"

def per_flow_queue(la_name: str, flow_id: str) -> str:
    return per_flow_container(la_name, flow_id)

def per_day_action_table(la_name: str, flow_id: str, yyyymmdd: str) -> str:
    return f"flow{logic_app_prefix(la_name)}{workflow_prefix(flow_id)}{yyyymmdd}t000000zactions"

def per_day_variable_table(la_name: str, flow_id: str, yyyymmdd: str) -> str:
    return f"flow{logic_app_prefix(la_name)}{workflow_prefix(flow_id)}{yyyymmdd}t000000zvariables"

def job_queue_tables(la_name: str) -> dict[str, str]:
    h = logic_app_prefix(la_name)
    return {
        "jobs": f"flow{h}jobs",
        "jobtriggers": f"flow{h}jobtriggers",
        "jobdefinitions": f"flow{h}jobdefinitions",
    }
```

## Caveat — naming-change risk

The hashing scheme has been stable since LA Std GA, but the date-suffix
infix changed from `…actions` (older builds) to `…t000000zactions` (current).
The tool only supports the current form. If you target an older LA Std
deployment, capture a real table list with `az storage table list` and
update the helpers accordingly.
