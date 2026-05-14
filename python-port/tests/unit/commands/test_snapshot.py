"""Tests for `lat site snapshot-create` / `lat site snapshot-restore`."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from lat import arm
from lat.cli import app

runner = CliRunner()


@pytest.fixture()
def stub_arm(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {
        "appsettings": {"FOO": "bar", "BAZ": "qux"},
        "get_fail": None,
        "put_calls": [],
    }

    def fake_get() -> dict[str, str]:
        if state["get_fail"]:
            raise state["get_fail"]
        return dict(state["appsettings"])

    def fake_put(props: dict[str, str]) -> None:
        state["put_calls"].append(dict(props))

    monkeypatch.setattr(arm, "get_appsettings", fake_get)
    monkeypatch.setattr(arm, "put_appsettings", fake_put)
    return state


def _make_wwwroot(tmp_path: Path) -> Path:
    """Build a minimal sample wwwroot."""
    root = tmp_path / "wwwroot"
    root.mkdir()
    (root / "host.json").write_text('{"version":"2.0"}', encoding="utf-8")
    wf = root / "wf1"
    wf.mkdir()
    (wf / "workflow.json").write_text(
        json.dumps({"definition": {"actions": {}}}), encoding="utf-8"
    )
    return root


# ---------------------------------------------------------------------------
# Snapshot Create
# ---------------------------------------------------------------------------


def test_snapshot_create_copies_files_and_dumps_appsettings(
    tmp_path: Path, stub_arm: dict
) -> None:
    root = _make_wwwroot(tmp_path)
    out = tmp_path / "Snapshot_test"
    result = runner.invoke(
        app,
        ["site", "snapshot-create", "--root", str(root), "--out", str(out)],
    )
    assert result.exit_code == 0, result.stdout
    # Files copied
    assert (out / "host.json").read_text(encoding="utf-8") == '{"version":"2.0"}'
    assert (out / "wf1" / "workflow.json").exists()
    # appsettings.json written with our stub data
    saved = json.loads((out / "appsettings.json").read_text(encoding="utf-8"))
    assert saved == {"FOO": "bar", "BAZ": "qux"}


def test_snapshot_create_continues_when_appsettings_dump_fails(
    tmp_path: Path, stub_arm: dict
) -> None:
    stub_arm["get_fail"] = RuntimeError("ARM 403 Forbidden")
    root = _make_wwwroot(tmp_path)
    out = tmp_path / "Snapshot_failed"
    result = runner.invoke(
        app,
        ["site", "snapshot-create", "--root", str(root), "--out", str(out)],
    )
    assert result.exit_code == 0  # wwwroot succeeded, appsettings is best-effort
    assert (out / "host.json").exists()
    assert not (out / "appsettings.json").exists()
    assert "Failed to retrieve appsettings" in result.stdout


def test_snapshot_create_skip_appsettings_flag(
    tmp_path: Path, stub_arm: dict
) -> None:
    root = _make_wwwroot(tmp_path)
    out = tmp_path / "Snapshot_skip"
    result = runner.invoke(
        app,
        [
            "site", "snapshot-create",
            "--root", str(root),
            "--out", str(out),
            "--skip-appsettings",
        ],
    )
    assert result.exit_code == 0
    assert not (out / "appsettings.json").exists()
    assert "Skipping app-settings dump" in result.stdout


def test_snapshot_create_refuses_existing_target(
    tmp_path: Path, stub_arm: dict
) -> None:
    root = _make_wwwroot(tmp_path)
    out = tmp_path / "exists"
    out.mkdir()
    result = runner.invoke(
        app,
        ["site", "snapshot-create", "--root", str(root), "--out", str(out)],
    )
    assert result.exit_code != 0
    assert "already exist" in result.output


def test_snapshot_create_missing_root(tmp_path: Path, stub_arm: dict) -> None:
    result = runner.invoke(
        app,
        [
            "site", "snapshot-create",
            "--root", str(tmp_path / "nope"),
            "--out", str(tmp_path / "out"),
        ],
    )
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Snapshot Restore
# ---------------------------------------------------------------------------


def _make_snapshot(tmp_path: Path) -> Path:
    """Build a sample snapshot with wwwroot files + appsettings.json."""
    snap = tmp_path / "Snapshot_sample"
    snap.mkdir()
    (snap / "host.json").write_text('{"version":"2.0"}', encoding="utf-8")
    wf = snap / "wf1"
    wf.mkdir()
    (wf / "workflow.json").write_text(
        json.dumps({"definition": {"actions": {}}}), encoding="utf-8"
    )
    (snap / "appsettings.json").write_text(
        json.dumps({"FOO": "from-snapshot", "NEW": "val"}, indent=2), encoding="utf-8"
    )
    return snap


def test_snapshot_restore_replaces_root_and_pushes_appsettings(
    tmp_path: Path, stub_arm: dict
) -> None:
    snap = _make_snapshot(tmp_path)
    # Existing wwwroot with different contents
    root = tmp_path / "wwwroot"
    root.mkdir()
    (root / "obsolete.txt").write_text("OLD", encoding="utf-8")

    result = runner.invoke(
        app,
        ["site", "snapshot-restore", "-p", str(snap), "--root", str(root), "--yes"],
    )
    assert result.exit_code == 0, result.stdout
    # Old file gone, new files present
    assert not (root / "obsolete.txt").exists()
    assert (root / "host.json").read_text(encoding="utf-8") == '{"version":"2.0"}'
    # appsettings pushed to ARM
    assert stub_arm["put_calls"] == [{"FOO": "from-snapshot", "NEW": "val"}]
    assert "Logic App will restart automatically" in result.stdout


def test_snapshot_restore_missing_appsettings_file_fails(
    tmp_path: Path, stub_arm: dict
) -> None:
    snap = tmp_path / "Snapshot_partial"
    snap.mkdir()
    (snap / "host.json").write_text('{"v":"2"}', encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "site", "snapshot-restore",
            "-p", str(snap),
            "--root", str(tmp_path / "wwwroot"),
            "--yes",
        ],
    )
    assert result.exit_code != 0
    assert "Missing appsettings.json" in result.output
    # Note: file restore happens before appsettings check (matches .NET);
    # ARM put_calls should remain empty.
    assert stub_arm["put_calls"] == []


def test_snapshot_restore_rejects_invalid_appsettings_shape(
    tmp_path: Path, stub_arm: dict
) -> None:
    snap = _make_snapshot(tmp_path)
    (snap / "appsettings.json").write_text("[1, 2, 3]", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "site", "snapshot-restore",
            "-p", str(snap),
            "--root", str(tmp_path / "wwwroot"),
            "--yes",
        ],
    )
    assert result.exit_code != 0
    assert stub_arm["put_calls"] == []


def test_snapshot_restore_missing_path(tmp_path: Path, stub_arm: dict) -> None:
    result = runner.invoke(
        app,
        [
            "site", "snapshot-restore",
            "-p", str(tmp_path / "nope"),
            "--root", str(tmp_path / "wwwroot"),
            "--yes",
        ],
    )
    assert result.exit_code != 0


def test_snapshot_restore_requires_confirmation_without_yes(
    tmp_path: Path, stub_arm: dict
) -> None:
    snap = _make_snapshot(tmp_path)
    root = tmp_path / "wwwroot"
    result = runner.invoke(
        app,
        ["site", "snapshot-restore", "-p", str(snap), "--root", str(root)],
        input="n\n",
    )
    assert result.exit_code != 0
    assert stub_arm["put_calls"] == []
