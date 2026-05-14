"""Tests for `lat validate workflows`."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from lat import arm
from lat.cli import app

runner = CliRunner()


def _make_workflow(root: Path, name: str, definition: dict[str, Any]) -> None:
    wf = root / name
    wf.mkdir()
    (wf / "workflow.json").write_text(json.dumps(definition), encoding="utf-8")


@pytest.fixture()
def stub_validator(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub arm.validate_workflow_definition.

    state['responses'] keys workflow name -> (ok, msg) tuple.
    state['calls'] records the (workflow, envelope) pairs.
    """
    state: dict[str, Any] = {"responses": {}, "calls": []}

    def fake_validate(workflow: str, envelope: dict[str, Any]) -> tuple[bool, str]:
        state["calls"].append((workflow, envelope))
        return state["responses"].get(workflow, (True, ""))

    monkeypatch.setattr(arm, "validate_workflow_definition", fake_validate)
    return state


def test_no_workflows_aborts(tmp_path: Path, stub_validator: dict) -> None:
    result = runner.invoke(
        app, ["validate", "workflows", "--root", str(tmp_path)]
    )
    assert result.exit_code != 0
    assert "No workflows found" in result.output


def test_missing_root_aborts(tmp_path: Path, stub_validator: dict) -> None:
    result = runner.invoke(
        app, ["validate", "workflows", "--root", str(tmp_path / "nope")]
    )
    assert result.exit_code != 0


def test_passing_workflow_reported(tmp_path: Path, stub_validator: dict) -> None:
    _make_workflow(tmp_path, "wf1", {"kind": "Stateful", "definition": {"actions": {}}})
    result = runner.invoke(app, ["validate", "workflows", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "Found 1 workflow(s)" in result.stdout
    assert "wf1: Vaildation passed." in result.stdout
    # Envelope wraps workflow.json under "properties"
    assert len(stub_validator["calls"]) == 1
    workflow, envelope = stub_validator["calls"][0]
    assert workflow == "wf1"
    assert envelope == {"properties": {"kind": "Stateful", "definition": {"actions": {}}}}


def test_failing_workflow_reported(tmp_path: Path, stub_validator: dict) -> None:
    _make_workflow(tmp_path, "broken", {"definition": {}})
    stub_validator["responses"]["broken"] = (False, "Definition is missing required field")
    result = runner.invoke(app, ["validate", "workflows", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "broken: Validation failed" in result.stdout
    assert "Definition is missing required field" in result.stdout


def test_mixed_pass_and_fail(tmp_path: Path, stub_validator: dict) -> None:
    _make_workflow(tmp_path, "good", {"definition": {"actions": {}}})
    _make_workflow(tmp_path, "bad", {"definition": {"oops": True}})
    stub_validator["responses"]["bad"] = (False, "Invalid action shape")
    result = runner.invoke(app, ["validate", "workflows", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "good: Vaildation passed." in result.stdout
    assert "bad: Validation failed" in result.stdout


def test_directories_without_workflow_json_ignored(tmp_path: Path, stub_validator: dict) -> None:
    (tmp_path / "unrelated").mkdir()
    _make_workflow(tmp_path, "wf-real", {"definition": {}})
    result = runner.invoke(app, ["validate", "workflows", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "Found 1 workflow(s)" in result.stdout


def test_validator_raises_propagates(tmp_path: Path, stub_validator: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """500-level errors from the validator are surfaced (not swallowed)."""
    _make_workflow(tmp_path, "wf1", {"definition": {}})

    def boom(workflow: str, envelope: dict[str, Any]) -> tuple[bool, str]:
        raise RuntimeError("ARM 500 Internal Server Error")

    monkeypatch.setattr(arm, "validate_workflow_definition", boom)
    result = runner.invoke(app, ["validate", "workflows", "--root", str(tmp_path)])
    assert result.exit_code != 0
