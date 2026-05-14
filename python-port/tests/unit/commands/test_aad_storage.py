"""Tests for AAD (Entra ID) storage authentication path.

Verifies that when AzureWebJobsStorage is not set as a connection string,
the storage clients are constructed with endpoint + TokenCredential. This
unlocks parity with modern Logic App Standard instances configured with
managed identity for storage.
"""
from __future__ import annotations

from typer.testing import CliRunner

import pytest

from lat import auth, settings as _settings
from lat.cli import app
from lat.storage import blobs, tables

runner = CliRunner()


# ---------------------------------------------------------------------------
# settings.py auto-detection
# ---------------------------------------------------------------------------


def test_uses_aad_storage_with_account_name(lat_env_aad) -> None:
    assert _settings.settings.uses_aad_storage is True
    assert _settings.settings.storage_account_name == "teststorage"
    assert _settings.settings.storage_endpoint_suffix == "core.windows.net"


def test_uses_aad_storage_when_credential_explicitly_set(monkeypatch) -> None:
    monkeypatch.delenv("AzureWebJobsStorage", raising=False)
    monkeypatch.setenv("AzureWebJobsStorage__accountName", "abc")
    monkeypatch.setenv("AzureWebJobsStorage__credential", "managedidentity")
    assert _settings.settings.uses_aad_storage is True


def test_conn_string_with_key_overrides_aad(monkeypatch) -> None:
    monkeypatch.setenv(
        "AzureWebJobsStorage",
        "DefaultEndpointsProtocol=https;AccountName=teststorage;"
        "AccountKey=Zm9vYmFy;EndpointSuffix=core.windows.net",
    )
    monkeypatch.setenv("AzureWebJobsStorage__accountName", "ignored")
    assert _settings.settings.uses_aad_storage is False


def test_account_resolved_from_service_uri(monkeypatch) -> None:
    monkeypatch.delenv("AzureWebJobsStorage", raising=False)
    monkeypatch.delenv("AzureWebJobsStorage__accountName", raising=False)
    monkeypatch.setenv(
        "AzureWebJobsStorage__tableServiceUri",
        "https://myaccount.table.core.usgovcloudapi.net",
    )
    assert _settings.settings.storage_account_name == "myaccount"
    assert _settings.settings.storage_endpoint_suffix == "core.usgovcloudapi.net"
    assert (
        _settings.settings.storage_endpoint("table")
        == "https://myaccount.table.core.usgovcloudapi.net"
    )


def test_storage_endpoint_builds_url(lat_env_aad) -> None:
    assert (
        _settings.settings.storage_endpoint("blob")
        == "https://teststorage.blob.core.windows.net"
    )
    assert (
        _settings.settings.storage_endpoint("table")
        == "https://teststorage.table.core.windows.net"
    )
    assert (
        _settings.settings.storage_endpoint("queue")
        == "https://teststorage.queue.core.windows.net"
    )


# ---------------------------------------------------------------------------
# storage clients route to credential-based construction
# ---------------------------------------------------------------------------


def test_table_service_client_uses_credential_in_aad_mode(
    monkeypatch, lat_env_aad
) -> None:
    """In AAD mode, TableServiceClient is constructed with endpoint + credential."""
    auth.reset_credential()
    captured: dict = {}

    class _FakeCred:
        def get_token(self, scope, **_):  # pragma: no cover
            raise RuntimeError("token call not expected in this test")

    monkeypatch.setattr(auth, "_build_credential", lambda: _FakeCred())

    from azure.data.tables import TableServiceClient

    original_init = TableServiceClient.__init__

    def fake_init(self, endpoint=None, credential=None, **kwargs):
        captured["endpoint"] = endpoint
        captured["credential"] = credential

    monkeypatch.setattr(TableServiceClient, "__init__", fake_init)
    try:
        tables._service_client()
    finally:
        monkeypatch.setattr(TableServiceClient, "__init__", original_init)

    assert captured["endpoint"] == "https://teststorage.table.core.windows.net"
    assert isinstance(captured["credential"], _FakeCred)


def test_blob_service_client_uses_credential_in_aad_mode(
    monkeypatch, lat_env_aad
) -> None:
    """In AAD mode, BlobServiceClient is constructed with account_url + credential."""
    auth.reset_credential()

    class _FakeCred:
        def get_token(self, scope, **_):  # pragma: no cover
            raise RuntimeError("token call not expected in this test")

    monkeypatch.setattr(auth, "_build_credential", lambda: _FakeCred())

    from azure.storage.blob import BlobServiceClient

    captured: dict = {}
    original_init = BlobServiceClient.__init__

    def fake_init(self, account_url=None, credential=None, **kwargs):
        captured["account_url"] = account_url
        captured["credential"] = credential

    monkeypatch.setattr(BlobServiceClient, "__init__", fake_init)
    try:
        blobs.service_client()
    finally:
        monkeypatch.setattr(BlobServiceClient, "__init__", original_init)

    assert captured["account_url"] == "https://teststorage.blob.core.windows.net"
    assert isinstance(captured["credential"], _FakeCred)


def test_conn_string_mode_still_uses_from_connection_string(
    monkeypatch, lat_env
) -> None:
    """Connection-string mode still routes through from_connection_string."""
    auth.reset_credential()

    from azure.data.tables import TableServiceClient

    captured: dict = {}
    original = TableServiceClient.from_connection_string

    @classmethod  # type: ignore[misc]
    def fake_from_cs(cls, conn_str, **kwargs):
        captured["conn_str"] = conn_str

    monkeypatch.setattr(TableServiceClient, "from_connection_string", fake_from_cs)
    try:
        tables._service_client()
    finally:
        monkeypatch.setattr(
            TableServiceClient, "from_connection_string", original
        )

    assert "AccountKey=Zm9vYmFy" in captured["conn_str"]


# ---------------------------------------------------------------------------
# validate storage-connectivity precondition
# ---------------------------------------------------------------------------


def test_validate_storage_connectivity_accepts_aad_mode(
    monkeypatch, lat_env_aad
) -> None:
    """When AAD env is set (no conn string), the precondition check passes.

    We stub the resolve/tcp_connect symbols imported into the command's
    own module namespace so the command short-circuits per-endpoint
    without hitting the network or the SDK.
    """
    from lat.commands import validate_storage_connectivity as cmd

    monkeypatch.setattr(cmd, "resolve", lambda _host: [])
    monkeypatch.setattr(cmd, "tcp_connect", lambda *a, **k: False)

    result = runner.invoke(
        app, ["validate", "storage-connectivity", "--skip-pe-check"]
    )
    # The relevant assertion: it does NOT short-circuit with the precondition
    # error from the conn-string-only check.
    assert "AzureWebJobsStorage is not set" not in result.output
    # All endpoints should be marked as DNS Failed but the run completed.
    assert "Failed" in result.output


def test_validate_storage_connectivity_rejects_when_nothing_set(
    monkeypatch,
) -> None:
    monkeypatch.delenv("AzureWebJobsStorage", raising=False)
    monkeypatch.delenv("AzureWebJobsStorage__accountName", raising=False)
    monkeypatch.delenv("AzureWebJobsStorage__tableServiceUri", raising=False)
    monkeypatch.delenv("AzureWebJobsStorage__blobServiceUri", raising=False)
    monkeypatch.delenv("AzureWebJobsStorage__queueServiceUri", raising=False)
    monkeypatch.delenv("AzureWebJobsStorage__credential", raising=False)

    result = runner.invoke(
        app, ["validate", "storage-connectivity", "--skip-pe-check"]
    )
    assert result.exit_code != 0
    assert "AzureWebJobsStorage is not set" in result.output
