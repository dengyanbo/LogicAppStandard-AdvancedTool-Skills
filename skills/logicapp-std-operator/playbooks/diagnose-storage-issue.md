# Playbook: Diagnose storage / connectivity issues

## Trigger conditions

- "My Logic App can't reach its storage"
- "DNS resolves but auth fails", "auth works but TCP fails"
- "I get `AuthorizationFailure` / `not authorized by network security perimeter`"
- "Service Provider X can't connect"
- "Connection times out"
- Classic .NET names: `ValidateStorageConnectivity`, `ValidateSPConnectivity`,
  `EndpointValidation`

## Diagnose: the three-layer checklist

There are exactly three layers that can fail. Walk them in order:

### Layer 1 — storage service endpoints

```powershell
# PowerShell — covers Blob, Queue, Table, File for the LA's main storage
lat validate storage-connectivity --skip-pe-check
```

```bash
# bash
lat validate storage-connectivity --skip-pe-check
```

Output is a table per service with DNS / TCP / Auth columns. Diagnose by
where the first column flips to `Failed`:

| First failure column | Likely cause | Where to look |
| --- | --- | --- |
| `DNS Resolution: Failed` | Wrong account name; DNS firewall; ASE with custom DNS misrouted | Confirm `AzureWebJobsStorage__accountName` value; from inside Kudu try `nslookup <acct>.table.core.windows.net` |
| `TCP Conn: Failed` (DNS Succeeded) | NSP / classic firewall / private endpoint blocking | See [`../references/nsp-troubleshooting.md`](../references/nsp-troubleshooting.md) |
| `Authentication: Failed` (TCP Succeeded) | RBAC missing in AAD mode, or wrong account key | See [`../references/aad-vs-connstring.md`](../references/aad-vs-connstring.md) §RBAC |
| `Is PE: Yes` while DNS=Failed | The endpoint resolves to a private IP but the host can't reach the PE subnet | Run from inside the VNet; or pop a Bastion box |

Drop `--skip-pe-check` to also classify whether each endpoint is private
vs. public (requires Reader on the subscription).

### Layer 2 — service-provider endpoints (declared in connections.json)

```powershell
lat validate sp-connectivity
```

This walks every Service Provider entry in `<wwwroot>\connections.json` and
DNS-resolves + TCP-pings the endpoint port. Output table is per SP.

Causes when a row fails:
- The endpoint host is unreachable from inside the LA's network
- The SP's port (often non-443, e.g. SFTP 22, AMQP 5671) is blocked by an
  egress firewall
- The connection has stale endpoint info that no longer points anywhere

### Layer 3 — arbitrary HTTP(S) endpoints

When a workflow contains an HTTP action that fails:

```powershell
lat validate endpoint -e https://target.example.com
```

Checks DNS + TCP/443 + SSL handshake. Useful for "does this URL even work
from inside the LA host".

## Diagnose: special case — hostruntime / Kudu unreachable

If `lat validate workflows` fails with a network error rather than a
validation error, the LA's hostruntime endpoint is not reachable. Check:

```powershell
lat validate endpoint -e "https://<LA>.azurewebsites.net"
```

This is the same endpoint `lat` uses for hostruntime calls.

## Common error → fix mapping

| Error message | Layer | Fix |
| --- | --- | --- |
| `Name or service not known` / `getaddrinfo failed` | 1 (DNS) | Wrong account name in `AzureWebJobsStorage__accountName`; or DNS firewall |
| `connection timed out` | 1 (TCP) | NSP / firewall; see [`../references/nsp-troubleshooting.md`](../references/nsp-troubleshooting.md) |
| `not authorized by network security perimeter` | 1 (Auth, by NSP) | Same as above; user identity needs an inbound IP rule (RBAC alone is insufficient) |
| `AuthorizationFailure` / `AuthenticationRequired` (403, not NSP) | 1 (Auth, by RBAC) | Grant Storage Table/Blob/Queue Data Contributor on the storage account |
| `Server selected protocol version TLS10 is not accepted` | 1 (TCP) | Storage account refuses TLS 1.0/1.1; your client must support 1.2 — modern Python/SDK do; check OS-level overrides |
| `ChainedTokenCredentialError` | 1 (Auth, no cred) | `az login`; or set ARM_* SP env vars |
| `Service Provider 'X' validation failed: TCP failed` | 2 | Network from LA to that SP is blocked; check egress NSG / firewall |
| `Service Provider 'X' validation failed: DNS failed` | 2 | Endpoint host doesn't resolve; check the connection's parameters |
| `Failed to validate workflow 'X': 400 ...` | hostruntime | Designer-side problem in the workflow.json itself; share the error with the user |
| `Failed to validate workflow 'X': 503 / network error` | hostruntime | LA site is down / scaling; wait + retry, or `lat tools restart` |

## Recommended diagnostic order for an opaque "my LA is broken"

```powershell
# 1. Can I even reach the LA's storage?
lat validate storage-connectivity --skip-pe-check

# 2. Are the service-provider connections healthy?
lat validate sp-connectivity

# 3. Is every workflow definition valid at runtime?
lat validate workflows

# 4. Anything in the host logs from the last hour?
lat site filter-host-logs

# 5. What does the recent failure landscape look like?
lat runs retrieve-failures-by-date -wf <suspect> -d (Get-Date).ToString("yyyyMMdd")
```

Stop at the first step that surfaces an obvious root cause and pivot to the
matching playbook.

## When you've fixed something

After remediation, re-run the failing layer's check. Don't declare victory
based on "I changed X, retry your workflow" — explicitly re-validate.

## Related .NET names

- `ValidateStorageConnectivity` → Layer 1
- `ValidateSPConnectivity` → Layer 2
- `EndpointValidation` → Layer 3
- `ValidateWorkflows` → hostruntime sanity
