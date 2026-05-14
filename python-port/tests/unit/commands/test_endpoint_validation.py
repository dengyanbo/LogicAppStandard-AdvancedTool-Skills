"""Tests for `lat validate endpoint`."""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from lat import network
from lat.cli import app
from lat.commands.endpoint_validation import _parse_endpoint

runner = CliRunner()


@pytest.fixture()
def stub_network(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    """Replace network probes with deterministic stubs.

    Returns the resolved-IPs dict so tests can override per-host behavior.
    """
    resolved: dict[str, list[str]] = {"example.com": ["93.184.216.34"]}

    def fake_resolve(host: str) -> list[str]:
        return resolved.get(host, [])

    def fake_tcp(ip: str, port: int, timeout: float = 1.0) -> bool:
        # Mock as "succeeded" for any IP we resolved.
        return any(ip in v for v in resolved.values())

    def fake_ssl(host: str, port: int = 443, timeout: float = 5.0) -> network.SslProbeResult:
        return network.SslProbeResult(ok=True)

    monkeypatch.setattr("lat.commands.endpoint_validation.resolve", fake_resolve)
    monkeypatch.setattr("lat.commands.endpoint_validation.tcp_connect", fake_tcp)
    monkeypatch.setattr("lat.commands.endpoint_validation.ssl_probe", fake_ssl)
    return resolved


# ---------------------------------------------------------------------------
# _parse_endpoint
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://example.com", ("https", "example.com", 443)),
        ("http://example.com", ("http", "example.com", 80)),
        ("example.com", ("https", "example.com", 443)),  # default to https
        ("https://example.com/", ("https", "example.com", 443)),
        ("https://example.com/api/v1", ("https", "example.com", 443)),
        ("http://example.com:8080", ("http", "example.com", 8080)),
        ("https://example.com:8443/path", ("https", "example.com", 8443)),
    ],
)
def test_parse_endpoint(raw: str, expected: tuple[str, str, int]) -> None:
    assert _parse_endpoint(raw) == expected


# ---------------------------------------------------------------------------
# CLI behavior
# ---------------------------------------------------------------------------


def test_https_endpoint_succeeds(stub_network: dict[str, list[str]]) -> None:
    result = runner.invoke(app, ["validate", "endpoint", "-url", "https://example.com"])
    assert result.exit_code == 0
    # Table prints each section. Verify at least one IP row.
    assert "93.184.216.34" in result.stdout
    assert "Succeeded" in result.stdout


def test_http_endpoint_skips_ssl(stub_network: dict[str, list[str]]) -> None:
    result = runner.invoke(app, ["validate", "endpoint", "-url", "http://example.com"])
    assert result.exit_code == 0
    assert "SSL certificate validation will be skipped" in result.stdout
    assert "Skipped" in result.stdout
    assert "93.184.216.34" in result.stdout


def test_dns_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """When DNS fails: one row with N/A IP and NotApplicable TCP/SSL."""
    monkeypatch.setattr("lat.commands.endpoint_validation.resolve", lambda host: [])
    # Make sure TCP/SSL are not called (they would fail without network)
    monkeypatch.setattr(
        "lat.commands.endpoint_validation.tcp_connect",
        lambda *a, **k: pytest.fail("tcp_connect should not be called on DNS failure"),
    )
    monkeypatch.setattr(
        "lat.commands.endpoint_validation.ssl_probe",
        lambda *a, **k: network.SslProbeResult(ok=False),
    )
    result = runner.invoke(app, ["validate", "endpoint", "-url", "https://invalid.example"])
    assert result.exit_code == 0
    assert "Failed" in result.stdout
    assert "N/A" in result.stdout
    assert "NotApplicable" in result.stdout


def test_invalid_url_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # An empty host should be caught by _parse_endpoint
    result = runner.invoke(app, ["validate", "endpoint", "-url", "https:///"])
    assert result.exit_code != 0
