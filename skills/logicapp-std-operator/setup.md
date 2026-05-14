# Setup — env vars, auth, preflight checks

Before invoking any `lat` command, ensure both **identity** (who you are
auth'd as) and **context** (which LA you're targeting) are resolved.

## 1. Pick the platform

`lat` runs on any OS where Python ≥ 3.11 is available. Two common contexts:

- **From your workstation** (Windows / Mac / Linux) — uses `az login` for
  ARM and (if AAD storage) for storage auth.
- **Inside the LA's Kudu container** — uses the LA's Managed Identity
  automatically (no `az login` needed; `MSI_ENDPOINT` + `MSI_SECRET` are
  already in the env).

## 2. Install `lat`

```powershell
# PowerShell (Windows)
cd <repo>\python-port
uv venv
.\.venv\Scripts\Activate.ps1
uv pip install -e .
lat --version  # or: lat --help
```

```bash
# bash (Linux / Mac / Kudu Linux container)
cd <repo>/python-port
python -m venv .venv
source .venv/bin/activate
pip install -e .
lat --help
```

## 3. Set the LA context

These four env vars describe *which* Logic App `lat` is targeting:

| Env var | Required? | Source |
| --- | --- | --- |
| `WEBSITE_SITE_NAME` | yes | LA name (e.g. `MyLogicApp`) |
| `WEBSITE_RESOURCE_GROUP` | yes | RG name |
| `WEBSITE_OWNER_NAME` | yes | `<sub-id>+<region>-<webspace>` — the `+` and everything after is informational; only the sub-id matters to `lat` |
| `REGION_NAME` | yes | e.g. `Australia East` |

Helper one-liner to grab them all from `az`:

```powershell
# PowerShell
$la = "MyLogicApp"; $rg = "my-rg"
$site = az resource show --ids "/subscriptions/$(az account show --query id -o tsv)/resourceGroups/$rg/providers/Microsoft.Web/sites/$la" -o json | ConvertFrom-Json
$env:WEBSITE_SITE_NAME      = $site.name
$env:WEBSITE_RESOURCE_GROUP = $rg
$env:WEBSITE_OWNER_NAME     = "$(az account show --query id -o tsv)+placeholder"
$env:REGION_NAME            = $site.location
```

```bash
# bash
la=MyLogicApp; rg=my-rg
sub=$(az account show --query id -o tsv)
region=$(az resource show --ids "/subscriptions/$sub/resourceGroups/$rg/providers/Microsoft.Web/sites/$la" --query location -o tsv)
export WEBSITE_SITE_NAME="$la"
export WEBSITE_RESOURCE_GROUP="$rg"
export WEBSITE_OWNER_NAME="$sub+placeholder"
export REGION_NAME="$region"
```

## 4. Set the storage context

Pick **one** of the two paths depending on the LA's actual storage config.
See [`references/aad-vs-connstring.md`](references/aad-vs-connstring.md) if
unsure which applies.

### Path A: Legacy (connection string with AccountKey)

```powershell
# PowerShell
$env:AzureWebJobsStorage = "DefaultEndpointsProtocol=https;AccountName=<acct>;AccountKey=<key>;EndpointSuffix=core.windows.net"
```

```bash
# bash
export AzureWebJobsStorage="DefaultEndpointsProtocol=https;AccountName=<acct>;AccountKey=<key>;EndpointSuffix=core.windows.net"
```

### Path B: Modern (managed identity / Entra ID)

```powershell
# PowerShell
Remove-Item Env:AzureWebJobsStorage -ErrorAction SilentlyContinue
$env:AzureWebJobsStorage__accountName = "<storage-account-name>"
az login   # populates DefaultAzureCredential
```

```bash
# bash
unset AzureWebJobsStorage
export AzureWebJobsStorage__accountName="<storage-account-name>"
az login
```

For Path B, the identity you're logged in as (or the MI inside Kudu) needs
these RBAC roles on the storage account:

- **Storage Table Data Contributor** — for `workflow *`, `runs *`,
  `tools generate-table-prefix`, `cleanup tables`, `validate storage-connectivity`
- **Storage Blob Data Contributor** — for `cleanup containers`,
  `validate storage-connectivity` (Blob)
- **Storage Queue Data Contributor** — for `validate storage-connectivity` (Queue)

`Reader` on the subscription is enough for `validate storage-connectivity`
to look up the Storage service tag.

## 5. ARM permissions

Some commands also call ARM (Azure Resource Manager) via
`azure.mgmt.web.WebSiteManagementClient`:

| Command | ARM permission needed |
| --- | --- |
| `tools restart` | Website Contributor (or Logic App Standard Contributor) |
| `tools get-mi-token` | None (just acquires a token for the user / MI) |
| `workflow backup` (appsettings part) | Website Contributor or Logic App Standard Contributor |
| `site snapshot-create` (appsettings part) | same |
| `site snapshot-restore` (push appsettings) | same |
| `validate scan-connections --apply` | same |
| `validate whitelist-connector-ip` | the target service's *Contributor* role (Storage / Key Vault / Event Hub) |
| `validate sp-connectivity` | None (file system + DNS / TCP only) |

If a command's appsettings step fails with 403, that's the typical RBAC gap.
The command will warn and continue with the rest of the work.

## 6. Preflight verification (recommended)

Before running anything destructive, confirm context with three read-only
checks:

```powershell
# 1. Identity context resolved
lat tools get-mi-token | Select-String access_token

# 2. Storage context resolved (DNS + TCP + auth, all three)
lat validate storage-connectivity --skip-pe-check

# 3. The LA is reachable through ARM
lat workflow list-workflows-summary | Select-Object -First 5
```

If any of these fail, stop and diagnose — do NOT proceed to a destructive
command.

## 7. Common preflight errors

| Error | Likely cause | Fix |
| --- | --- | --- |
| `AzureWebJobsStorage is not set and no storage account could be resolved` | Neither Path A nor Path B set | Set one |
| `This request is not authorized by network security perimeter` | NSP blocks your client IP | See [`references/nsp-troubleshooting.md`](references/nsp-troubleshooting.md) |
| `AuthenticationRequired` / `AuthorizationFailure` (403) | RBAC missing | Grant the relevant role from §4 / §5 |
| `WEBSITE_SITE_NAME is not set` | Missing env vars from §3 | Set them |
| `Could not get token from DefaultAzureCredential` | Not logged in / no MI | `az login` on workstation; ensure MI is enabled in Kudu |
| `ZstdError: could not determine content size in frame header` | Outdated `lat` (pre-2b6e3fd) | Pull latest and `pip install -e .` again |
