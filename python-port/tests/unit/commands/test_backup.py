"""Tests for `lat workflow backup`."""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lat import arm
from lat.cli import app
from lat.storage import compression
from lat.storage.prefix import main_definition_table

runner = CliRunner()


def _make_definition_bytes(definition: dict) -> bytes:
    return compression.compress(json.dumps(definition))


def _row(
    flow_id: str,
    flow_name: str,
    seq_id: str,
    changed: str,
    definition: dict,
    *,
    rk_prefix: str = "MYEDGEENVIRONMENT_FLOWVERSION",
    kind: str = "Stateful",
) -> dict:
    return {
        "PartitionKey": "PK",
        "RowKey": f"{rk_prefix}-{seq_id}",
        "FlowName": flow_name,
        "FlowId": flow_id,
        "FlowSequenceId": seq_id,
        "ChangedTime": _dt.datetime.fromisoformat(changed),
        "DefinitionCompressed": _make_definition_bytes(definition),
        "Kind": kind,
    }


@pytest.fixture()
def stub_arm(monkeypatch: pytest.MonkeyPatch) -> dict:
    state: dict = {"calls": 0, "result": {"FOO": "BAR"}, "raise": False}

    def fake_get():
        state["calls"] += 1
        if state["raise"]:
            raise RuntimeError("ARM 403 Forbidden")
        return state["result"]

    monkeypatch.setattr(arm, "get_appsettings", fake_get)
    return state


def test_backup_writes_definitions_and_appsettings(
    tmp_path: Path, lat_env, fake_tables, stub_arm
) -> None:
    table = main_definition_table("testlogicapp")
    fake_tables.add_table(
        table,
        _row("flowA", "wfOne", "a-v1", "2024-01-01T00:00:00+00:00",
             {"actions": {"a1": {}}}),
        _row("flowA", "wfOne", "a-v2", "2024-02-01T00:00:00+00:00",
             {"actions": {"a2": {}}}),
        # Non-FLOWVERSION row must be ignored
        _row("flowA", "wfOne", "a-lookup", "2024-03-01T00:00:00+00:00",
             {"actions": {}},
             rk_prefix="MYEDGEENVIRONMENT_FLOWLOOKUP"),
        # Different workflow
        _row("flowB", "wfTwo", "b-v1", "2024-04-01T00:00:00+00:00",
             {"actions": {"b": {}}}),
    )

    result = runner.invoke(
        app, ["workflow", "backup", "--output", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output

    # appsettings.json written
    settings_path = tmp_path / "appsettings.json"
    assert settings_path.exists()
    assert json.loads(settings_path.read_text(encoding="utf-8")) == {"FOO": "BAR"}

    # wfOne has 2 versions; latest ChangedTime is 2024-02 -> folder tag should match
    wf1_folder = tmp_path / "wfOne" / "LastModified_20240201000000_flowA"
    assert wf1_folder.exists(), list(tmp_path.iterdir())
    files = sorted(p.name for p in wf1_folder.iterdir())
    assert files == ["20240101000000_a-v1.json", "20240201000000_a-v2.json"]

    # wfTwo has 1 version
    wf2_folder = tmp_path / "wfTwo" / "LastModified_20240401000000_flowB"
    assert wf2_folder.exists()
    assert (wf2_folder / "20240401000000_b-v1.json").exists()

    # Decompressed file content includes original definition
    payload = json.loads(
        (wf1_folder / "20240201000000_a-v2.json").read_text(encoding="utf-8")
    )
    assert payload["kind"] == "Stateful"
    assert payload["definition"] == {"actions": {"a2": {}}}


def test_backup_skips_existing_files(
    tmp_path: Path, lat_env, fake_tables, stub_arm
) -> None:
    table = main_definition_table("testlogicapp")
    fake_tables.add_table(
        table,
        _row("flowA", "wfOne", "a-v1", "2024-01-01T00:00:00+00:00",
             {"actions": {"a1": {}}}),
    )
    target_folder = tmp_path / "wfOne" / "LastModified_20240101000000_flowA"
    target_folder.mkdir(parents=True)
    existing = target_folder / "20240101000000_a-v1.json"
    existing.write_text('{"sentinel": true}', encoding="utf-8")

    result = runner.invoke(
        app, ["workflow", "backup", "--output", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    # File preserved — backup did not overwrite
    assert json.loads(existing.read_text(encoding="utf-8")) == {"sentinel": True}


def test_backup_date_filter(
    tmp_path: Path, lat_env, fake_tables, stub_arm
) -> None:
    table = main_definition_table("testlogicapp")
    fake_tables.add_table(
        table,
        _row("flowA", "wfOne", "a-old", "2023-01-01T00:00:00+00:00",
             {"actions": {}}),
        _row("flowA", "wfOne", "a-new", "2024-08-15T00:00:00+00:00",
             {"actions": {}}),
    )
    result = runner.invoke(
        app,
        [
            "workflow", "backup",
            "--date", "20240101",
            "--output", str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    folder = tmp_path / "wfOne" / "LastModified_20240815000000_flowA"
    assert folder.exists()
    files = list(folder.iterdir())
    # Only the "new" definition was backed up
    assert len(files) == 1
    assert files[0].name == "20240815000000_a-new.json"


def test_backup_continues_if_appsettings_fails(
    tmp_path: Path, lat_env, fake_tables, stub_arm
) -> None:
    stub_arm["raise"] = True
    table = main_definition_table("testlogicapp")
    fake_tables.add_table(
        table,
        _row("flowA", "wfOne", "a-v1", "2024-01-01T00:00:00+00:00", {"actions": {}}),
    )
    result = runner.invoke(
        app, ["workflow", "backup", "--output", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    # No appsettings file written
    assert not (tmp_path / "appsettings.json").exists()
    # But workflow file was still saved
    folder = tmp_path / "wfOne" / "LastModified_20240101000000_flowA"
    assert (folder / "20240101000000_a-v1.json").exists()
    assert "Failed to retrieve appsettings" in result.output


def test_backup_bad_date_format(tmp_path: Path, lat_env, fake_tables, stub_arm) -> None:
    table = main_definition_table("testlogicapp")
    fake_tables.add_table(table)
    result = runner.invoke(
        app,
        [
            "workflow", "backup",
            "--date", "2024-01-01",  # wrong format
            "--output", str(tmp_path),
        ],
    )
    assert result.exit_code != 0
    assert "yyyyMMdd" in result.output
