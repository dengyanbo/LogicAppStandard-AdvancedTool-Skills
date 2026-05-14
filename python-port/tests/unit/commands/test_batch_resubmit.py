"""Tests for `lat runs batch-resubmit`.

Mocks `lat.arm.list_runs` and `lat.arm.resubmit_trigger_history` so the
command can be exercised entirely offline.
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from lat import arm
from lat.cli import app
from lat.commands import batch_resubmit as mod

runner = CliRunner()


def _run(name: str, trigger: str = "manual") -> dict[str, Any]:
    return {"name": name, "properties": {"trigger": {"name": trigger}}}


@pytest.fixture()
def stub_arm(monkeypatch: pytest.MonkeyPatch) -> dict[str, list]:
    """Replace arm.list_runs + arm.resubmit_trigger_history with deterministic stubs.

    Returns a dict with:
      * 'runs'  — list of run dicts (mutate to control what list_runs returns)
      * 'calls' — list of resubmit_trigger_history (workflow, trigger, run_id) tuples
      * 'fail_with' — list of (run_id, Exception) pairs to make resubmit raise
    """
    state: dict[str, Any] = {"runs": [], "calls": [], "fail_with": []}

    def fake_list(workflow: str, *, status: str, start_time: str, end_time: str) -> Iterator[dict]:
        yield from state["runs"]

    def fake_resubmit(workflow: str, trigger: str, run_id: str) -> None:
        state["calls"].append((workflow, trigger, run_id))
        for failing_id, err in state["fail_with"]:
            if failing_id == run_id:
                # Remove the failure entry so retry succeeds.
                state["fail_with"].remove((failing_id, err))
                raise err

    monkeypatch.setattr(arm, "list_runs", fake_list)
    monkeypatch.setattr(arm, "resubmit_trigger_history", fake_resubmit)
    return state


# ---------------------------------------------------------------------------
# Helper-level tests
# ---------------------------------------------------------------------------


def test_safe_timestamp_suffix_handles_iso_z() -> None:
    assert mod._safe_timestamp_suffix("2026-05-14T00:00:00Z") == "20260514000000"


def test_safe_timestamp_suffix_handles_naive_iso() -> None:
    assert mod._safe_timestamp_suffix("2026-05-14T12:34:56") == "20260514123456"


def test_safe_timestamp_suffix_handles_date_only() -> None:
    assert mod._safe_timestamp_suffix("2026-05-14") == "20260514000000"


def test_safe_timestamp_suffix_fallback_alnum() -> None:
    out = mod._safe_timestamp_suffix("notatimestamp")
    assert out == "notatimestamp"


def test_load_processed_missing_file(tmp_path: Path) -> None:
    assert mod._load_processed(tmp_path / "missing.log") == set()


def test_load_processed_skips_blank_lines(tmp_path: Path) -> None:
    log = tmp_path / "log.txt"
    log.write_text("abc\n\n  \ndef\n", encoding="utf-8")
    assert mod._load_processed(log) == {"abc", "def"}


def test_is_throttle_error_detects_429_substring() -> None:
    assert mod._is_throttle_error(RuntimeError("HTTP 429"))
    assert mod._is_throttle_error(RuntimeError("Server responded: Too Many Requests"))
    assert not mod._is_throttle_error(RuntimeError("HTTP 503 Service Unavailable"))


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


def test_batch_resubmit_no_runs_exits_cleanly(tmp_path: Path, stub_arm: dict) -> None:
    result = runner.invoke(
        app,
        [
            "runs", "batch-resubmit",
            "-wf", "wf1",
            "-st", "2026-05-14T00:00:00Z",
            "-et", "2026-05-15T00:00:00Z",
            "--yes",
            "--log-path", str(tmp_path / "log.txt"),
        ],
    )
    assert result.exit_code == 0
    assert "No failed run detected." in result.stdout
    assert stub_arm["calls"] == []


def test_batch_resubmit_resubmits_each_run(tmp_path: Path, stub_arm: dict) -> None:
    stub_arm["runs"] = [_run("run-1"), _run("run-2"), _run("run-3")]
    log = tmp_path / "log.txt"
    result = runner.invoke(
        app,
        [
            "runs", "batch-resubmit",
            "-wf", "wf1",
            "-st", "2026-05-14T00:00:00Z",
            "-et", "2026-05-15T00:00:00Z",
            "--yes",
            "--log-path", str(log),
        ],
    )
    assert result.exit_code == 0, result.stdout
    # Each run resubmitted exactly once
    submitted_ids = sorted(rid for _, _, rid in stub_arm["calls"])
    assert submitted_ids == ["run-1", "run-2", "run-3"]
    # Log file contains all run IDs
    assert sorted(log.read_text(encoding="utf-8").splitlines()) == ["run-1", "run-2", "run-3"]
    assert "All Failed run resubmitted successfully" in result.stdout


def test_batch_resubmit_skips_already_processed(tmp_path: Path, stub_arm: dict) -> None:
    stub_arm["runs"] = [_run("run-1"), _run("run-2")]
    log = tmp_path / "log.txt"
    log.write_text("run-1\n", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "runs", "batch-resubmit",
            "-wf", "wf1",
            "-st", "2026-05-14T00:00:00Z",
            "-et", "2026-05-15T00:00:00Z",
            "--yes",
            "--log-path", str(log),
        ],
    )
    assert result.exit_code == 0
    # Only run-2 should have been submitted
    assert [rid for _, _, rid in stub_arm["calls"]] == ["run-2"]
    # Log should contain both now
    lines = log.read_text(encoding="utf-8").splitlines()
    assert "run-1" in lines and "run-2" in lines


def test_batch_resubmit_throttle_retries(tmp_path: Path, stub_arm: dict) -> None:
    """A 429 on one run should pause and retry; final state has all resubmitted once."""
    stub_arm["runs"] = [_run("run-1"), _run("run-2")]
    stub_arm["fail_with"] = [("run-1", RuntimeError("HTTP 429 Too Many Requests"))]
    log = tmp_path / "log.txt"
    result = runner.invoke(
        app,
        [
            "runs", "batch-resubmit",
            "-wf", "wf1",
            "-st", "2026-05-14T00:00:00Z",
            "-et", "2026-05-15T00:00:00Z",
            "--yes",
            "--log-path", str(log),
            "--throttle-sleep", "0",  # fast test
        ],
    )
    assert result.exit_code == 0
    # run-1 attempted twice (first 429, second OK), run-2 once
    ids = [rid for _, _, rid in stub_arm["calls"]]
    assert ids.count("run-1") == 2
    assert ids.count("run-2") == 1
    assert "Hit throttling limitation" in result.stdout


def test_batch_resubmit_non_throttle_error_propagates(tmp_path: Path, stub_arm: dict) -> None:
    stub_arm["runs"] = [_run("run-1")]
    stub_arm["fail_with"] = [("run-1", RuntimeError("HTTP 500"))]
    result = runner.invoke(
        app,
        [
            "runs", "batch-resubmit",
            "-wf", "wf1",
            "-st", "2026-05-14T00:00:00Z",
            "-et", "2026-05-15T00:00:00Z",
            "--yes",
            "--log-path", str(tmp_path / "log.txt"),
            "--throttle-sleep", "0",
        ],
    )
    assert result.exit_code != 0


def test_batch_resubmit_uses_custom_status(tmp_path: Path, stub_arm: dict) -> None:
    stub_arm["runs"] = [_run("run-X")]
    result = runner.invoke(
        app,
        [
            "runs", "batch-resubmit",
            "-wf", "wf1",
            "-st", "2026-05-14T00:00:00Z",
            "-et", "2026-05-15T00:00:00Z",
            "-s", "Succeeded",
            "--yes",
            "--log-path", str(tmp_path / "log.txt"),
        ],
    )
    assert result.exit_code == 0
    assert "Detected 1 Succeeded runs." in result.stdout
    assert "All Succeeded run resubmitted successfully" in result.stdout


def test_batch_resubmit_confirms_before_starting(tmp_path: Path, stub_arm: dict) -> None:
    stub_arm["runs"] = [_run("run-1")]
    # Decline the first prompt
    result = runner.invoke(
        app,
        [
            "runs", "batch-resubmit",
            "-wf", "wf1",
            "-st", "2026-05-14T00:00:00Z",
            "-et", "2026-05-15T00:00:00Z",
            "--log-path", str(tmp_path / "log.txt"),
        ],
        input="n\n",
    )
    assert result.exit_code != 0
    assert stub_arm["calls"] == []


def test_collect_filters_runs_missing_name_or_trigger(stub_arm: dict) -> None:
    """Runs without a name or trigger.name must be skipped."""
    stub_arm["runs"] = [
        _run("ok"),
        {"name": "no-trigger", "properties": {}},
        {"properties": {"trigger": {"name": "manual"}}},  # no name
    ]
    found = mod._collect_candidate_runs("wf1", "Failed", "x", "y")
    assert [r.run_id for r in found] == ["ok"]
