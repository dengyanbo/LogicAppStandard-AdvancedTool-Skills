"""Tests for `lat cleanup containers / tables / run-history`."""
from __future__ import annotations

from typer.testing import CliRunner

from lat.cli import app
from lat.storage.prefix import (
    flowlookup_rowkey,
    logic_app_prefix,
    main_definition_table,
    workflow_prefix,
)

runner = CliRunner()

LA = "testlogicapp"
FLOW_A = "11111111-aaaa-bbbb-cccc-aaaaaaaaaaaa"
FLOW_B = "22222222-bbbb-cccc-dddd-bbbbbbbbbbbb"


def _lookup_row(name: str, flow_id: str) -> dict:
    return {
        "PartitionKey": "PK",
        "RowKey": flowlookup_rowkey(name),
        "FlowName": name,
        "FlowId": flow_id,
    }


def _version_row(name: str, flow_id: str, seq: str) -> dict:
    return {
        "PartitionKey": "PK",
        "RowKey": f"MYEDGEENVIRONMENT_FLOWVERSION-{flow_id}-{seq}",
        "FlowName": name,
        "FlowId": flow_id,
        "FlowSequenceId": seq,
    }


def _name_with_date(prefix: str, date: str, tail: str) -> str:
    """Build a runtime resource name with date suffix at position 34."""
    # `prefix` is `flow<la_prefix(15)><wf_prefix(15)>` (length 34).
    return f"{prefix}{date}{tail}"


# ---------------------------------------------------------------------------
# CleanUpContainers
# ---------------------------------------------------------------------------


def test_cleanup_containers_la_scope_deletes_old(
    lat_env, fake_tables, fake_blobs
) -> None:
    fake_tables.add_table(main_definition_table(LA))
    la_pref = logic_app_prefix(LA)
    base = f"flow{la_pref}"
    # 4 containers, only 2 should be deleted (date < 20240515)
    fake_blobs.add_container(_name_with_date(base + workflow_prefix(FLOW_A), "20240514", "t1"))
    fake_blobs.add_container(_name_with_date(base + workflow_prefix(FLOW_A), "20240515", "t2"))
    fake_blobs.add_container(_name_with_date(base + workflow_prefix(FLOW_B), "20240101", "t3"))
    fake_blobs.add_container(_name_with_date(base + workflow_prefix(FLOW_B), "20240601", "t4"))
    # Noise that shouldn't match
    fake_blobs.add_container("unrelated-container")

    result = runner.invoke(
        app, ["cleanup", "containers", "-d", "20240515", "--yes"]
    )
    assert result.exit_code == 0, result.output
    assert len(fake_blobs.delete_calls) == 2
    deleted_dates = sorted(
        d[34:42] for d in fake_blobs.delete_calls if len(d) >= 42
    )
    assert deleted_dates == ["20240101", "20240514"]
    # The other 2 + noise still present
    assert "unrelated-container" in fake_blobs.containers


def test_cleanup_containers_workflow_scope_only_that_workflow(
    lat_env, fake_tables, fake_blobs
) -> None:
    fake_tables.add_table(
        main_definition_table(LA),
        _lookup_row("wfOne", FLOW_A),
        _version_row("wfOne", FLOW_A, "v1"),
    )
    la_pref = logic_app_prefix(LA)
    # One container for wfOne (FLOW_A), one for FLOW_B (different workflow).
    fake_blobs.add_container(
        _name_with_date(f"flow{la_pref}{workflow_prefix(FLOW_A)}", "20240101", "x")
    )
    fake_blobs.add_container(
        _name_with_date(f"flow{la_pref}{workflow_prefix(FLOW_B)}", "20240101", "y")
    )

    result = runner.invoke(
        app, ["cleanup", "containers", "-wf", "wfOne", "-d", "20240601", "--yes"]
    )
    assert result.exit_code == 0, result.output
    assert len(fake_blobs.delete_calls) == 1
    # Only the FLOW_A container was deleted
    assert workflow_prefix(FLOW_A) in fake_blobs.delete_calls[0]


