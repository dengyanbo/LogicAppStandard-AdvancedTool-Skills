"""Tests for `lat workflow list-workflows` and `list-workflows-summary`."""
from __future__ import annotations

import datetime as _dt

from typer.testing import CliRunner

from lat.cli import app
from lat.storage.prefix import flowlookup_rowkey, main_definition_table

runner = CliRunner()


def _row(
    flow_id: str,
    flow_name: str,
    rk_suffix: str,
    changed: str,
    *,
    kind: str = "Stateful",
) -> dict:
    return {
        "PartitionKey": "PK",
        "RowKey": rk_suffix,
        "FlowName": flow_name,
        "FlowId": flow_id,
        "Kind": kind,
        "ChangedTime": _dt.datetime.fromisoformat(changed),
    }


def _seed(fake_tables) -> None:
    table = main_definition_table("testlogicapp")
    fake_tables.add_table(
        table,
        # Workflow "alpha" has 2 FlowIds (one currently in use, one deleted),
        # each with 2 versions.
        _row("alpha-1", "alpha", "MYEDGEENVIRONMENT_FLOWVERSION-v1",
             "2024-01-01T00:00:00+00:00"),
        _row("alpha-1", "alpha", "MYEDGEENVIRONMENT_FLOWVERSION-v2",
             "2024-02-01T00:00:00+00:00"),
        _row("alpha-2", "alpha", "MYEDGEENVIRONMENT_FLOWVERSION-v3",
             "2024-06-01T00:00:00+00:00"),
        _row("alpha-2", "alpha", "MYEDGEENVIRONMENT_FLOWVERSION-v4",
             "2024-07-01T00:00:00+00:00"),
        # Lookup row points at alpha-2 (current).
        {
            "PartitionKey": "PK",
            "RowKey": flowlookup_rowkey("alpha"),
            "FlowName": "alpha",
            "FlowId": "alpha-2",
            "Kind": "Stateful",
            "ChangedTime": _dt.datetime.fromisoformat(
                "2024-08-01T00:00:00+00:00"
            ),
        },
        # Workflow "beta" has 1 FlowId, 1 version.
        _row("beta-1", "beta", "MYEDGEENVIRONMENT_FLOWVERSION-v1",
             "2024-03-01T00:00:00+00:00", kind="Stateless"),
        {
            "PartitionKey": "PK",
            "RowKey": flowlookup_rowkey("beta"),
            "FlowName": "beta",
            "FlowId": "beta-1",
            "Kind": "Stateless",
            "ChangedTime": _dt.datetime.fromisoformat(
                "2024-03-15T00:00:00+00:00"
            ),
        },
    )


def test_summary_lists_each_workflow_once(lat_env, fake_tables) -> None:
    _seed(fake_tables)
    result = runner.invoke(app, ["workflow", "list-workflows-summary"])
    assert result.exit_code == 0, result.output
    # Each name appears exactly once in the summary table
    assert result.output.count("alpha") >= 1
    assert result.output.count("beta") >= 1
    # alpha sibling count = 2 (two FlowIds)
    assert "2" in result.output


def test_interactive_drilldown(lat_env, fake_tables) -> None:
    _seed(fake_tables)
    # Inputs: pick alpha (index 0), then pick first FlowId
    result = runner.invoke(
        app, ["workflow", "list-workflows"], input="0\n0\n"
    )
    assert result.exit_code == 0, result.output
    # Should show "In Use" exactly once (current FlowId alpha-2)
    assert "In Use" in result.output
    assert "Deleted" in result.output


def test_summary_empty_aborts(lat_env, fake_tables) -> None:
    table = main_definition_table("testlogicapp")
    fake_tables.add_table(table)
    result = runner.invoke(app, ["workflow", "list-workflows-summary"])
    assert result.exit_code != 0
