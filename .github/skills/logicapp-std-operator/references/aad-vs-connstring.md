# Reference: AAD-vs-connection-string decision tree

## TL;DR

Modern Logic Apps Standard increasingly run with **managed identity for
storage** (no shared keys). The .NET `LogicAppAdvancedTool.exe` only
understands the legacy conn-string form. `lat` understands both.

## How to tell which mode the target LA uses

```powershell
# PowerShell
$la = "MyLogicApp"; $rg = "my-rg"
az functionapp config appsettings list --name $la --resource-group $rg `
  --query "[?contains(name,'AzureWebJobsStorage')].{name:name, hasValue:(value!='')}" `
  -o table
```

```bash
# bash
la=MyLogicApp; rg=my-rg
az functionapp config appsettings list --name "$la" --resource-group "$rg" \
  --query "[?contains(name,'AzureWebJobsStorage')].{name:name, hasValue:(value!='')}" \
  -o table
```

Read the rows:

| Settings present | Mode |
| --- | --- |
| `AzureWebJobsStorage` only (with a long value containing `AccountKey=`) | Legacy conn-string |
| `AzureWebJobsStorage__accountName` (no `AzureWebJobsStorage`) | AAD (managed identity) |
| Both | Mixed — depends on app's local `Run` config; `lat` follows the resolution order in `env-vars.md` |
| Neither but `AzureWebJobsStorage__credential` set | AAD (explicit opt-in) |

## Decision tree

```
Did you find AccountKey=... in AzureWebJobsStorage?
├─ Yes → LEGACY mode
│        Set AzureWebJobsStorage locally to the same value
│        `lat` will use TableServiceClient.from_connection_string()
│
└─ No  → AAD mode
         Set AzureWebJobsStorage__accountName=<account>
         Either:
         (a) az login on your workstation, OR
         (b) export AzureWebJobsStorage__credential=managedidentity
             on a host with MSI
         `lat` will use DefaultAzureCredential() + TableServiceClient(endpoint, credential)
```

## RBAC needed in AAD mode

The identity that `lat` is auth'd as needs these roles on the storage
account (or its parent RG / sub):

- **Storage Table Data Contributor** — required for almost every command
  that touches storage tables (most of `workflow *` and `runs *`)
- **Storage Blob Data Contributor** — for `cleanup containers`, the Blob
  portion of `validate storage-connectivity`
- **Storage Queue Data Contributor** — for the Queue portion of
  `validate storage-connectivity`

`Storage Account Contributor` alone is NOT enough — it grants management-plane
control (firewall rules, etc.) but not data-plane access.

Check what your principal has:

```powershell
$me = az ad signed-in-user show --query id -o tsv
az role assignment list `
  --scope "/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/<acct>" `
  --assignee $me `
  --query "[].roleDefinitionName" -o tsv
```

```bash
me=$(az ad signed-in-user show --query id -o tsv)
az role assignment list \
  --scope "/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/<acct>" \
  --assignee "$me" \
  --query "[].roleDefinitionName" -o tsv
```

## Diagnosing "I'm in AAD mode but it doesn't work"

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `AzureWebJobsStorage is not set and no storage account could be resolved` | Neither `AzureWebJobsStorage` nor `AzureWebJobsStorage__accountName` is set | Set one |
| `AuthenticationRequired` / `AuthorizationFailure` (403) on Tables / Blobs | RBAC role missing | Grant the Data Contributor role (above) |
| `This request is not authorized by network security perimeter` | NSP / firewall blocks | See [`nsp-troubleshooting.md`](nsp-troubleshooting.md) |
| `ChainedTokenCredentialError: ... DefaultAzureCredential failed` | No credential source available | `az login` or set service-principal env vars |
| `lat` works for some tables but 403 on others | Container-level / table-level ACL overrides | RBAC at the **account** level usually fixes; check for explicit table ACLs |

## Forcing one mode over the other

`lat` resolves mode on every command (env-driven, not cached). To force:

```powershell
# Force LEGACY mode for this shell, ignoring any AAD env vars
$env:AzureWebJobsStorage = "DefaultEndpointsProtocol=https;AccountName=...;AccountKey=...;EndpointSuffix=core.windows.net"
Remove-Item Env:AzureWebJobsStorage__accountName -ErrorAction SilentlyContinue
Remove-Item Env:AzureWebJobsStorage__credential -ErrorAction SilentlyContinue
```

```powershell
# Force AAD mode
Remove-Item Env:AzureWebJobsStorage -ErrorAction SilentlyContinue
$env:AzureWebJobsStorage__accountName = "mystorage"
```
