"""Tests for `lat validate whitelist-connector-ip`.

Mocks both the network management SDK (service tags) and the direct ARM
HTTP layer used for resource GET/PUT.
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from typer.testing import CliRunner

from lat.cli import app
from lat.commands import whitelist_connector_ip as mod
from lat.commands.whitelist_connector_ip import (
    _ensure_path,
    _parse_resource_id,
    _select,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_parse_resource_id_storage() -> None:
    rid = "/subscriptions/abc/resourceGroups/rg1/providers/Microsoft.Storage/storageAccounts/sa1"
    parsed = _parse_resource_id(rid)
    assert parsed == {
        "subscriptions": "abc",
        "resourceGroups": "rg1",
        "providers": "Microsoft.Storage",
        "storageAccounts": "sa1",
    }


def test_parse_resource_id_rejects_odd_segments() -> None:
    with pytest.raises(Exception):
        _parse_resource_id("/subscriptions/abc/resourceGroups")


def test_select_walks_path() -> None:
    node = {"a": {"b": {"c": 42}}}
    assert _select(node, ("a", "b", "c")) == 42
    assert _select(node, ("a", "missing")) is None


def test_ensure_path_creates_missing_branches() -> None:
    node: dict = {}
    target = _ensure_path(node, ("a", "b", "c"))
    assert isinstance(target, dict)
    assert node == {"a": {"b": {"c": {}}}}


# ---------------------------------------------------------------------------
# Mocking helpers
# ---------------------------------------------------------------------------


def _service_tag_value(name: str, prefixes: list[str]) -> MagicMock:
    """Build a mock ServiceTagInformation that mirrors azure-mgmt-network shape."""
    inner = MagicMock()
    inner.name = name
    inner.properties.address_prefixes = prefixes
    return inner


@pytest.fixture()
def fake_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEBSITE_OWNER_NAME", "subABC+region")
    monkeypatch.setenv("REGION_NAME", "East US")


@pytest.fixture()
def fake_arm(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace _arm_request with a mock so GET/PUT calls are recorded.

    The 'get_response' key controls what the first call (assumed GET) returns;
    'put_calls' collects the body of any subsequent PUTs.
    """
    state: dict[str, Any] = {"get_response": {}, "put_calls": []}

    def fake_request(method: str, url: str, *, body: dict | None = None) -> httpx.Response:
        if method == "GET":
            return httpx.Response(200, json=state["get_response"], request=httpx.Request(method, url))
        if method == "PUT":
            state["put_calls"].append({"url": url, "body": body})
            return httpx.Response(200, json={}, request=httpx.Request(method, url))
        raise RuntimeError(f"Unexpected method {method}")

    monkeypatch.setattr(mod, "_arm_request", fake_request)
    return state


