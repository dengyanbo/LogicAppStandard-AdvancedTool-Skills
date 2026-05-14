"""Tests for `lat tools <name>` commands.

Expected outputs match the .NET `LogicAppAdvancedTool.exe Tools <Name>` CLI
verbatim (captured 2026-05-14).
"""
from __future__ import annotations

import base64

import pytest
from typer.testing import CliRunner

from lat.cli import app
from lat.commands.tools import _decode_run_id
from lat.storage.compression import compress

runner = CliRunner()


# ---------------------------------------------------------------------------
# Tools GeneratePrefix
# ---------------------------------------------------------------------------


def test_generate_prefix_la_only_matches_dotnet() -> None:
    result = runner.invoke(app, ["tools", "generate-prefix", "-la", "MyLogicApp"])
    assert result.exit_code == 0
    # .NET output line: "Logic App Prefix: 9584982b3a036bb"
    assert "Logic App Prefix: 9584982b3a036bb" in result.stdout
    # No workflow output when wf not supplied
    assert "Workflow Prefix" not in result.stdout
    assert "Combined prefix" not in result.stdout


def test_generate_prefix_with_workflow_matches_dotnet() -> None:
    result = runner.invoke(
        app,
        [
            "tools", "generate-prefix",
            "-la", "test-la-1",
            "-wf", "11111111-1111-1111-1111-111111111111",
        ],
    )
    assert result.exit_code == 0
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines == [
        "Logic App Prefix: 25b536ddefd5aaa",
        "Workflow Prefix: f64208cfbb7a724",
        "Combined prefix: 25b536ddefd5aaaf64208cfbb7a724",
    ]


def test_generate_prefix_does_not_lowercase_input() -> None:
    """Per Tools/GeneratePrefix.cs, input is hashed as-is."""
    upper = runner.invoke(app, ["tools", "generate-prefix", "-la", "MyLogicApp"])
    lower = runner.invoke(app, ["tools", "generate-prefix", "-la", "mylogicapp"])
    # These should differ since the tool does NOT lowercase
    assert "9584982b3a036bb" in upper.stdout
    assert "3fa3e8f6cecdc74" in lower.stdout
    assert upper.stdout != lower.stdout


def test_generate_prefix_requires_la() -> None:
    result = runner.invoke(app, ["tools", "generate-prefix"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Tools RunIDToDateTime
# ---------------------------------------------------------------------------


RUNID_VECTORS = [
    ("08584737551867954143243946780CU57", "2024-10-02T06:48:18Z"),
    ("08584000000000000000000000000CU01", "2027-02-02T22:21:25Z"),
    ("08585000000000000000000000000CU99", "2023-12-03T12:34:45Z"),
]


@pytest.mark.parametrize("run_id,expected_dt", RUNID_VECTORS)
def test_runid_to_datetime_matches_dotnet(run_id: str, expected_dt: str) -> None:
    result = runner.invoke(app, ["tools", "runid-to-datetime", "-id", run_id])
    assert result.exit_code == 0
    assert f"Datetime of RunID {run_id} is {expected_dt}" in result.stdout


def test_runid_decode_returns_utc_datetime() -> None:
    """The decoded datetime must be tz-aware UTC."""
    dt = _decode_run_id("08584737551867954143243946780CU57")
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 0
    assert (dt.year, dt.month, dt.day) == (2024, 10, 2)


def test_runid_to_datetime_rejects_short_input() -> None:
    result = runner.invoke(app, ["tools", "runid-to-datetime", "-id", "shortid"])
    assert result.exit_code != 0


def test_runid_to_datetime_rejects_non_digit_prefix() -> None:
    result = runner.invoke(
        app, ["tools", "runid-to-datetime", "-id", "abcdefghij1234567890CU01"]
    )
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Tools DecodeZSTD
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    ['{"hello":"world"}', "simple", "日本語", "a" * 200],
)
def test_decode_zstd_round_trip(payload: str) -> None:
    b64 = base64.b64encode(compress(payload)).decode("ascii")
    result = runner.invoke(app, ["tools", "decode-zstd", "-c", b64])
    assert result.exit_code == 0
    # Output format: blank line, "Decoded content:", payload
    assert "Decoded content:" in result.stdout
    assert payload in result.stdout


def test_decode_zstd_rejects_invalid_base64() -> None:
    result = runner.invoke(app, ["tools", "decode-zstd", "-c", "this!!!is@@@invalid***"])
    assert result.exit_code != 0


def test_decode_zstd_output_header_matches_dotnet() -> None:
    """The .NET tool prints '\\r\\nDecoded content:\\r\\n<payload>'. We use \\n."""
    b64 = base64.b64encode(compress("x")).decode("ascii")
    result = runner.invoke(app, ["tools", "decode-zstd", "-c", b64])
    # Expect a blank line then 'Decoded content:' then payload
    lines = result.stdout.splitlines()
    assert "" in lines  # blank line before header
    assert "Decoded content:" in lines
    decoded_idx = lines.index("Decoded content:")
    assert lines[decoded_idx + 1] == "x"
