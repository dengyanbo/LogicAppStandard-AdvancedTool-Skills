"""Tests for `lat workflow merge-run-history`."""
from __future__ import annotations

from typer.testing import CliRunner

from lat.cli import app
from lat.storage.prefix import (
    flowlookup_rowkey,
    logic_app_prefix,
    main_definition_table,
    partition_key,
    workflow_prefix,
)

runner = CliRunner()

LA = "testlogicapp"
SOURCE_ID = "aaaaaaaa-1111-1111-1111-aaaaaaaaaaaa"
TARGET_ID = "bbbbbbbb-2222-2222-2222-bbbbbbbbbbbb"


def _flow_lookup(name: str, flow_id: str) -> dict:
    return {
        "PartitionKey": "PK",
        "RowKey": flowlookup_rowkey(name),
        "FlowName": name,
        "FlowId": flow_id,
    }


def _main_row(seq: str, flow_name: str, flow_id: str) -> dict:
    rk = f"MYEDGEENVIRONMENT_FLOWVERSION-{flow_id.upper()}-{seq}"
    return {
        "PartitionKey": partition_key(rk),
        "RowKey": rk,
        "FlowName": flow_name,
        "FlowId": flow_id,
        "FlowSequenceId": seq,
    }


def _runs_row(rk_suffix: str, flow_id: str) -> dict:
    rk = f"RUN-{flow_id.upper()}-{rk_suffix}"
    return {
        "PartitionKey": partition_key(rk),
        "RowKey": rk,
        "FlowId": flow_id,
        "Status": "Succeeded",
    }


