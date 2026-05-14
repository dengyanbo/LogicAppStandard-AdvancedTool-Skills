# Reference 07 — ARM Endpoints used by the tool

Every ARM call made by `LogicAppAdvancedTool`, with method, URL template,
query parameters, body shape, and the Python equivalent.

All calls go through `Shared/HttpOperations.cs:9-21` (sync) and `:41-58`
(async), which:
1. Set `Authorization: Bearer {token}`.
2. Optionally attach a JSON body via `StringContent(content, UTF8, "application/json")`.
3. Synchronously call `client.Send(request)`.
4. Throw `ExpectedException` if `IsSuccessStatusCode` is false, including
   the response body.

## 1. Site app settings

### 1.1 Read

`Shared/AppSettings.cs:91-101`:

```
POST {ManagementBaseUrl}/config/appsettings/list?api-version=2022-03-01
Authorization: Bearer {token}
```

> Note: it is **POST** (not GET) per Azure's "List" pattern for site
> properties that contain secrets. The response wraps the settings dict
> under `properties`.

Response shape:

```json
{
  "id": "...",
  "name": "appsettings",
  "type": "Microsoft.Web/sites/config",
  "properties": {
    "AzureWebJobsStorage": "...",
    "FUNCTIONS_WORKER_RUNTIME": "dotnet",
    ...
  }
}
```

### 1.2 Write

`Shared/AppSettings.cs:103-115`:

```
PUT {ManagementBaseUrl}/config/appsettings?api-version=2022-03-01
Authorization: Bearer {token}
Content-Type: application/json
```

Body: the full response from the list call, with `properties` replaced by
the new settings dict. The tool does **not** PATCH — it always sends the
full envelope (id, name, type, location, properties), which Azure requires
for PUT on `config/appsettings`.

### 1.3 Python

```python
# src/lat/arm.py
import json
import httpx
from .msi import retrieve_token, verify_token
from .settings import settings


def _arm_base() -> str:
    s = settings
    return (
        f"https://management.azure.com/subscriptions/{s.subscription_id}"
        f"/resourceGroups/{s.resource_group}"
        f"/providers/Microsoft.Web/sites/{s.logic_app_name}"
    )


def get_appsettings() -> dict:
    token = retrieve_token()
    url = f"{_arm_base()}/config/appsettings/list?api-version=2022-03-01"
    r = httpx.post(url, headers={"Authorization": f"Bearer {token.access_token}"})
    r.raise_for_status()
    return r.json()["properties"]


def put_appsettings(properties: dict) -> None:
    token = retrieve_token()
    list_url = f"{_arm_base()}/config/appsettings/list?api-version=2022-03-01"
    headers = {"Authorization": f"Bearer {token.access_token}"}
    envelope = httpx.post(list_url, headers=headers).json()
    envelope["properties"] = properties
    put_url = f"{_arm_base()}/config/appsettings?api-version=2022-03-01"
    r = httpx.put(put_url, headers={**headers, "Content-Type": "application/json"},
                  content=json.dumps(envelope))
    r.raise_for_status()
```

## 2. Site restart

```
POST {ManagementBaseUrl}/restart?api-version=2022-03-01
Authorization: Bearer {token}
```

No body. 200/204 success. Used by `Tools Restart` and implicitly by
`Snapshot Restore` (Azure restarts the site automatically when app settings
change).

## 3. Workflow runs — list / cancel / resubmit

`BatchResubmit` and `CancelRuns` call the **hostruntime** endpoint, which
proxies into the Logic App runtime's management API on the site itself,
*not* an ARM provider endpoint.

Base:

```
{ManagementBaseUrl}/hostruntime/runtime/webhooks/workflow/api/management
```

