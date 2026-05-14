"""Tests for `lat site sync-to-local-{normal,auto,batch}`.

Replace _share_client with a synthetic dir client that walks an in-memory
tree of files/directories. No Azure SDK calls happen during tests.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import pytest
from typer.testing import CliRunner

from lat.cli import app
from lat.commands import sync_to_local as mod
from lat.commands.sync_to_local import (
    DEFAULT_EXCLUDES,
    _purge_subfolders,
    _resolve_excludes,
)

runner = CliRunner()


class FakeDirClient:
    """In-memory _DirClient implementation; tree is a nested dict.

    Leaves are bytes (file contents). Sub-dicts are sub-directories.
    """

    def __init__(self, tree: dict[str, Any]) -> None:
        self.tree = tree

    def list_files(self) -> Iterable[tuple[str, bool]]:
        for name, value in self.tree.items():
            yield name, isinstance(value, dict)

    def open_subdir(self, name: str) -> "FakeDirClient":
        return FakeDirClient(self.tree[name])

    def download_file(self, name: str) -> bytes:
        return self.tree[name]


@pytest.fixture()
def fake_shares(monkeypatch: pytest.MonkeyPatch) -> dict[tuple[str, str], dict[str, Any]]:
    """Replace _share_client with a (cs, share) -> tree lookup."""
    catalog: dict[tuple[str, str], dict[str, Any]] = {}

    def fake(cs: str, share: str) -> FakeDirClient:
        if (cs, share) not in catalog:
            raise AssertionError(f"unknown fake share ({cs!r}, {share!r})")
        return FakeDirClient(catalog[(cs, share)])

    monkeypatch.setattr(mod, "_share_client", fake)
    return catalog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_resolve_excludes_includes_defaults() -> None:
    assert DEFAULT_EXCLUDES.issubset(_resolve_excludes(None))
    assert DEFAULT_EXCLUDES.issubset(_resolve_excludes([]))


def test_resolve_excludes_merges_extras() -> None:
    out = _resolve_excludes(["custom1", " custom2 ", ""])
    assert "custom1" in out
    assert "custom2" in out
    # Defaults still present
    assert ".git" in out


def test_purge_subfolders_keeps_excludes(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "removed").mkdir()
    (tmp_path / "kept").mkdir()
    (tmp_path / "stayfile").write_text("x", encoding="utf-8")  # file at top level

    _purge_subfolders(tmp_path, {".git", "kept"})

    assert (tmp_path / ".git").exists()
    assert (tmp_path / "kept").exists()
    assert not (tmp_path / "removed").exists()
    # Top-level files untouched
    assert (tmp_path / "stayfile").exists()


def test_purge_subfolders_handles_missing_local(tmp_path: Path) -> None:
    _purge_subfolders(tmp_path / "absent", DEFAULT_EXCLUDES)  # no error


# ---------------------------------------------------------------------------
# Auto mode — non-interactive
# ---------------------------------------------------------------------------


def test_auto_sync_downloads_files(tmp_path: Path, fake_shares: dict) -> None:
    fake_shares[("cs1", "share1")] = {
        "host.json": b'{"version":"2.0"}',
        "wf1": {"workflow.json": b'{"definition":{}}'},
        "wf2": {
            "workflow.json": b'{"definition":{}}',
            "subfolder": {"deep.txt": b"deep"},
        },
    }
    local = tmp_path / "wwwroot"
    local.mkdir()
    (local / "obsolete").mkdir()  # should be removed by purge

    result = runner.invoke(
        app,
        [
            "site", "sync-to-local-auto",
            "-sn", "share1",
            "-cs", "cs1",
            "-path", str(local),
        ],
    )
    assert result.exit_code == 0, result.stdout
    # Cloud tree fully materialized
    assert (local / "host.json").read_bytes() == b'{"version":"2.0"}'
    assert (local / "wf1" / "workflow.json").read_bytes() == b'{"definition":{}}'
    assert (local / "wf2" / "subfolder" / "deep.txt").read_bytes() == b"deep"
    # Pre-existing non-excluded subfolder purged
    assert not (local / "obsolete").exists()


def test_auto_sync_preserves_excludes(tmp_path: Path, fake_shares: dict) -> None:
    fake_shares[("cs1", "share1")] = {"host.json": b"x"}
    local = tmp_path / "wwwroot"
    local.mkdir()
    (local / ".git").mkdir()  # default excluded
    (local / "custom").mkdir()  # exclude via -ex
    (local / "purged").mkdir()  # should be removed

    result = runner.invoke(
        app,
        [
            "site", "sync-to-local-auto",
            "-sn", "share1",
            "-cs", "cs1",
            "-path", str(local),
            "-ex", "custom",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert (local / ".git").exists()
    assert (local / "custom").exists()
    assert not (local / "purged").exists()


# ---------------------------------------------------------------------------
# Normal mode — interactive
# ---------------------------------------------------------------------------


def test_normal_sync_no_cleanup_when_declined(tmp_path: Path, fake_shares: dict) -> None:
    """Decline the cleanup prompt: existing folders remain."""
    fake_shares[("cs1", "share1")] = {"host.json": b"x"}
    local = tmp_path / "wwwroot"
    local.mkdir()
    (local / "obsolete").mkdir()

    # First prompt: confirm overwrite (y), second: cleanup (n)
    result = runner.invoke(
        app,
        [
            "site", "sync-to-local-normal",
            "-sn", "share1",
            "-cs", "cs1",
            "-path", str(local),
        ],
        input="y\nn\n",
    )
    assert result.exit_code == 0, result.stdout
    assert (local / "host.json").read_bytes() == b"x"
    assert (local / "obsolete").exists()  # not purged


def test_normal_sync_cleanup_with_custom_excludes(tmp_path: Path, fake_shares: dict) -> None:
    fake_shares[("cs1", "share1")] = {"host.json": b"x"}
    local = tmp_path / "wwwroot"
    local.mkdir()
    (local / "keep-me").mkdir()
    (local / "purge-me").mkdir()

    # overwrite y, cleanup y, exclude "keep-me"
    result = runner.invoke(
        app,
        [
            "site", "sync-to-local-normal",
            "-sn", "share1",
            "-cs", "cs1",
            "-path", str(local),
        ],
        input="y\ny\nkeep-me\n",
    )
    assert result.exit_code == 0, result.stdout
    assert (local / "keep-me").exists()
    assert not (local / "purge-me").exists()


def test_normal_sync_abort_on_overwrite_decline(tmp_path: Path, fake_shares: dict) -> None:
    """The very first confirmation aborts the whole command."""
    fake_shares[("cs1", "share1")] = {"host.json": b"x"}
    local = tmp_path / "wwwroot"
    local.mkdir()
    result = runner.invoke(
        app,
        [
            "site", "sync-to-local-normal",
            "-sn", "share1",
            "-cs", "cs1",
            "-path", str(local),
        ],
        input="n\n",
    )
    assert result.exit_code != 0
    # Nothing got downloaded
    assert not (local / "host.json").exists()


def test_normal_sync_with_yes_flag_skips_prompts(tmp_path: Path, fake_shares: dict) -> None:
    fake_shares[("cs1", "share1")] = {"host.json": b"x"}
    local = tmp_path / "wwwroot"
    local.mkdir()
    (local / "obsolete").mkdir()
    result = runner.invoke(
        app,
        [
            "site", "sync-to-local-normal",
            "-sn", "share1",
            "-cs", "cs1",
            "-path", str(local),
            "--yes",
        ],
    )
    assert result.exit_code == 0
    # --yes => no cleanup; obsolete folder still here
    assert (local / "obsolete").exists()
    assert (local / "host.json").read_bytes() == b"x"


# ---------------------------------------------------------------------------
# Batch mode
# ---------------------------------------------------------------------------


def test_batch_sync_runs_each_entry(tmp_path: Path, fake_shares: dict) -> None:
    fake_shares[("cs1", "share1")] = {"a.txt": b"A"}
    fake_shares[("cs2", "share2")] = {"b.txt": b"B"}

    local_a = tmp_path / "appA"
    local_b = tmp_path / "appB"
    local_a.mkdir()
    local_b.mkdir()

    config = tmp_path / "batch.json"
    config.write_text(
        json.dumps(
            [
                {
                    "FileShareName": "share1",
                    "ConnectionString": "cs1",
                    "LocalPath": str(local_a),
                    "Excludes": [],
                },
                {
                    "FileShareName": "share2",
                    "ConnectionString": "cs2",
                    "LocalPath": str(local_b),
                    "Excludes": ["custom"],
                },
            ]
        ),
        encoding="utf-8",
    )
    result = runner.invoke(
        app, ["site", "sync-to-local-batch", "-cf", str(config)]
    )
    assert result.exit_code == 0, result.stdout
    assert (local_a / "a.txt").read_bytes() == b"A"
    assert (local_b / "b.txt").read_bytes() == b"B"
    assert "All the projects have been synced" in result.stdout


def test_batch_sync_missing_config(tmp_path: Path, fake_shares: dict) -> None:
    result = runner.invoke(
        app, ["site", "sync-to-local-batch", "-cf", str(tmp_path / "nope.json")]
    )
    assert result.exit_code != 0
    assert "cannot be found" in result.output


def test_batch_sync_rejects_non_list(tmp_path: Path, fake_shares: dict) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text('{"a":1}', encoding="utf-8")
    result = runner.invoke(app, ["site", "sync-to-local-batch", "-cf", str(bad)])
    assert result.exit_code != 0


def test_batch_sync_rejects_entry_with_missing_fields(tmp_path: Path, fake_shares: dict) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([{"FileShareName": "s"}]), encoding="utf-8")
    result = runner.invoke(app, ["site", "sync-to-local-batch", "-cf", str(bad)])
    assert result.exit_code != 0
