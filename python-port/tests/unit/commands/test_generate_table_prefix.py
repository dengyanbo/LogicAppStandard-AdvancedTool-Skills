"""Tests for `lat tools generate-table-prefix`."""
from __future__ import annotations

from typer.testing import CliRunner

from lat.cli import app
from lat.storage.prefix import flowlookup_rowkey, generate, main_definition_table

runner = CliRunner()


def test_la_only_when_no_workflow(lat_env, fake_tables) -> None:
    # Table need not exist for this branch.
    result = runner.invoke(app, ["tools", "generate-table-prefix"])
    assert result.exit_code == 0, result.output
    expected = generate("testlogicapp")
    assert f"Logic App Prefix: {expected}" in result.output
    # Workflow Prefix line should NOT appear
    assert "Workflow Prefix" not in result.output


def test_resolves_workflow_to_combined_prefix(lat_env, fake_tables) -> None:
    table = main_definition_table("testlogicapp")
    fake_tables.add_table(
        table,
        {
            "PartitionKey": "PK",
            "RowKey": flowlookup_rowkey("wfOne"),
            "FlowName": "wfOne",
            "FlowId": "11111111-2222-3333-4444-555555555555",
        },
    )
    result = runner.invoke(
        app, ["tools", "generate-table-prefix", "-wf", "wfOne"]
    )
    assert result.exit_code == 0, result.output
    la_prefix = generate("testlogicapp")
    wf_prefix = generate("11111111-2222-3333-4444-555555555555")
    assert f"Logic App Prefix: {la_prefix}" in result.output
    assert f"Workflow Prefix: {wf_prefix}" in result.output
    assert f"Combined prefix: {la_prefix}{wf_prefix}" in result.output


def test_missing_workflow_errors(lat_env, fake_tables) -> None:
    table = main_definition_table("testlogicapp")
    fake_tables.add_table(table)
    result = runner.invoke(
        app, ["tools", "generate-table-prefix", "-wf", "ghost"]
    )
    assert result.exit_code != 0
    assert "cannot be found" in result.output


def test_missing_site_name_errors(monkeypatch, fake_tables) -> None:
    monkeypatch.delenv("WEBSITE_SITE_NAME", raising=False)
    result = runner.invoke(app, ["tools", "generate-table-prefix"])
    assert result.exit_code != 0
    assert "WEBSITE_SITE_NAME" in result.output
