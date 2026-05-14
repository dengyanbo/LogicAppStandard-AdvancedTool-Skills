"""Tests for `lat workflow decode`."""
from __future__ import annotations

import json

from typer.testing import CliRunner

from lat.cli import app
from lat.storage import compression
from lat.storage.prefix import main_definition_table

runner = CliRunner()


def _row(flow_name: str, seq: str, definition: dict, *, kind: str = "Stateful") -> dict:
    return {
        "PartitionKey": "PK",
        "RowKey": f"MYEDGEENVIRONMENT_FLOWVERSION-{seq}",
        "FlowName": flow_name,
        "FlowId": "flowA",
        "FlowSequenceId": seq,
        "DefinitionCompressed": compression.compress(json.dumps(definition)),
        "Kind": kind,
    }


def test_decode_emits_definition_json(lat_env, fake_tables) -> None:
    table = main_definition_table("testlogicapp")
    fake_tables.add_table(
        table,
        _row("wfOne", "v1", {"actions": {"a1": {}}}),
        _row("wfOne", "v2", {"actions": {"a2": {}}}),
    )
    result = runner.invoke(
        app,
        ["workflow", "decode", "-wf", "wfOne", "-v", "v2"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == {"definition": {"actions": {"a2": {}}}, "kind": "Stateful"}


def test_decode_unknown_version_errors(lat_env, fake_tables) -> None:
    table = main_definition_table("testlogicapp")
    fake_tables.add_table(table, _row("wfOne", "v1", {"actions": {}}))
    result = runner.invoke(
        app, ["workflow", "decode", "-wf", "wfOne", "-v", "vnone"]
    )
    assert result.exit_code != 0
    assert "cannot be found" in result.output


def test_decode_unknown_workflow_errors(lat_env, fake_tables) -> None:
    table = main_definition_table("testlogicapp")
    fake_tables.add_table(table, _row("wfOne", "v1", {"actions": {}}))
    result = runner.invoke(
        app, ["workflow", "decode", "-wf", "ghost", "-v", "v1"]
    )
    assert result.exit_code != 0
    assert "cannot be found" in result.output