def test_cleanup_containers_none_found_errors(
    lat_env, fake_tables, fake_blobs
) -> None:
    fake_tables.add_table(main_definition_table(LA))
    result = runner.invoke(
        app, ["cleanup", "containers", "-d", "20240515", "--yes"]
    )
    assert result.exit_code != 0
    assert "No blob containers found" in result.output


def test_cleanup_containers_bad_date(lat_env, fake_tables, fake_blobs) -> None:
    result = runner.invoke(
        app, ["cleanup", "containers", "-d", "2024-05-15", "--yes"]
    )
    assert result.exit_code != 0
    assert "yyyyMMdd" in result.output


# ---------------------------------------------------------------------------
# CleanUpTables
# ---------------------------------------------------------------------------


def test_cleanup_tables_filters_to_actions_and_variables(
    lat_env, fake_tables, fake_blobs
) -> None:
    fake_tables.add_table(main_definition_table(LA))
    la_pref = logic_app_prefix(LA)
    base = f"flow{la_pref}{workflow_prefix(FLOW_A)}"
    # 4 tables: actions/variables before, actions/variables after, plus
    # an unrelated `flows` table (must not be deleted).
    fake_tables.add_table(_name_with_date(base, "20240101", "t000000zactions"))
    fake_tables.add_table(_name_with_date(base, "20240101", "t000000zvariables"))
    fake_tables.add_table(_name_with_date(base, "20240601", "t000000zactions"))
    fake_tables.add_table(_name_with_date(base, "20240601", "t000000zvariables"))
    fake_tables.add_table(f"flow{la_pref}flows")  # main table; preserve
    fake_tables.add_table("unrelated")

    result = runner.invoke(
        app, ["cleanup", "tables", "-d", "20240515", "--yes"]
    )
    assert result.exit_code == 0, result.output
    # 2 deletions (old actions + old variables)
    remaining = {
        name
        for name in [
            _name_with_date(base, "20240101", "t000000zactions"),
            _name_with_date(base, "20240101", "t000000zvariables"),
            _name_with_date(base, "20240601", "t000000zactions"),
            _name_with_date(base, "20240601", "t000000zvariables"),
            f"flow{la_pref}flows",
            "unrelated",
        ]
        if name in fake_tables._tables  # noqa: SLF001
    }
    assert _name_with_date(base, "20240601", "t000000zactions") in remaining
    assert _name_with_date(base, "20240601", "t000000zvariables") in remaining
    assert f"flow{la_pref}flows" in remaining
    assert "unrelated" in remaining
    assert _name_with_date(base, "20240101", "t000000zactions") not in remaining
    assert _name_with_date(base, "20240101", "t000000zvariables") not in remaining


def test_cleanup_tables_none_found_errors(
    lat_env, fake_tables, fake_blobs
) -> None:
    fake_tables.add_table(main_definition_table(LA))
    result = runner.invoke(
        app, ["cleanup", "tables", "-d", "20240515", "--yes"]
    )
    assert result.exit_code != 0
    assert "No storage tables found" in result.output


# ---------------------------------------------------------------------------
# CleanUpRunHistory — composite
# ---------------------------------------------------------------------------


def test_cleanup_run_history_calls_both(lat_env, fake_tables, fake_blobs) -> None:
    fake_tables.add_table(main_definition_table(LA))
    la_pref = logic_app_prefix(LA)
    base = f"flow{la_pref}{workflow_prefix(FLOW_A)}"
    fake_tables.add_table(_name_with_date(base, "20240101", "t000000zactions"))
    fake_blobs.add_container(_name_with_date(base, "20240101", "container1"))

    result = runner.invoke(
        app, ["cleanup", "run-history", "-d", "20240515", "--yes"]
    )
    assert result.exit_code == 0, result.output
    assert len(fake_blobs.delete_calls) == 1
    # Table got deleted too
    assert _name_with_date(base, "20240101", "t000000zactions") not in fake_tables._tables  # noqa: SLF001
