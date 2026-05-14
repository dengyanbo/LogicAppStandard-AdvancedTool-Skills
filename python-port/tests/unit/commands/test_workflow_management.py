"""Tests for workflow-management commands: revert, clone, convert-to-stateful,
restore-workflow-with-version, ingest-workflow."""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lat.cli import app
from lat.storage import compression
from lat.storage.prefix import (
    flowlookup_rowkey,
    main_definition_table,
    per_flow_table,
)

runner = CliRunner()

LA = "testlogicapp"
FLOW_ID = "ffffffff-aaaa-bbbb-cccc-dddddddddddd"


def _version_row(
    seq: str,
    *,
    flow_name: str = "wfOne",
    flow_id: str = FLOW_ID,
    definition: dict | None = None,
    runtime_context: dict | None = None,
    changed: str | None = None,
    kind: str = "Stateful",
) -> dict:
    row = {
        "PartitionKey": "PK",
        "RowKey": f"MYEDGEENVIRONMENT_FLOWVERSION-{seq}",
        "FlowName": flow_name,
        "FlowId": flow_id,
        "FlowSequenceId": seq,
        "DefinitionCompressed": compression.compress(
            json.dumps(definition or {"actions": {seq: {}}})
        ),
        "Kind": kind,
    }
    if changed:
        row["ChangedTime"] = _dt.datetime.fromisoformat(changed)
    if runtime_context is not None:
        row["RuntimeContext"] = compression.compress(json.dumps(runtime_context))
    return row


def _identifier_row(
    seq: str = "current",
    *,
    flow_name: str = "wfOne",
    flow_id: str = FLOW_ID,
    definition: dict | None = None,
    kind: str = "Stateful",
) -> dict:
    return {
        "PartitionKey": "PK",
        "RowKey": f"MYEDGEENVIRONMENT_FLOWIDENTIFIER-{seq}",
        "FlowName": flow_name,
        "FlowId": flow_id,
        "FlowSequenceId": seq,
        "DefinitionCompressed": compression.compress(
            json.dumps(definition or {"actions": {"identifier": {}}})
        ),
        "Kind": kind,
    }


def _lookup_row(*, flow_name: str = "wfOne", flow_id: str = FLOW_ID) -> dict:
    return {
        "PartitionKey": "PK",
        "RowKey": flowlookup_rowkey(flow_name),
        "FlowName": flow_name,
        "FlowId": flow_id,
    }


@pytest.fixture()
def wwwroot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("LAT_ROOT_FOLDER", str(tmp_path))
    return tmp_path


# ---------------------------------------------------------------------------
# revert
# ---------------------------------------------------------------------------


