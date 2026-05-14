"""Tests for the `lat site filter-host-logs` command."""
from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from typer.testing import CliRunner

from lat.cli import app

runner = CliRunner()


def test_filter_empty_dir(tmp_path: Path) -> None:
    result = runner.invoke(app, ["site", "filter-host-logs", "--log-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "No log files detected." in result.stdout


def test_filter_nonexistent_dir(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    result = runner.invoke(app, ["site", "filter-host-logs", "--log-dir", str(missing)])
    assert result.exit_code == 1
    assert "Log directory does not exist" in result.stdout


def test_filter_collects_errors_and_warnings(tmp_path: Path) -> None:
    log = tmp_path / "host.log"
    log.write_text(
        dedent(
            """\
            2026-05-14T10:00:00 [Information] Starting host.
            2026-05-14T10:00:01 [Information] Initialized worker.
            2026-05-14T10:00:02 [Error] Failed to load workflow X
                at frame 1
                at frame 2
            2026-05-14T10:00:03 [Information] Continuing
            2026-05-14T10:00:04 [Warning] Slow operation
                some continuation
            2026-05-14T10:00:05 [Error] Bang
            """
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out.log"
    result = runner.invoke(
        app,
        ["site", "filter-host-logs", "--log-dir", str(tmp_path), "--out", str(out)],
    )
    assert result.exit_code == 0
    assert out.exists()
    contents = out.read_text(encoding="utf-8")
    assert "[Error] Failed to load workflow X" in contents
    assert "at frame 1" in contents
    assert "at frame 2" in contents
    assert "[Warning] Slow operation" in contents
    assert "some continuation" in contents
    assert "[Error] Bang" in contents
    # Initial [Information] lines are skipped (they don't follow a hit)
    assert "Starting host." not in contents
    assert "Initialized worker." not in contents
    # [Information] resets continuation, then [Warning] re-engages — verify line
    # ordering preserves the original sequence.
    idx_err1 = contents.index("[Error] Failed to load workflow X")
    idx_warn = contents.index("[Warning] Slow operation")
    idx_err2 = contents.index("[Error] Bang")
    assert idx_err1 < idx_warn < idx_err2


def test_filter_no_hits_removes_empty_output(tmp_path: Path) -> None:
    log = tmp_path / "host.log"
    log.write_text(
        "2026-05-14T10:00:00 [Information] All quiet.\n", encoding="utf-8"
    )
    out = tmp_path / "out.log"
    result = runner.invoke(
        app,
        ["site", "filter-host-logs", "--log-dir", str(tmp_path), "--out", str(out)],
    )
    assert result.exit_code == 0
    assert "no warning or error messages" in result.stdout
    # No output file should remain
    assert not out.exists()


def test_filter_separator_between_files(tmp_path: Path) -> None:
    (tmp_path / "a.log").write_text(
        "2026-05-14 [Error] from-a\n", encoding="utf-8"
    )
    (tmp_path / "b.log").write_text(
        "2026-05-14 [Error] from-b\n", encoding="utf-8"
    )
    out = tmp_path / "out.log"
    result = runner.invoke(
        app,
        ["site", "filter-host-logs", "--log-dir", str(tmp_path), "--out", str(out)],
    )
    assert result.exit_code == 0
    contents = out.read_text(encoding="utf-8")
    # 58 '=' chars separator after each section
    assert "=" * 58 in contents
    # Two separate sections present
    assert contents.count("Error and Warning logs in") == 2
    assert "from-a" in contents and "from-b" in contents
