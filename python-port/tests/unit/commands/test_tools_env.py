"""Tests for `lat tools import-appsettings` and `lat tools clean-environment-variable`."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from lat.cli import app
from lat.commands import tools_env

runner = CliRunner()


class RecordingWriter:
    """In-memory env-var writer that records calls for assertions."""

    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self.store: dict[str, str] = dict(initial or {})
        self.calls: list[tuple[str, str | None]] = []

    def set(self, name: str, value: str) -> None:
        self.store[name] = value
        self.calls.append(("set", name))  # type: ignore[arg-type]

    def delete(self, name: str) -> None:
        self.store.pop(name, None)
        self.calls.append(("delete", name))  # type: ignore[arg-type]


@pytest.fixture()
def recording_writer(monkeypatch: pytest.MonkeyPatch) -> RecordingWriter:
    writer = RecordingWriter()
    monkeypatch.setattr(tools_env, "_get_writer", lambda: writer)
    return writer


def _write_settings(tmp_path: Path, settings: dict[str, Any]) -> Path:
    f = tmp_path / "appsettings.json"
    f.write_text(json.dumps(settings), encoding="utf-8")
    return f


# ---------------------------------------------------------------------------
# ImportAppsettings
# ---------------------------------------------------------------------------


def test_import_appsettings_writes_all_keys(tmp_path: Path, recording_writer: RecordingWriter) -> None:
    f = _write_settings(tmp_path, {"FOO": "bar", "BAZ": "qux"})
    result = runner.invoke(
        app, ["tools", "import-appsettings", "-f", str(f), "--yes"]
    )
    assert result.exit_code == 0, result.stdout
    assert recording_writer.store == {"FOO": "bar", "BAZ": "qux"}
    assert "All app settings imported" in result.stdout


def test_import_appsettings_coerces_non_string_values(tmp_path: Path, recording_writer: RecordingWriter) -> None:
    f = _write_settings(tmp_path, {"NUM": 42, "BOOL": True})
    result = runner.invoke(
        app, ["tools", "import-appsettings", "-f", str(f), "--yes"]
    )
    assert result.exit_code == 0
    assert recording_writer.store == {"NUM": "42", "BOOL": "True"}


def test_import_appsettings_missing_file(tmp_path: Path, recording_writer: RecordingWriter) -> None:
    missing = tmp_path / "nope.json"
    result = runner.invoke(
        app, ["tools", "import-appsettings", "-f", str(missing), "--yes"]
    )
    assert result.exit_code != 0
    assert "not exists" in result.output


def test_import_appsettings_invalid_json(tmp_path: Path, recording_writer: RecordingWriter) -> None:
    f = tmp_path / "bad.json"
    f.write_text("{not valid", encoding="utf-8")
    result = runner.invoke(
        app, ["tools", "import-appsettings", "-f", str(f), "--yes"]
    )
    assert result.exit_code != 0
    assert "not valid JSON" in result.output


def test_import_appsettings_rejects_non_object_top_level(tmp_path: Path, recording_writer: RecordingWriter) -> None:
    f = tmp_path / "list.json"
    f.write_text("[1, 2, 3]", encoding="utf-8")
    result = runner.invoke(
        app, ["tools", "import-appsettings", "-f", str(f), "--yes"]
    )
    assert result.exit_code != 0


def test_import_appsettings_prompt_aborts_without_yes(tmp_path: Path, recording_writer: RecordingWriter) -> None:
    f = _write_settings(tmp_path, {"FOO": "bar"})
    # Decline at the prompt
    result = runner.invoke(
        app, ["tools", "import-appsettings", "-f", str(f)], input="n\n"
    )
    assert result.exit_code != 0
    assert recording_writer.store == {}  # nothing written


# ---------------------------------------------------------------------------
# CleanEnvironmentVariable
# ---------------------------------------------------------------------------


def test_clean_environment_variable_removes_all_keys(tmp_path: Path, recording_writer: RecordingWriter) -> None:
    recording_writer.store = {"FOO": "x", "BAR": "y", "UNTOUCHED": "z"}
    f = _write_settings(tmp_path, {"FOO": "old", "BAR": "old"})
    result = runner.invoke(
        app, ["tools", "clean-environment-variable", "-f", str(f), "--yes"]
    )
    assert result.exit_code == 0, result.stdout
    assert recording_writer.store == {"UNTOUCHED": "z"}
    assert "Environment variables have been removed." in result.stdout


def test_clean_environment_variable_ignores_missing_keys(tmp_path: Path, recording_writer: RecordingWriter) -> None:
    """delete() is a no-op for absent keys, mirroring .NET SetEnvironmentVariable(name, null)."""
    f = _write_settings(tmp_path, {"NOT_SET_ANYWHERE": "v"})
    result = runner.invoke(
        app, ["tools", "clean-environment-variable", "-f", str(f), "--yes"]
    )
    assert result.exit_code == 0
    assert recording_writer.calls == [("delete", "NOT_SET_ANYWHERE")]
