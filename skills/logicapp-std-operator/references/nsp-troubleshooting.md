# Reference: Network Security Perimeter (NSP) troubleshooting

## The symptom

```
HttpResponseError: This request is not authorized by network security perimeter
to perform this operation.
RequestId: ...
ErrorCode: AuthorizationFailure
```

This is **not** an RBAC problem. The storage account has `publicNetworkAccess =
"SecuredByPerimeter"`, which means: "Even though my RBAC says you're allowed,
the network perimeter says you can't reach me from where you are."

Storage account-level firewall (the older "Selected networks" model) produces
similar symptoms but a different error message. The investigation is the
same.

## Step 1: Confirm it's NSP, not classic firewall

```powershell
$acct = "mystorage"; $rg = "my-rg"
az storage account show --name $acct --resource-group $rg `
  --query "{publicAccess:publicNetworkAccess, networkAcls:networkAcls.defaultAction}" -o json
```

```bash
acct=mystorage; rg=my-rg
az storage account show --name "$acct" --resource-group "$rg" \
  --query "{publicAccess:publicNetworkAccess, networkAcls:networkAcls.defaultAction}" -o json
```

| Output | Meaning |
| --- | --- |
| `publicAccess: "SecuredByPerimeter"` | NSP |
| `publicAccess: "Enabled"` + `networkAcls: "Deny"` | Classic firewall (selected networks) |
| `publicAccess: "Disabled"` | Private endpoints only |
| `publicAccess: "Enabled"` + `networkAcls: "Allow"` | Open; the error is something else |

## Step 2: Find the NSP

```powershell
az network perimeter list --query "[].{name:name, rg:resourceGroup}" -o table
```

```bash
az network perimeter list --query "[].{name:name, rg:resourceGroup}" -o table
```

There may be one or several. Find the one your storage account is associated
with:

```powershell
az network perimeter association list `
  --perimeter-name <nsp> --resource-group <nsp-rg> `
  --query "[?contains(properties.privateLinkResource.id, '<your-storage-acct>')]" -o json
```

## Step 3: Find the profile binding the storage account

The association's `properties.profile.id` points at one profile in the NSP.
That profile holds the inbound access rules that gate traffic to the account.

```powershell
az network perimeter profile access-rule list `
  --perimeter-name <nsp> --resource-group <nsp-rg> `
  --profile-name <profile> `
  --query "[?direction=='Inbound'].{name:name, prefixes:properties.addressPrefixes, subs:properties.subscriptions}" -o json
```

## Step 4: Find your current public IP

```powershell
(Invoke-WebRequest -Uri "https://api.ipify.org" -UseBasicParsing).Content
```

```bash
curl -s https://api.ipify.org
```

If you're behind corporate NAT, this IP can change between requests — adding
a single `/32` will likely stop working in minutes. Prefer `/24` or wider for
the duration of the work.

## Step 5: Decide how to unblock

| Option | When to use |
| --- | --- |
| Add your IP / CIDR to the NSP inbound access rule | You're an admin on the NSP **and** working short-term |
| Run from a machine inside the allowed range (e.g. an Azure VM in the same VNet, a bastion) | The NSP is locked down by policy and you can't widen it |
| Add a subscription-based rule (`--subscriptions`) | Other Azure resources in your sub need access |
| Connect over Private Link / VPN | Long-term, the right answer for production |

### Adding a temporary IP rule (admin-only)

```powershell
az network perimeter profile access-rule create `
  --perimeter-name <nsp> --resource-group <nsp-rg> `
  --profile-name <profile> `
  --name "allow-<you>-temp" `
  --direction Inbound `
  --address-prefixes "<your-cidr>"
# Wait ~60s for propagation, then retry your lat command.
```

Remember to delete the rule when done:

```powershell
az network perimeter profile access-rule delete `
  --perimeter-name <nsp> --resource-group <nsp-rg> `
  --profile-name <profile> `
  --name "allow-<you>-temp" --yes
```

## Step 6: Common surprises

- **NAT pool**: Your `api.ipify.org` result can change between consecutive
  curls (we saw `104.43.2.94 → 104.43.2.90 → 104.43.2.91` in ~5 minutes
  during testing). Use a `/24` or wider, not `/32`.
- **NSP propagation**: Rule changes take 30–120 seconds to take effect. Wait
  before retrying.
- **`accessMode: Learning`** on the association does NOT mean "open" — the
  exact behavior depends on the resource type. For Storage, "Learning" still
  enforces deny on non-matching traffic but only logs (not blocks) on rules
  that would otherwise deny. If you're seeing AuthorizationFailure, the rule
  doesn't cover your IP regardless of mode.
- **Subscription-based rule** (`subscriptions: [{id: ...}]`) allows other
  *Azure resources* in that subscription, **not** user identities. User
  access still needs an IP-based rule.

## Step 7: Validate after the rule is in place

```powershell
lat validate storage-connectivity --skip-pe-check
```

All three (Blob, Queue, Table) should show DNS=Succeeded, TCP=Succeeded,
Authentication=Succeeded.