| Operation | Method | URL suffix |
| --- | --- | --- |
| List runs | GET | `/workflows/{workflow}/runs?api-version=2018-11-01&$filter=status eq 'Failed' and startTime ge '{iso}' and startTime le '{iso}'` |
| Get one run | GET | `/workflows/{workflow}/runs/{runId}?api-version=2018-11-01` |
| Cancel run | POST | `/workflows/{workflow}/runs/{runId}/cancel?api-version=2018-11-01` |
| Resubmit run | POST | `/workflows/{workflow}/runs/{runId}/resubmit?api-version=2018-11-01` |

The list response supports `nextLink` for pagination — chase it until
absent. The Python port must respect `nextLink` (the .NET tool does this
inside the resubmit loop).

### 3.1 Throttling

The list endpoint paginates ~50 items per page, and the resubmit endpoint
is rate-limited by the LA host to roughly **50 resubmits per 5 minutes**.
When throttled, the response is HTTP 429 with a `Retry-After` header. The
.NET tool catches this and sleeps 2 minutes before retrying. Mirror:

```python
def _resubmit_one(token, workflow, run_id) -> None:
    url = f"{_runtime_base()}/workflows/{workflow}/runs/{run_id}/resubmit?api-version=2018-11-01"
    while True:
        r = httpx.post(url, headers={"Authorization": f"Bearer {token.access_token}"})
        if r.status_code == 429:
            retry_after = int(r.headers.get("Retry-After", "120"))
            time.sleep(retry_after)
            continue
        r.raise_for_status()
        return
```

## 4. Service tags

`Shared/ServiceTagRetriever.cs:19-37`:

```
GET https://management.azure.com/subscriptions/{sub}/providers/Microsoft.Network/locations/{region-lower}/serviceTags?api-version=2023-09-01
Authorization: Bearer {token-for-management.azure.com}
```

Response contains `.values` which is an array of `AzureServiceTag` objects
(name, id, properties.addressPrefixes, properties.region, etc.). The tool
flattens to `Dictionary<name, properties>`.

The MI needs subscription-level Reader; otherwise the response omits
`values` and the tool throws "*Cannot retrieve service tags due to
permission issue, please assign Logic App MI with reader role on
subscription level and retry command after 2 minutes.*"

## 5. Target-service firewalls (WhitelistConnectorIP)

The user provides the full ARM resource ID. The tool then:

1. Picks an api-version based on the resource provider:
   * `Microsoft.Storage/storageAccounts` → `2023-01-01`
   * `Microsoft.KeyVault/vaults` → `2022-07-01`
   * `Microsoft.EventHub/namespaces` → `2022-10-01-preview` (network rule sets)
2. GET the resource.
3. Mutate `properties.networkAcls.ipRules` (Storage / Key Vault) or
   `value.ipMask` array (Event Hub).
4. PUT or POST back.

For the Python port, consult the C# `Operations/WhitelistConnectorIP.cs`
for the exact body shape per resource type. The api-versions may need to
be refreshed periodically — pin them in a constants module.

## 6. Connector IP regions

The IPs to whitelist come from Azure's documented service tag
`AzureConnectors.<region>`. Look up via service tags (§4) — the regional
suffix is `AppSettings.Region.ToLower()`.

## 7. Errors and retries

`Shared/HttpOperations.cs` does **no** retry — every call is a single
attempt. The Python port should:

* Use `httpx.HTTPTransport(retries=3)` for transient connect failures.
* On 429, sleep `Retry-After` then retry up to 5 times.
* On 401, refresh the MI token once and retry.
* On 5xx, exponential backoff (1s, 2s, 4s) for up to 3 attempts.
* On 4xx other than 429/401, raise immediately with the body included.

## 8. Disabling logging of bearer tokens

`httpx` (and `azure-core`) sometimes log the `Authorization` header at DEBUG
level. Suppress by attaching a redacting hook:

```python
def _redact(request: httpx.Request) -> None:
    if "Authorization" in request.headers:
        request.headers["Authorization"] = "Bearer <redacted>"
```

…but only when emitting logs, not on the wire.
