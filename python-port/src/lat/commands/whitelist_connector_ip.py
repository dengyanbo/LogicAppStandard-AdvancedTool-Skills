"""`WhitelistConnectorIP` — add Azure Connector regional IPs to a resource's firewall.

Mirrors `Operations/WhitelistConnectorIP.cs`. Looks up the region-specific
`AzureConnectors.<region>` service tag, then PUTs the resource with the
extra IP rules. Supports the same three providers the .NET tool ships:
Microsoft.Storage, Microsoft.KeyVault, Microsoft.EventHub.

The target resource is fetched and updated via direct ARM HTTP (each
resource type has its own SDK, but they all share the same JSON shape
once you know the API version and `ipRules` rule path).

Service-tag lookup uses `azure-mgmt-network.NetworkManagementClient.service_tags`
instead of a hand-rolled HTTP call.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx
import typer
from azure.mgmt.network import NetworkManagementClient
from rich.console import Console

from ..auth import DEFAULT_AUDIENCE, credential, retrieve_token
from ..settings import settings

console = Console()


@dataclass(frozen=True)
class _ProviderConfig:
    """ARM call parameters per resource provider, from Resources/RegisteredProvider.json."""

    api_version: str
    url_parameter: str = ""
    mask_name: str = ""  # value key under each IP rule (Storage/KV: "value"; EH: "ipMask")
    rule_path: tuple[str, ...] = ("properties", "networkAcls")


_SUPPORTED_PROVIDERS: dict[str, _ProviderConfig] = {
    "Microsoft.KeyVault": _ProviderConfig(
        api_version="2023-02-01",
        rule_path=("properties", "networkAcls"),
    ),
    "Microsoft.Storage": _ProviderConfig(
        api_version="2023-01-01",
        rule_path=("properties", "networkAcls"),
    ),
    "Microsoft.EventHub": _ProviderConfig(
        api_version="2023-01-01-preview",
        url_parameter="/networkrulesets/default",
        mask_name="ipMask",
        rule_path=("properties",),
    ),
}


def _parse_resource_id(resource_id: str) -> dict[str, str]:
    """Split an ARM resource ID into a key/value dict by alternating segments."""
    parts = resource_id.strip("/").split("/")
    if len(parts) % 2 != 0:
        raise typer.BadParameter(
            f"Resource ID has odd segment count, cannot parse: {resource_id!r}"
        )
    return dict(zip(parts[0::2], parts[1::2], strict=True))


def _select(node: dict[str, Any], path: tuple[str, ...]) -> Any:
    cur: Any = node
    for seg in path:
        if not isinstance(cur, dict) or seg not in cur:
            return None
        cur = cur[seg]
    return cur


def _ensure_path(node: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any]:
    cur = node
    for seg in path:
        if not isinstance(cur.get(seg), dict):
            cur[seg] = {}
        cur = cur[seg]
    return cur


def _get_ip_value(rule: dict[str, Any], mask_name: str) -> str:
    """Extract the IP string from a rule object, regardless of key spelling."""
    key = mask_name or "value"
    return str(rule.get(key) or rule.get("value") or "")


def _new_ip_rule(ip: str, mask_name: str) -> dict[str, str]:
    return {(mask_name or "value"): ip}


def _network_client() -> NetworkManagementClient:
    sub = settings.subscription_id
    if not sub:
        raise typer.BadParameter(
            "WEBSITE_OWNER_NAME (-> subscription_id) is required to query service tags."
        )
    return NetworkManagementClient(credential(), sub)


def _connector_ipv4_prefixes(region: str) -> list[str]:
    """Look up the AzureConnectors.<region> service tag and return IPv4 prefixes."""
    tag_name = f"AzureConnectors.{region}"
    tags = _network_client().service_tags.list(region.lower())
    for value in tags.values or []:
        if value.name == tag_name:
            prefixes = list(value.properties.address_prefixes or [])
            return [p for p in prefixes if "." in p]
    raise typer.BadParameter(
        f"Service tag {tag_name!r} not found. Check region spelling or MI Reader "
        "permission on the subscription."
    )


def _arm_request(method: str, url: str, *, body: dict | None = None) -> httpx.Response:
    token = retrieve_token(DEFAULT_AUDIENCE)
    headers = {"Authorization": f"Bearer {token.access_token}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    resp = httpx.request(
        method,
        url,
        headers=headers,
        content=json.dumps(body) if body is not None else None,
        timeout=60.0,
    )
    if not resp.is_success:
        raise RuntimeError(f"{method} {url} failed ({resp.status_code}): {resp.text}")
    return resp


def whitelist_connector_ip(
    resource_id: str = typer.Option(
        ..., "-id", "--resource-id",
        help=(
            "Full ARM ID of the target resource, e.g. "
            "/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/<sa>"
        ),
    ),
    region: str = typer.Option(
        None, "--region",
        help=f"Region for the AzureConnectors service tag. Defaults to {settings.region}.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Print the IPs that would be added but do not PUT the resource.",
    ),
) -> None:
    """Append region's Azure Connector IPs to a Storage / KV / EventHub firewall."""
    target_region = region or settings.region
    if not target_region:
        raise typer.BadParameter(
            "Region not set (pass --region or set REGION_NAME env var)."
        )
    target_region = target_region.replace(" ", "")

    info = _parse_resource_id(resource_id)
    provider_key = info.get("providers")
    if provider_key not in _SUPPORTED_PROVIDERS:
        raise typer.BadParameter(
            f"The provided resource provider: {provider_key!r} is not supported, "
            "following services are supported:\n"
            + "\n".join(_SUPPORTED_PROVIDERS)
        )
    config = _SUPPORTED_PROVIDERS[provider_key]

    # GET current resource
    base_url = f"https://management.azure.com{resource_id}{config.url_parameter}"
    resource_url = f"{base_url}?api-version={config.api_version}"
    typer.echo(f"Fetching resource {resource_id}")
    payload = _arm_request("GET", resource_url).json()

    # Make sure the rule_path is materialized — if firewall is disabled, the
    # networkAcls (or properties for EH) block won't exist yet.
    rule_node = _select(payload, config.rule_path)
    if rule_node is None:
        rule_node = _ensure_path(payload, config.rule_path)
    if not isinstance(rule_node, dict):
        raise RuntimeError(f"Unexpected shape at {config.rule_path}: {rule_node!r}")
    rule_node.setdefault("ipRules", [])

    existing_rules = list(rule_node["ipRules"])
    existing_ips = {
        _get_ip_value(r, config.mask_name).replace("/32", "") for r in existing_rules
    }

    typer.echo(
        f"Resource found in Azure, retrieving Azure Connector IP range in {target_region}"
    )
    connector_ips = [ip.replace("/32", "") for ip in _connector_ipv4_prefixes(target_region)]
    missing = [ip for ip in connector_ips if ip not in existing_ips]

    if not missing:
        typer.echo(
            f"Detected {len(connector_ips)} IP range from Azure document, "
            "all of them are in the firewall rule, no need to update."
        )
        return

    typer.echo(
        f"Detected {len(connector_ips)} IP range from Azure document, "
        f"{len(missing)} records(s) not found in firewall, updating firewall records."
    )

    if dry_run:
        for ip in missing:
            typer.echo(f"  would add: {ip}")
        return

    rule_node["ipRules"] = existing_rules + [_new_ip_rule(ip, config.mask_name) for ip in missing]
    rule_node["defaultAction"] = "Deny"
    payload.setdefault("properties", {})["publicNetworkAccess"] = "Enabled"

    _arm_request("PUT", resource_url, body=payload)
    typer.echo("Firewall updated, please refresh (press F5) the whole page.")


def register(validate_app: typer.Typer) -> None:
    validate_app.command(
        "whitelist-connector-ip",
        help="Add Azure Connector IP range to a Storage / KV / EventHub firewall.",
    )(whitelist_connector_ip)
