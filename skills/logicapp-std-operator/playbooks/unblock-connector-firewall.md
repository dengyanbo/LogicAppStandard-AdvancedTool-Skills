# Playbook: Unblock Azure Connector against a downstream firewall

## Trigger conditions

- "My Logic App's connector can't reach the Storage account / Key Vault /
  Event Hub because of a firewall"
- "Open the firewall for Azure Connectors"
- Classic .NET name: `WhitelistConnectorIP`

## What this fixes

Azure-managed connectors (the ones living in the `Microsoft.Web/connections`
namespace, like Storage Blob, Service Bus, Outlook etc.) make calls from a
**regional IP pool** published as the `AzureConnectors.<region>` service
tag. If the downstream resource (your Storage account, KV, EH) has its
firewall set to `Deny by default`, those calls get blocked.

`lat validate whitelist-connector-ip` fetches the current IP range for the
LA's region and adds those prefixes to the target resource's
`networkAcls.ipRules`. Supports three downstream resource types:

- `Microsoft.Storage/storageAccounts`
- `Microsoft.KeyVault/vaults`
- `Microsoft.EventHub/namespaces`

## What this does NOT fix

- Connector-to-Internet egress restrictions (those are LA-side, not
  downstream)
- Private endpoint configurations (different model entirely; whitelisting
  IPs doesn't help if the target is private-only)
- Authentication / RBAC failures
- Network Security Perimeter on the downstream (NSP > network ACL)
- Cross-tenant connections

## Diagnose

1. Confirm the connector failure is actually network. Look at the run
   history for the failing action:

   ```powershell
   lat runs retrieve-action-payload -wf <wf> -d <yyyyMMdd> -a <action>
   ```

   Network blocks usually show `403 IpAuthorizationFailure` or
   `Forbidden by network rules`. Authentication failures show
   `AuthenticationFailed` or `401`. Don't confuse them.

2. Inspect the downstream resource's firewall:

   ```powershell
   # PowerShell — example for a Storage account
   az storage account show --name <acct> --resource-group <rg> `
       --query "{publicAccess:publicNetworkAccess, defaultAction:networkAcls.defaultAction, ipRules:networkAcls.ipRules[].value}" -o json
   ```

   ```bash
   az storage account show --name <acct> --resource-group <rg> \
       --query "{publicAccess:publicNetworkAccess, defaultAction:networkAcls.defaultAction, ipRules:networkAcls.ipRules[].value}" -o json
   ```

   If `defaultAction: Deny` and `ipRules` doesn't include
   `AzureConnectors.<region>`'s prefixes, this playbook is right.

3. Verify the LA's region:

   ```powershell
   az resource show --ids "/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Web/sites/<la>" --query location -o tsv
   ```

   The region name must match exactly (e.g. `Australia East`, not
   `australiaeast`). The command normalises by stripping spaces, so
   "Australia East" → "AustraliaEast" → looks up `AzureConnectors.AustraliaEast`.

## Decide

Ask the user via `ask_user`:

1. **Target resource ID** — full ARM ID, e.g.
   `/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/<acct>`
2. **Region** — only if you can't infer it from the LA's location
3. **Has the user reviewed the existing ipRules?** Adding the connector
   range will mix Azure-owned IPs in with whatever's already there.

Always preview with `--dry-run` first.

## Execute

### Step 1: Dry run

```powershell
# PowerShell
lat validate whitelist-connector-ip `
    --resource-id "/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/<acct>" `
    --dry-run
```

```bash
# bash
lat validate whitelist-connector-ip \
    --resource-id "/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/<acct>" \
    --dry-run
```

The output lists every IP that *would* be added (it skips any that are
already in `ipRules`). Show the list to the user.

### Step 2: Apply

After user confirms via `ask_user`:

```powershell
lat validate whitelist-connector-ip `
    --resource-id "<full-arm-id>"
```

The command PUTs the updated resource via ARM. Note that the command also
sets `networkAcls.defaultAction = "Deny"` (if it wasn't already) and
`properties.publicNetworkAccess = "Enabled"` to ensure the IP rules are
actually enforced.

## Verify

1. Re-inspect the firewall:

   ```powershell
   az storage account show --name <acct> --resource-group <rg> `
       --query "networkAcls.ipRules[].value" -o tsv
   ```

   The new ranges should be present.

2. Wait a minute for propagation, then trigger the connector action in a
   test run. Look at:

   ```powershell
   lat runs retrieve-action-payload -wf <wf> -d <today> -a <action>
   ```

   The previously-blocked action should now succeed.

## Rollback

If you need to remove the added rules:

```powershell
# PowerShell — example for Storage
az storage account network-rule remove `
    --account-name <acct> --resource-group <rg> `
    --ip-address <one-of-the-added-ranges>
```

```bash
# bash
az storage account network-rule remove \
    --account-name <acct> --resource-group <rg> \
    --ip-address <one-of-the-added-ranges>
```

You'll have to remove each prefix individually. The connector range is
typically 5-15 CIDRs, so that's manageable.

## RBAC required

The identity running `lat` needs Contributor on the **target resource**
(not the LA):

| Target | Required role |
| --- | --- |
| Storage account | Storage Account Contributor (or Contributor) |
| Key Vault | Key Vault Contributor (or Contributor) |
| Event Hub namespace | Contributor |

`Reader` on the subscription is also implicitly used to query the service
tag.

## Common pitfalls

| Pitfall | Mitigation |
| --- | --- |
| Connector range changes over time | Re-run this playbook periodically (Microsoft publishes updates ~weekly) |
| Customer's own VNet IPs get overwritten | They won't — the command appends, doesn't replace; but verify with `--dry-run` |
| Target resource has private endpoint | IP whitelisting is irrelevant; the connector traffic goes through the public endpoint regardless. Different problem entirely |
| User specifies wrong region | Service tag for the wrong region opens the wrong IPs; double-check |
| `AzureConnectors.<region>` tag returns 0 prefixes | Region name typo, or your principal lacks `Reader` on the subscription (needed for service-tag query) |

## Related .NET names

- `WhitelistConnectorIP` → `lat validate whitelist-connector-ip`