def test_revert_writes_workflow_json(lat_env, fake_tables, wwwroot: Path) -> None:
    fake_tables.add_table(
        main_definition_table(LA),
        _version_row("v1", definition={"actions": {"v1": {}}}),
        _version_row("v2", definition={"actions": {"v2": {}}}),
    )
    result = runner.invoke(
        app,
        ["workflow", "revert", "-wf", "wfOne", "-v", "v1", "--yes"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(
        (wwwroot / "wfOne" / "workflow.json").read_text(encoding="utf-8")
    )
    assert payload == {"definition": {"actions": {"v1": {}}}, "kind": "Stateful"}


def test_revert_unknown_version_errors(
    lat_env, fake_tables, wwwroot: Path
) -> None:
    fake_tables.add_table(main_definition_table(LA))
    result = runner.invoke(
        app,
        ["workflow", "revert", "-wf", "wfOne", "-v", "vghost", "--yes"],
    )
    assert result.exit_code != 0
    assert "No workflow definition found" in result.output


# ---------------------------------------------------------------------------
# clone
# ---------------------------------------------------------------------------


def test_clone_uses_flowidentifier_by_default(
    lat_env, fake_tables, wwwroot: Path
) -> None:
    fake_tables.add_table(
        main_definition_table(LA),
        _identifier_row(definition={"actions": {"latest": {}}}),
        _version_row("v1"),
    )
    result = runner.invoke(
        app,
        ["workflow", "clone", "-s", "wfOne", "-t", "wfClone"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(
        (wwwroot / "wfClone" / "workflow.json").read_text(encoding="utf-8")
    )
    assert payload["definition"] == {"actions": {"latest": {}}}


def test_clone_with_version_uses_that_row(
    lat_env, fake_tables, wwwroot: Path
) -> None:
    fake_tables.add_table(
        main_definition_table(LA),
        _identifier_row(definition={"actions": {"latest": {}}}),
        _version_row("V123", definition={"actions": {"v123": {}}}),
    )
    result = runner.invoke(
        app,
        ["workflow", "clone", "-s", "wfOne", "-t", "wfClone", "-v", "v123"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(
        (wwwroot / "wfClone" / "workflow.json").read_text(encoding="utf-8")
    )
    assert payload["definition"] == {"actions": {"v123": {}}}


def test_clone_target_exists_errors(
    lat_env, fake_tables, wwwroot: Path
) -> None:
    fake_tables.add_table(
        main_definition_table(LA),
        _identifier_row(definition={"actions": {}}),
    )
    (wwwroot / "wfClone").mkdir()
    result = runner.invoke(
        app,
        ["workflow", "clone", "-s", "wfOne", "-t", "wfClone"],
    )
    assert result.exit_code != 0
    assert "already exists" in result.output


# ---------------------------------------------------------------------------
# convert-to-stateful
# ---------------------------------------------------------------------------


def test_convert_to_stateful_clones_identifier_row(
    lat_env, fake_tables, wwwroot: Path
) -> None:
    fake_tables.add_table(
        main_definition_table(LA),
        _identifier_row(definition={"actions": {"src": {}}}, kind="Stateless"),
    )
    result = runner.invoke(
        app,
        ["workflow", "convert-to-stateful", "-s", "wfOne", "-t", "wfStateful"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(
        (wwwroot / "wfStateful" / "workflow.json").read_text(encoding="utf-8")
    )
    # Source kind is preserved (matches .NET behavior).
    assert payload["kind"] == "Stateless"
    assert payload["definition"] == {"actions": {"src": {}}}


# ---------------------------------------------------------------------------
# restore-workflow-with-version
# ---------------------------------------------------------------------------


def test_restore_workflow_with_version_writes_files(
    lat_env, fake_tables, wwwroot: Path, tmp_path: Path
) -> None:
    fake_tables.add_table(
        main_definition_table(LA),
        _lookup_row(),
        _version_row(
            "v1",
            definition={"actions": {"v1": {}}},
            runtime_context={"connections": []},
            changed="2024-01-01T00:00:00+00:00",
        ),
    )
    ctx_folder = tmp_path / "ctx-out"
    result = runner.invoke(
        app,
        [
            "workflow", "restore-workflow-with-version",
            "-wf", "wfOne",
            "--flow-id", FLOW_ID,
            "-v", "v1",
            "--runtime-context-output", str(ctx_folder),
        ],
    )
    assert result.exit_code == 0, result.output
    assert (wwwroot / "wfOne" / "workflow.json").exists()
    ctx_file = ctx_folder / "RuntimeContext_wfOne_v1.json"
    assert ctx_file.exists()
    assert json.loads(ctx_file.read_text(encoding="utf-8")) == {"connections": []}


# ---------------------------------------------------------------------------
# ingest-workflow
# ---------------------------------------------------------------------------


def test_ingest_workflow_updates_both_tables(
    lat_env, fake_tables, wwwroot: Path
) -> None:
    # Set up: main definition table with 5 rows for wfOne; per-workflow table with 3.
    main_client = fake_tables.add_table(
        main_definition_table(LA),
        _lookup_row(),
        *[
            _version_row(
                f"v{i}",
                definition={"actions": {f"old-v{i}": {}}},
                changed=f"2024-0{i+1}-01T00:00:00+00:00",
            )
            for i in range(1, 6)
        ],
    )
    wf_table = per_flow_table(LA, FLOW_ID, "flows")
    wf_client = fake_tables.add_table(
        wf_table,
        *[
            {
                "PartitionKey": "PK",
                "RowKey": f"wf-row-{i}",
                "FlowName": "wfOne",
                "FlowId": FLOW_ID,
                "DefinitionCompressed": compression.compress(
                    json.dumps({"old": True})
                ),
                "ChangedTime": _dt.datetime.fromisoformat(
                    f"2024-0{i+1}-01T00:00:00+00:00"
                ),
            }
            for i in range(1, 4)
        ],
    )

    # Local workflow.json with a new definition.
    wf_folder = wwwroot / "wfOne"
    wf_folder.mkdir()
    (wf_folder / "workflow.json").write_text(
        json.dumps({"definition": {"new": "shiny"}, "kind": "Stateful"}),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["workflow", "ingest-workflow", "-wf", "wfOne", "--yes"],
    )
    assert result.exit_code == 0, result.output

    # 4 main rows updated, 2 wf rows updated.
    updated_main = [u for u in main_client.update_calls if u.get("FlowName") is None]
    # Each update payload carries only the merge fields, so we count length:
    assert len(main_client.update_calls) == 4
    assert len(wf_client.update_calls) == 2

    # Verify the new compressed payload now decompresses to the new definition.
    new_compressed = main_client.update_calls[0]["DefinitionCompressed"]
    assert json.loads(compression.decompress(new_compressed)) == {"new": "shiny"}


def test_ingest_workflow_missing_file_errors(
    lat_env, fake_tables, wwwroot: Path
) -> None:
    fake_tables.add_table(main_definition_table(LA), _lookup_row())
    result = runner.invoke(
        app, ["workflow", "ingest-workflow", "-wf", "wfMissing", "--yes"]
    )
    assert result.exit_code != 0
    assert "Cannot find definition Json file" in result.output
