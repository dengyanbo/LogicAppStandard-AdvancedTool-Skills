"""Tests for `lat tools get-mi-token` and `lat tools restart`.

These commands hit Azure SDK code; we mock the SDK layer (auth + arm).
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from lat import arm, auth
from lat.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Tools GetMIToken
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_token(monkeypatch: pytest.MonkeyPatch) -> auth.MIToken:
    tok = auth.MIToken(
        access_token="eyJ.fake.token",
        expires_on=1_900_000_000,
        resource="https://management.azure.com",
        client_id="00000000-0000-0000-0000-000000000000",
    )
    monkeypatch.setattr(auth, "retrieve_token", lambda audience=auth.DEFAULT_AUDIENCE: tok)
    monkeypatch.setattr("lat.commands.tools.retrieve_token", lambda audience=auth.DEFAULT_AUDIENCE: tok)
    return tok


def test_get_mi_token_default_audience(fake_token: auth.MIToken) -> None:
    result = runner.invoke(app, ["tools", "get-mi-token"])
    assert result.exit_code == 0, result.stdout
    parsed = json.loads(result.stdout)
    assert parsed["access_token"] == fake_token.access_token
    assert parsed["expires_on"] == fake_token.expires_on
    assert parsed["resource"] == fake_token.resource
    assert parsed["token_type"] == "Bearer"
    assert parsed["client_id"] == fake_token.client_id


def test_get_mi_token_custom_audience(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_retrieve(audience: str = auth.DEFAULT_AUDIENCE) -> auth.MIToken:
        captured["audience"] = audience
        return auth.MIToken(access_token="x", expires_on=1, resource=audience.rstrip("/"))

    monkeypatch.setattr("lat.commands.tools.retrieve_token", fake_retrieve)
    result = runner.invoke(
        app, ["tools", "get-mi-token", "-a", "https://storage.azure.com/"]
    )
    assert result.exit_code == 0
    assert captured["audience"] == "https://storage.azure.com/"
    parsed = json.loads(result.stdout)
    assert parsed["resource"] == "https://storage.azure.com"


# ---------------------------------------------------------------------------
# Tools Restart
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_arm(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Inject a mock WebSiteManagementClient via arm._set_web_client."""
    client = MagicMock()
    # Make sure no real settings are required (sub/rg/name)
    monkeypatch.setenv("WEBSITE_OWNER_NAME", "sub+region")
    monkeypatch.setenv("WEBSITE_RESOURCE_GROUP", "rg")
    monkeypatch.setenv("WEBSITE_SITE_NAME", "mylogicapp")
    arm._set_web_client(client)
    yield client
    arm._set_web_client(None)


def test_restart_with_yes(mock_arm: MagicMock) -> None:
    result = runner.invoke(app, ["tools", "restart", "--yes"])
    assert result.exit_code == 0, result.stdout
    mock_arm.web_apps.restart.assert_called_once_with("rg", "mylogicapp")
    assert "Restart request accepted." in result.stdout


def test_restart_confirms_before_calling(mock_arm: MagicMock) -> None:
    """No --yes: prompt aborts when user declines, SDK is not touched."""
    result = runner.invoke(app, ["tools", "restart"], input="n\n")
    assert result.exit_code != 0
    mock_arm.web_apps.restart.assert_not_called()


def test_restart_propagates_sdk_errors(mock_arm: MagicMock) -> None:
    mock_arm.web_apps.restart.side_effect = RuntimeError("ARM 403 Forbidden")
    result = runner.invoke(app, ["tools", "restart", "--yes"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# auth helpers
# ---------------------------------------------------------------------------


def test_audience_to_scope_default_audience() -> None:
    assert auth._audience_to_scope("https://management.azure.com") == "https://management.azure.com/.default"
    assert auth._audience_to_scope("https://management.azure.com/") == "https://management.azure.com/.default"
    assert auth._audience_to_scope("https://storage.azure.com/.default") == "https://storage.azure.com/.default"


def test_retrieve_token_uses_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    """retrieve_token must request the correct scope from azure.identity."""
    captured: dict[str, str] = {}

    class FakeAccessToken:
        token = "fake-jwt"
        expires_on = 1_900_000_000

    class FakeCredential:
        def get_token(self, scope: str) -> FakeAccessToken:  # noqa: D401
            captured["scope"] = scope
            return FakeAccessToken()

    monkeypatch.setattr(auth, "_credential", FakeCredential())
    token = auth.retrieve_token("https://storage.azure.com/")
    assert captured["scope"] == "https://storage.azure.com/.default"
    assert token.access_token == "fake-jwt"
    assert token.expires_on == 1_900_000_000
    assert token.resource == "https://storage.azure.com"


def test_reset_credential_clears_singleton() -> None:
    auth._credential = "something"  # type: ignore[assignment]
    auth.reset_credential()
    assert auth._credential is None
