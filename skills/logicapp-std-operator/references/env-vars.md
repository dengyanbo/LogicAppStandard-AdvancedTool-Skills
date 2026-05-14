# Reference: environment variables `lat` reads

Resolution precedence and what each one is for. Mirrors
`python-port/src/lat/settings.py`.

## Logic App identification

| Var | Required for | Format | Where it comes from |
| --- | --- | --- | --- |
| `WEBSITE_SITE_NAME` | every storage / ARM command | `<la-name>` | LA's name, as shown in the portal |
| `WEBSITE_RESOURCE_GROUP` | every ARM command | `<rg-name>` | LA's RG |
| `WEBSITE_OWNER_NAME` | ARM commands; storage Reader checks | `<sub-id>+<region>-<webspace>` | The LA's app setting; only the part before `+` matters |
| `REGION_NAME` | `validate storage-connectivity` (PE check), `validate whitelist-connector-ip` | `Australia East` (display name) | LA's region |
| `LAT_ROOT_FOLDER` | `validate workflows / scan-connections`, `workflow revert / clone / convert-to-stateful / restore-workflow-with-version / ingest-workflow` | absolute path | Defaults to `C:\home\site\wwwroot` |

## Storage authentication

`lat` chooses **one** of two modes per process based on these vars. Resolution
order (first match wins):

1. If `AzureWebJobsStorage__credential` is set (any value) → AAD mode
2. If `AzureWebJobsStorage` contains `AccountKey=` → connection-string mode
3. If `AzureWebJobsStorage__accountName` or `AzureWebJobsStorage__*ServiceUri`
   resolves to an account name → AAD mode
4. Otherwise → error: "AzureWebJobsStorage is not set"

| Var | Mode | Format |
| --- | --- | --- |
| `AzureWebJobsStorage` | connection-string | `DefaultEndpointsProtocol=https;AccountName=...;AccountKey=...;EndpointSuffix=core.windows.net` |
| `AzureWebJobsStorage__accountName` | AAD | `mystorage` (account name only) |
| `AzureWebJobsStorage__credential` | AAD | `managedidentity` (explicit opt-in) |
| `AzureWebJobsStorage__clientId` | AAD | User-assigned MI client ID (optional) |
| `AzureWebJobsStorage__tableServiceUri` | AAD | `https://mystorage.table.core.windows.net` |
| `AzureWebJobsStorage__blobServiceUri` | AAD | `https://mystorage.blob.core.windows.net` |
| `AzureWebJobsStorage__queueServiceUri` | AAD | `https://mystorage.queue.core.windows.net` |
| `WEBSITE_CONTENTAZUREFILECONNECTIONSTRING` | (file share, both modes) | A separate connection string just for the wwwroot file share. Used by `site sync-to-local-*` and as the file-share entry in `validate storage-connectivity`. |

## Managed Identity endpoint (auto-set inside App Service)

| Var | Set automatically inside Kudu? | Purpose |
| --- | --- | --- |
| `MSI_ENDPOINT` | yes | Legacy MSI HTTP endpoint |
| `MSI_SECRET` | yes | Legacy MSI auth header |
| `IDENTITY_ENDPOINT` | yes (newer hosts) | Modern MSI endpoint |
| `IDENTITY_HEADER` | yes (newer hosts) | Modern MSI auth header |

These are read by `azure-identity`'s `ManagedIdentityCredential`; you do not
normally set them by hand. On a workstation they're absent and the credential
chain falls through to `AzureCliCredential` (which is what `az login`
populates).

## Verification one-liner

```powershell
# PowerShell
'WEBSITE_SITE_NAME','WEBSITE_RESOURCE_GROUP','WEBSITE_OWNER_NAME','REGION_NAME',
'AzureWebJobsStorage','AzureWebJobsStorage__accountName','AzureWebJobsStorage__credential' |
  ForEach-Object {
    $value = (Get-Item "Env:$_" -ErrorAction SilentlyContinue).Value
    if ($_ -match 'Storage$' -and $value) { $value = '<set,' + $value.Length + ' chars>' }
    "{0,-50} = {1}" -f $_, ($value ?? '<unset>')
  }
```

```bash
# bash
for v in WEBSITE_SITE_NAME WEBSITE_RESOURCE_GROUP WEBSITE_OWNER_NAME REGION_NAME \
         AzureWebJobsStorage AzureWebJobsStorage__accountName AzureWebJobsStorage__credential; do
  val="${!v}"
  case "$v" in
    AzureWebJobsStorage) [ -n "$val" ] && val="<set,${#val} chars>" ;;
  esac
  printf "%-50s = %s\n" "$v" "${val:-<unset>}"
done
```

## Typical setups

### A) Local workstation, AAD storage, az login

```
WEBSITE_SITE_NAME              = MyLogicApp
WEBSITE_RESOURCE_GROUP         = my-rg
WEBSITE_OWNER_NAME             = <sub-id>+placeholder
REGION_NAME                    = Australia East
AzureWebJobsStorage__accountName = mystorage
# AzureWebJobsStorage NOT set
# (az login provides the credential)
```

### B) Local workstation, legacy conn string

```
WEBSITE_SITE_NAME              = MyLogicApp
WEBSITE_RESOURCE_GROUP         = my-rg
WEBSITE_OWNER_NAME             = <sub-id>+placeholder
REGION_NAME                    = Australia East
AzureWebJobsStorage            = DefaultEndpointsProtocol=https;AccountName=...;AccountKey=...;EndpointSuffix=core.windows.net
```

### C) Inside Kudu (no manual setup; everything auto-set)

The container already has all the LA's app settings exported. Just install
`lat` and run.
