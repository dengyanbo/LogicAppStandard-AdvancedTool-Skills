"""Tests for `lat runs search-in-history`, `retrieve-failures-*`, `cancel-runs`."""
from __future__ import annotations

import base64
import datetime as _dt
import json
from pathlib import Path

from typer.testing import CliRunner

from lat.cli import app
from lat.storage import compression
from lat.storage.prefix import (
    flowlookup_rowkey,
    main_definition_table,
    per_day_action_table,
    per_flow_table,
)

runner = CliRunner()

FLOW_ID = "ffffffff-1111-2222-3333-444444444444"
LA = "testlogicapp"


def _flow_lookup() -> dict:
    return {
        "PartitionKey": "PK",
        "RowKey": flowlookup_rowkey("wfOne"),
        "FlowName": "wfOne",
        "FlowId": FLOW_ID,
    }


def _payload_bytes(content: str) -> bytes:
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    return compression.compress(json.dumps({"inlinedContent": encoded}))


def _action_row(
    *,
    rk: str,
    action_name: str,
    run_id: str,
    created: str,
    inputs: str = "{}",
    outputs: str = "{}",
    status: str = "Succeeded",
    error_msg: str | None = None,
    code: str | None = None,
) -> dict:
    row = {
        "PartitionKey": "PK",
        "RowKey": rk,
        "ActionName": action_name,
        "FlowRunSequenceId": run_id,
        "CreatedTime": _dt.datetime.fromisoformat(created),
        "Timestamp": _dt.datetime.fromisoformat(created),
        "InputsLinkCompressed": _payload_bytes(inputs),
        "OutputsLinkCompressed": _payload_bytes(outputs),
        "Status": status,
        "Code": code,
    }
    if error_msg is not None:
        row["Error"] = compression.compress(
            json.dumps({"message": error_msg, "code": code or "Failed"})
        )
    return row


# ---------------------------------------------------------------------------
# search-in-history
# ---------------------------------------------------------------------------


