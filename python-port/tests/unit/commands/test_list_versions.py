"""Tests for `lat workflow list-versions`."""
from __future__ import annotations

import datetime as _dt

import pytest
from typer.testing import CliRunner

from lat.cli import app
from lat.storage.prefix import main_definition_table

runner = CliRunner()


def _version_row(
    flow_id: str,
    flow_name: str,
    seq_id: str,
    updated: str,
) -> dict:
    return {
        "PartitionKey": "PK",
        "RowKey": f"MYEDGEENVIRONMENT_FLOWVERSION-{seq_id}",
        "FlowName": flow_name,
        "FlowId": flow_id,
        "FlowSequenceId": seq_id,
        "FlowUpdatedTime": _dt.datetime.fromisoformat(updated),
        "ChangedTime": _dt.datetime.fromisoformat(updated),
    }


def test_lists_versions_newest_first(lat_env, fake_tables) -> None:
    table = main_definition_table("testlogicapp")
    fake_tables.add_table(
        table,
        _version_row("flowA", "myWorkflow", "v1", "2024-01-01T00:00:00+00:00"),
        _version_row("flowA", "myWorkflow", "v2", "2024-06-01T00:00:00+00:00"),
        _version_row("flowA", "myWorkflow", "v3", "2024-03-01T00:00:00+00:00"),
        # noise: different name + non-FLOWVERSION row
        _version_row("flowB", "otherWorkflow", "v9", "2024-09-01T00:00:00+00:00"),
        {
            "PartitionKey": "PK",
            "RowKey": "MYEDGEENVIRONMENT_FLOWLOOKUP-XYZ",
            "FlowName": "myWorkflow",
            "FlowId": "flowA",
            "FlowSequenceId": "current",
            "FlowUpdatedTime": _dt.datetime.fromisoformat("2024-12-01T00:00:00+00:00"),
        },
    )
    result = runner.invoke(
        app, ["workflow", "list-versions", "-wf", "myWorkflow"]
    )
    assert result.exit_code == 0, result.output
    # All 3 FLOWVERSION rows present, lookup row excluded
    assert result.output.count("flowA") == 3
    assert "flowB" not in result.output
    # Newest (v2) appears before older (v1, v3)
    lines = result.output.splitlines()
    v2_line = next(i for i, l in enumerate(lines) if "v2" in l)
    v3_line = next(i for i, l in enumerate(lines) if "v3" in l)
    v1_line = next(i for i, l in enumerate(lines) if "v1" in l)
    assert v2_line < v3_line < v1_line


def test_missing_workflow_errors(lat_env, fake_tables) -> None:
    table = main_definition_table("testlogicapp")
    fake_tables.add_table(table)  # empty
    result = runner.invoke(
        app, ["workflow", "list-versions", "-wf", "ghost"]
    )
    assert result.exit_code != 0
    assert "ghost cannot be found" in result.output


def test_only_flowversion_rows_kept(lat_env, fake_tables) -> None:
    table = main_definition_table("testlogicapp")
    fake_tables.add_table(
        table,
        # Only non-FLOWVERSION rows for this name
        {
            "PartitionKey": "PK",
            "RowKey": "MYEDGEENVIRONMENT_FLOWIDENTIFIER-X",
            "FlowName": "myWorkflow",
            "FlowId": "flowA",
            "FlowSequenceId": "id1",
            "FlowUpdatedTime": _dt.datetime.fromisoformat("2024-01-01T00:00:00+00:00"),
        },
        {
            "PartitionKey": "PK",
            "RowKey": "MYEDGEENVIRONMENT_FLOWLOOKUP-Y",
            "FlowName": "myWorkflow",
            "FlowId": "flowA",
            "FlowSequenceId": "lookup1",
            "FlowUpdatedTime": _dt.datetime.fromisoformat("2024-01-01T00:00:00+00:00"),
        },
    )
    result = runner.invoke(
        app, ["workflow", "list-versions", "-wf", "myWorkflow"]
    )
    assert result.exit_code != 0
    assert "cannot be found" in result.output