@pytest.fixture()
def fake_service_tags(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    """Replace _network_client().service_tags.list with a stub.

    Returns a dict keyed by service tag name -> IPv4 prefixes.
    """
    catalog: dict[str, list[str]] = {
        "AzureConnectors.EastUS": ["20.1.0.0/24", "20.2.0.0/24", "fe80::/16"],
        "AzureConnectors.WestUS": ["40.1.0.0/24"],
    }

    class FakeList:
        def __init__(self, values: list[MagicMock]) -> None:
            self.values = values

    def fake_list(location: str) -> FakeList:
        # service_tags.list normalises to lowercase; match keys.
        return FakeList(
            [_service_tag_value(name, prefixes) for name, prefixes in catalog.items()]
        )

    client = MagicMock()
    client.service_tags.list = fake_list
    monkeypatch.setattr(mod, "_network_client", lambda: client)
    return catalog


# ---------------------------------------------------------------------------
# End-to-end via CLI
# ---------------------------------------------------------------------------


def _resource_id(provider: str = "Microsoft.Storage") -> str:
    return f"/subscriptions/sub/resourceGroups/rg/providers/{provider}/storageAccounts/sa"


def test_whitelist_storage_adds_missing_ips(
    fake_settings: None, fake_arm: dict, fake_service_tags: dict
) -> None:
    fake_arm["get_response"] = {
        "properties": {
            "networkAcls": {
                "ipRules": [{"value": "20.1.0.0/24"}],  # already present
                "defaultAction": "Allow",
            }
        }
    }
    result = runner.invoke(
        app, ["validate", "whitelist-connector-ip", "-id", _resource_id()]
    )
    assert result.exit_code == 0, result.stdout
    # One PUT issued
    assert len(fake_arm["put_calls"]) == 1
    body = fake_arm["put_calls"][0]["body"]
    rules = body["properties"]["networkAcls"]["ipRules"]
    # IPv4 only from the service tag (fe80::/16 stripped)
    values = sorted(r["value"] for r in rules)
    assert "20.1.0.0/24" in values
    assert "20.2.0.0/24" in values
    assert all(":" not in v for v in values)
    # defaultAction flipped to Deny + publicNetworkAccess Enabled
    assert body["properties"]["networkAcls"]["defaultAction"] == "Deny"
    assert body["properties"]["publicNetworkAccess"] == "Enabled"


def test_whitelist_keyvault_uses_correct_api_version(
    fake_settings: None, fake_arm: dict, fake_service_tags: dict
) -> None:
    fake_arm["get_response"] = {"properties": {}}
    result = runner.invoke(
        app, ["validate", "whitelist-connector-ip", "-id", _resource_id("Microsoft.KeyVault")]
    )
    assert result.exit_code == 0, result.stdout
    # PUT URL must carry the KV api version
    put = fake_arm["put_calls"][0]
    assert "api-version=2023-02-01" in put["url"]


def test_whitelist_eventhub_uses_ipmask_key_and_url_param(
    fake_settings: None, fake_arm: dict, fake_service_tags: dict
) -> None:
    fake_arm["get_response"] = {
        "properties": {"ipRules": [{"ipMask": "20.1.0.0/24"}]}
    }
    result = runner.invoke(
        app, ["validate", "whitelist-connector-ip", "-id", _resource_id("Microsoft.EventHub")]
    )
    assert result.exit_code == 0, result.stdout
    put = fake_arm["put_calls"][0]
    # EH uses ipMask key, not value
    rules = put["body"]["properties"]["ipRules"]
    assert any("ipMask" in r for r in rules)
    # EH uses /networkrulesets/default suffix
    assert "/networkrulesets/default" in put["url"]


def test_whitelist_no_missing_ips_skips_put(
    fake_settings: None, fake_arm: dict, fake_service_tags: dict
) -> None:
    fake_arm["get_response"] = {
        "properties": {
            "networkAcls": {
                "ipRules": [
                    {"value": "20.1.0.0/24"},
                    {"value": "20.2.0.0/24"},
                ]
            }
        }
    }
    result = runner.invoke(
        app, ["validate", "whitelist-connector-ip", "-id", _resource_id()]
    )
    assert result.exit_code == 0
    assert "no need to update" in result.stdout
    assert fake_arm["put_calls"] == []


def test_whitelist_dry_run_skips_put(
    fake_settings: None, fake_arm: dict, fake_service_tags: dict
) -> None:
    fake_arm["get_response"] = {"properties": {"networkAcls": {"ipRules": []}}}
    result = runner.invoke(
        app,
        ["validate", "whitelist-connector-ip", "-id", _resource_id(), "--dry-run"],
    )
    assert result.exit_code == 0
    assert "would add: 20.1.0.0/24" in result.stdout
    assert fake_arm["put_calls"] == []


def test_whitelist_handles_disabled_firewall(
    fake_settings: None, fake_arm: dict, fake_service_tags: dict
) -> None:
    """When networkAcls is absent (firewall disabled), the command builds it from scratch."""
    fake_arm["get_response"] = {"properties": {}}
    result = runner.invoke(
        app, ["validate", "whitelist-connector-ip", "-id", _resource_id()]
    )
    assert result.exit_code == 0, result.stdout
    body = fake_arm["put_calls"][0]["body"]
    assert "networkAcls" in body["properties"]
    assert len(body["properties"]["networkAcls"]["ipRules"]) == 2


def test_whitelist_rejects_unsupported_provider(
    fake_settings: None, fake_arm: dict, fake_service_tags: dict
) -> None:
    rid = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm"
    result = runner.invoke(app, ["validate", "whitelist-connector-ip", "-id", rid])
    assert result.exit_code != 0
    # No PUT was issued
    assert fake_arm["put_calls"] == []


def test_whitelist_region_override(
    fake_settings: None, fake_arm: dict, fake_service_tags: dict
) -> None:
    """--region overrides REGION_NAME."""
    fake_arm["get_response"] = {"properties": {"networkAcls": {"ipRules": []}}}
    result = runner.invoke(
        app,
        [
            "validate", "whitelist-connector-ip",
            "-id", _resource_id(),
            "--region", "West US",
        ],
    )
    assert result.exit_code == 0, result.stdout
    body = fake_arm["put_calls"][0]["body"]
    values = sorted(r["value"] for r in body["properties"]["networkAcls"]["ipRules"])
    assert values == ["40.1.0.0/24"]