def test_search_in_history_finds_keyword(tmp_path: Path, lat_env, fake_tables) -> None:
    fake_tables.add_table(main_definition_table(LA), _flow_lookup())
    fake_tables.add_table(
        per_day_action_table(LA, FLOW_ID, "20240515"),
        _action_row(
            rk="r1", action_name="a1", run_id="run1",
            created="2024-05-15T10:00:00+00:00", inputs="hello UNIQUE",
        ),
        _action_row(
            rk="r2", action_name="a2", run_id="run2",
            created="2024-05-15T11:00:00+00:00", outputs="world",
        ),
    )
    result = runner.invoke(
        app,
        [
            "runs", "search-in-history", "-wf", "wfOne", "-d", "20240515",
            "-k", "UNIQUE", "-o", str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    out_file = tmp_path / "testlogicapp_wfOne_20240515_SearchResults.json"
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert list(data.keys()) == ["run1"]
    assert len(data["run1"]) == 1


def test_search_in_history_no_match_errors(tmp_path: Path, lat_env, fake_tables) -> None:
    fake_tables.add_table(main_definition_table(LA), _flow_lookup())
    fake_tables.add_table(
        per_day_action_table(LA, FLOW_ID, "20240515"),
        _action_row(
            rk="r1", action_name="a1", run_id="run1",
            created="2024-05-15T10:00:00+00:00", inputs="hello",
        ),
    )
    result = runner.invoke(
        app,
        [
            "runs", "search-in-history", "-wf", "wfOne", "-d", "20240515",
            "-k", "GHOST", "-o", str(tmp_path),
        ],
    )
    assert result.exit_code != 0
    assert "No run hisotry input/output found" in result.output


# ---------------------------------------------------------------------------
# retrieve-failures-by-date
# ---------------------------------------------------------------------------


def test_retrieve_failures_by_date_filters_correctly(
    tmp_path: Path, lat_env, fake_tables
) -> None:
    fake_tables.add_table(main_definition_table(LA), _flow_lookup())
    fake_tables.add_table(
        per_day_action_table(LA, FLOW_ID, "20240515"),
        _action_row(
            rk="ok", action_name="ok", run_id="run1",
            created="2024-05-15T10:00:00+00:00", status="Succeeded",
        ),
        _action_row(
            rk="real", action_name="real", run_id="run2",
            created="2024-05-15T11:00:00+00:00", status="Failed",
            error_msg="Boom", code="InvalidRequest",
        ),
        # Control-action failure: should be filtered out by the
        # "An action failed. No dependent actions succeeded." rule.
        _action_row(
            rk="dep", action_name="ForEach", run_id="run3",
            created="2024-05-15T12:00:00+00:00", status="Failed",
            error_msg="An action failed. No dependent actions succeeded.",
        ),
    )
    result = runner.invoke(
        app,
        [
            "runs", "retrieve-failures-by-date",
            "-wf", "wfOne", "-d", "20240515", "-o", str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    out_file = tmp_path / "testlogicapp_wfOne_20240515_FailureLogs.json"
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert list(data.keys()) == ["run2"]
    assert data["run2"][0]["Error"]["code"] == "InvalidRequest"


def test_retrieve_failures_by_date_no_failures_errors(
    tmp_path: Path, lat_env, fake_tables
) -> None:
    fake_tables.add_table(main_definition_table(LA), _flow_lookup())
    fake_tables.add_table(per_day_action_table(LA, FLOW_ID, "20240515"))
    result = runner.invoke(
        app,
        [
            "runs", "retrieve-failures-by-date",
            "-wf", "wfOne", "-d", "20240515", "-o", str(tmp_path),
        ],
    )
    assert result.exit_code != 0
    assert "No failure actions" in result.output


# ---------------------------------------------------------------------------
# retrieve-failures-by-run
# ---------------------------------------------------------------------------


def test_retrieve_failures_by_run_uses_run_date(
    tmp_path: Path, lat_env, fake_tables
) -> None:
    fake_tables.add_table(main_definition_table(LA), _flow_lookup())
    fake_tables.add_table(
        per_flow_table(LA, FLOW_ID, "runs"),
        {
            "PartitionKey": "PK",
            "RowKey": "run-X",
            "FlowRunSequenceId": "run-X",
            "Status": "Failed",
            "CreatedTime": _dt.datetime.fromisoformat(
                "2024-07-04T08:00:00+00:00"
            ),
            "EndTime": _dt.datetime.fromisoformat(
                "2024-07-04T08:05:00+00:00"
            ),
        },
    )
    fake_tables.add_table(
        per_day_action_table(LA, FLOW_ID, "20240704"),
        _action_row(
            rk="a1", action_name="step1", run_id="run-X",
            created="2024-07-04T08:01:00+00:00", status="Failed",
            error_msg="x failed",
        ),
    )
    result = runner.invoke(
        app,
        [
            "runs", "retrieve-failures-by-run",
            "-wf", "wfOne", "-r", "run-X", "-o", str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    out_file = tmp_path / "testlogicapp_wfOne_run-X_FailureLogs.json"
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert list(data.keys()) == ["run-X"]


def test_retrieve_failures_by_run_unknown_run_errors(
    tmp_path: Path, lat_env, fake_tables
) -> None:
    fake_tables.add_table(main_definition_table(LA), _flow_lookup())
    fake_tables.add_table(per_flow_table(LA, FLOW_ID, "runs"))
    result = runner.invoke(
        app,
        [
            "runs", "retrieve-failures-by-run",
            "-wf", "wfOne", "-r", "missing", "-o", str(tmp_path),
        ],
    )
    assert result.exit_code != 0
    assert "Cannot find workflow run" in result.output


# ---------------------------------------------------------------------------
# cancel-runs
# ---------------------------------------------------------------------------


def _runs_table_row(run_id: str, status: str) -> dict:
    return {
        "PartitionKey": "PK",
        "RowKey": run_id,
        "FlowRunSequenceId": run_id,
        "Status": status,
    }


def test_cancel_runs_flips_status_to_cancelled(
    lat_env, fake_tables
) -> None:
    fake_tables.add_table(main_definition_table(LA), _flow_lookup())
    runs = fake_tables.add_table(
        per_flow_table(LA, FLOW_ID, "runs"),
        _runs_table_row("r1", "Running"),
        _runs_table_row("r2", "Waiting"),
        _runs_table_row("r3", "Succeeded"),  # untouched
    )
    result = runner.invoke(
        app, ["runs", "cancel-runs", "-wf", "wfOne", "--yes"]
    )
    assert result.exit_code == 0, result.output
    assert "Found 2 run(s)" in result.output
    assert "2 runs cancelled sucessfully" in result.output
    assert runs.rows[("PK", "r1")]["Status"] == "Cancelled"
    assert runs.rows[("PK", "r2")]["Status"] == "Cancelled"
    assert runs.rows[("PK", "r3")]["Status"] == "Succeeded"


def test_cancel_runs_empty_errors(lat_env, fake_tables) -> None:
    fake_tables.add_table(main_definition_table(LA), _flow_lookup())
    fake_tables.add_table(per_flow_table(LA, FLOW_ID, "runs"))
    result = runner.invoke(
        app, ["runs", "cancel-runs", "-wf", "wfOne", "--yes"]
    )
    assert result.exit_code != 0
    assert "no running/waiting runs" in result.output.lower()


def test_cancel_runs_requires_confirmation_without_yes(
    lat_env, fake_tables
) -> None:
    fake_tables.add_table(main_definition_table(LA), _flow_lookup())
    fake_tables.add_table(
        per_flow_table(LA, FLOW_ID, "runs"),
        _runs_table_row("r1", "Running"),
    )
    # Decline the confirmation
    result = runner.invoke(
        app, ["runs", "cancel-runs", "-wf", "wfOne"], input="n\n"
    )
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Graceful degradation when per-day / per-flow tables don't exist on the
# storage account. Reproduces the real-Azure bug where running e.g.
# `retrieve-failures-by-date` against a date with no traffic raised a raw
# ResourceNotFoundError ("TableNotFound") stack trace instead of the
# friendly "no records" message. Fix is in storage/tables.query_paged.
# ---------------------------------------------------------------------------


def test_retrieve_failures_by_date_missing_action_table_is_graceful(
    tmp_path: Path, lat_env, fake_tables
) -> None:
    fake_tables.add_table(main_definition_table(LA), _flow_lookup())
    missing = fake_tables.get_table_client(per_day_action_table(LA, FLOW_ID, "20240515"))
    missing.missing = True
    result = runner.invoke(
        app,
        [
            "runs", "retrieve-failures-by-date",
            "-wf", "wfOne", "-d", "20240515", "-o", str(tmp_path),
        ],
    )
    # Friendly user-facing exit (no stack trace).
    assert result.exit_code != 0
    assert "TableNotFound" not in result.output
    assert "Traceback" not in result.output
    assert "No failure actions" in result.output


def test_search_in_history_missing_action_table_is_graceful(
    tmp_path: Path, lat_env, fake_tables
) -> None:
    fake_tables.add_table(main_definition_table(LA), _flow_lookup())
    missing = fake_tables.get_table_client(per_day_action_table(LA, FLOW_ID, "20240515"))
    missing.missing = True
    result = runner.invoke(
        app,
        [
            "runs", "search-in-history",
            "-wf", "wfOne", "-d", "20240515",
            "-k", "anything", "-o", str(tmp_path),
        ],
    )
    assert "TableNotFound" not in result.output
    assert "Traceback" not in result.output