def test_merge_run_history_rekeys_main_and_runs(lat_env, fake_tables) -> None:
    main_table_name = main_definition_table(LA)
    main_table = fake_tables.add_table(
        main_table_name,
        # Source workflow with 2 main rows
        _flow_lookup("sourceWF", SOURCE_ID),
        _main_row("v1", "sourceWF", SOURCE_ID),
        _main_row("v2", "sourceWF", SOURCE_ID),
        # Target workflow already exists with 1 main row
        _flow_lookup("targetWF", TARGET_ID),
        _main_row("t1", "targetWF", TARGET_ID),
    )
    la_pref = logic_app_prefix(LA)
    src_pref = f"flow{la_pref}{workflow_prefix(SOURCE_ID)}"
    tgt_pref = f"flow{la_pref}{workflow_prefix(TARGET_ID)}"

    src_runs = fake_tables.add_table(
        f"{src_pref}runs",
        _runs_row("r1", SOURCE_ID),
        _runs_row("r2", SOURCE_ID),
    )
    tgt_runs = fake_tables.add_table(f"{tgt_pref}runs")

    # Action table within date range
    src_actions = fake_tables.add_table(
        f"{src_pref}20240515t000000zactions",
        {
            "PartitionKey": partition_key(f"ACT-{SOURCE_ID.upper()}-a"),
            "RowKey": f"ACT-{SOURCE_ID.upper()}-a",
            "FlowId": SOURCE_ID,
            "ActionName": "doStuff",
        },
    )
    tgt_actions = fake_tables.add_table(f"{tgt_pref}20240515t000000zactions")

    # Action table OUTSIDE date range — should not be merged
    src_old = fake_tables.add_table(
        f"{src_pref}20230101t000000zactions",
        {
            "PartitionKey": "PK",
            "RowKey": f"ACT-{SOURCE_ID.upper()}-old",
            "FlowId": SOURCE_ID,
        },
    )

    result = runner.invoke(
        app,
        [
            "workflow", "merge-run-history",
            "-s", "sourceWF", "-t", "targetWF",
            "--start", "20240101", "--end", "20240601",
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output

    # FLOWLOOKUP row's RK doesn't include the FlowId, so source's lookup row
    # was OVERWRITTEN in place (FlowId now == TARGET_ID, FlowName updated).
    lookup = main_table.rows[("PK", flowlookup_rowkey("sourceWF"))]
    assert lookup["FlowId"] == TARGET_ID
    assert lookup["FlowName"] == "targetWF"

    # FLOWVERSION rows: RK contains SOURCE_ID.upper(), so the upsert wrote
    # a NEW row (with target's RK + target FlowId) while the source row is
    # untouched — matches .NET behavior.
    target_versions = [
        r
        for r in main_table.rows.values()
        if r.get("FlowId") == TARGET_ID
        and TARGET_ID.upper() in str(r.get("RowKey", ""))
        and r.get("FlowSequenceId") in {"v1", "v2"}
    ]
    assert len(target_versions) == 2
    # And the original source FLOWVERSION rows still exist.
    source_versions = [
        r
        for r in main_table.rows.values()
        if r.get("FlowId") == SOURCE_ID and r.get("FlowSequenceId") in {"v1", "v2"}
    ]
    assert len(source_versions) == 2

    # Runs table: target runs table now has the 2 re-keyed rows.
    target_runs_keys = [r["RowKey"] for r in tgt_runs.rows.values()]
    assert any(TARGET_ID.upper() in rk for rk in target_runs_keys)
    assert all(SOURCE_ID.upper() not in rk for rk in target_runs_keys)
    # Each target runs row's PartitionKey was recomputed from the new RowKey
    for r in tgt_runs.rows.values():
        assert r["PartitionKey"] == partition_key(r["RowKey"])

    # Action table within range was merged
    assert len(tgt_actions.rows) == 1
    # Action table outside range was NOT merged (no row in any target table)
    out_of_range_target = fake_tables.add_table(
        f"{tgt_pref}20230101t000000zactions"
    )
    assert len(out_of_range_target.rows) == 0


def test_merge_run_history_target_missing_errors(lat_env, fake_tables) -> None:
    fake_tables.add_table(
        main_definition_table(LA),
        _flow_lookup("sourceWF", SOURCE_ID),
    )
    result = runner.invoke(
        app,
        [
            "workflow", "merge-run-history",
            "-s", "sourceWF", "-t", "ghost",
            "--start", "20240101", "--end", "20240601",
            "--yes",
        ],
    )
    assert result.exit_code != 0
    assert "Cannot find existing workflow" in result.output


def test_merge_run_history_same_id_errors(lat_env, fake_tables) -> None:
    # Source and target both resolve to the SAME flow id (degenerate input)
    fake_tables.add_table(
        main_definition_table(LA),
        _flow_lookup("sourceWF", SOURCE_ID),
        _flow_lookup("targetWF", SOURCE_ID),
    )
    result = runner.invoke(
        app,
        [
            "workflow", "merge-run-history",
            "-s", "sourceWF", "-t", "targetWF",
            "--start", "20240101", "--end", "20240601",
            "--yes",
        ],
    )
    assert result.exit_code != 0
    assert "same" in result.output.lower()


def test_merge_run_history_creates_missing_target_tables(lat_env, fake_tables) -> None:
    """Repro of the real-Azure bug: when the target workflow has never been
    triggered, its per-flow runs/flows/histories tables don't exist yet.
    `_merge_table` must auto-create them rather than crash with TableNotFound
    on the first submit_transaction call.
    """
    main_table_name = main_definition_table(LA)
    fake_tables.add_table(
        main_table_name,
        _flow_lookup("sourceWF", SOURCE_ID),
        _main_row("v1", "sourceWF", SOURCE_ID),
        _flow_lookup("targetWF", TARGET_ID),
        _main_row("t1", "targetWF", TARGET_ID),
    )
    la_pref = logic_app_prefix(LA)
    src_pref = f"flow{la_pref}{workflow_prefix(SOURCE_ID)}"
    tgt_pref = f"flow{la_pref}{workflow_prefix(TARGET_ID)}"

    # Source runs table has data
    fake_tables.add_table(
        f"{src_pref}runs",
        _runs_row("r1", SOURCE_ID),
    )
    # Target runs table is MISSING on the storage account (never triggered)
    tgt_runs = fake_tables.get_table_client(f"{tgt_pref}runs")
    tgt_runs.missing = True

    result = runner.invoke(
        app,
        [
            "workflow", "merge-run-history",
            "-s", "sourceWF", "-t", "targetWF",
            "--start", "20240101", "--end", "20240601",
            "--yes",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "TableNotFound" not in result.output
    assert "Traceback" not in result.output
    # Target table was auto-created (missing flag flipped) and got the row.
    assert tgt_runs.missing is False
    assert tgt_runs.create_table_calls == 1
    target_runs_keys = [r["RowKey"] for r in tgt_runs.rows.values()]
    assert len(target_runs_keys) == 1
    assert TARGET_ID.upper() in target_runs_keys[0]
