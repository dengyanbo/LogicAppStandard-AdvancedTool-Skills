"""Tests for `lat runs generate-run-history-url`."""
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


def _run_row(run_id: str, created: str, ended: str, *, status: str = "Failed") -> dict:
    return {
        "PartitionKey": "PK",
        "RowKey": run_id,
        "FlowRunSequenceId": run_id,
        "Status": status,
        "CreatedTime": _dt.datetime.fromisoformat(created),
        "EndTime": _dt.datetime.fromisoformat(ended),
    }


def _payload_bytes(content: str) -> bytes:
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    return compression.compress(json.dumps({"inlinedContent": encoded}))


def _action_row(
    *,
    run_id: str,
    created: str,
    code: str = "Failed",
    outputs: str = '{"x":1}',
    error_msg: str = "",
) -> dict:
    return {
        "PartitionKey": "PK",
        "RowKey": f"action-{run_id}",
        "FlowRunSequenceId": run_id,
        "ActionName": "doStuff",
        "Status": "Failed",
        "Code": code,
        "CreatedTime": _dt.datetime.fromisoformat(created),
        "OutputsLinkCompressed": _payload_bytes(outputs),
        "InputsLinkCompressed": _payload_bytes("{}"),
        "Error": compression.compress(json.dumps({"message": error_msg, "code": code}))
        if error_msg
        else None,
    }


def test_emits_portal_urls(tmp_path: Path, lat_env, fake_tables) -> None:
    fake_tables.add_table(main_definition_table(LA), _flow_lookup())
    fake_tables.add_table(
        per_flow_table(LA, FLOW_ID, "runs"),
        _run_row(
            "08585432111111111111",
            "2024-05-15T10:00:00+00:00",
            "2024-05-15T10:05:00+00:00",
        ),
        _run_row(
            "08585432222222222222",
            "2024-05-15T11:00:00+00:00",
            "2024-05-15T11:01:00+00:00",
        ),
    )

    result = runner.invoke(
        app,
        [
            "runs", "generate-run-history-url",
            "-wf", "wfOne",
            "-d", "20240515",
            "-o", str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    out_file = tmp_path / "testlogicapp_wfOne_20240515_RunHistoryUrl.json"
    assert out_file.exists()
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert len(data) == 2
    assert {d["RunID"] for d in data} == {
        "08585432111111111111",
        "08585432222222222222",
    }
    for entry in data:
        assert "portal.azure.com" in entry["RunHistoryUrl"]
        assert entry["RunID"] in entry["RunHistoryUrl"]


def test_skips_non_failed_runs(tmp_path: Path, lat_env, fake_tables) -> None:
    fake_tables.add_table(main_definition_table(LA), _flow_lookup())
    fake_tables.add_table(
        per_flow_table(LA, FLOW_ID, "runs"),
        _run_row(
            "good", "2024-05-15T10:00:00+00:00",
            "2024-05-15T10:01:00+00:00", status="Succeeded",
        ),
        _run_row(
            "bad", "2024-05-15T11:00:00+00:00", "2024-05-15T11:01:00+00:00",
        ),
    )
    result = runner.invoke(
        app,
        [
            "runs", "generate-run-history-url",
            "-wf", "wfOne", "-d", "20240515", "-o", str(tmp_path),
        ],
    )
    assert result.exit_code == 0
    data = json.loads(
        (tmp_path / "testlogicapp_wfOne_20240515_RunHistoryUrl.json").read_text()
    )
    assert [d["RunID"] for d in data] == ["bad"]


def test_filter_keyword_in_outputs(tmp_path: Path, lat_env, fake_tables) -> None:
    fake_tables.add_table(main_definition_table(LA), _flow_lookup())
    fake_tables.add_table(
        per_flow_table(LA, FLOW_ID, "runs"),
        _run_row(
            "match-run", "2024-05-15T10:00:00+00:00",
            "2024-05-15T10:01:00+00:00",
        ),
        _run_row(
            "no-match", "2024-05-15T11:00:00+00:00",
            "2024-05-15T11:01:00+00:00",
        ),
    )
    fake_tables.add_table(
        per_day_action_table(LA, FLOW_ID, "20240515"),
        _action_row(
            run_id="match-run",
            created="2024-05-15T10:00:30+00:00",
            outputs="HEY MATCH-TOKEN",
        ),
        _action_row(
            run_id="no-match",
            created="2024-05-15T11:00:30+00:00",
            outputs="something else",
        ),
    )
    result = runner.invoke(
        app,
        [
            "runs", "generate-run-history-url",
            "-wf", "wfOne", "-d", "20240515",
            "-f", "MATCH-TOKEN",
            "-o", str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(
        (tmp_path / "testlogicapp_wfOne_20240515_RunHistoryUrl.json").read_text()
    )
    assert [d["RunID"] for d in data] == ["match-run"]


def test_no_failed_runs_errors(tmp_path: Path, lat_env, fake_tables) -> None:
    fake_tables.add_table(main_definition_table(LA), _flow_lookup())
    fake_tables.add_table(per_flow_table(LA, FLOW_ID, "runs"))
    result = runner.invoke(
        app,
        [
            "runs", "generate-run-history-url",
            "-wf", "wfOne", "-d", "20240515", "-o", str(tmp_path),
        ],
    )
    assert result.exit_code != 0
    assert "No failure runs detected" in result.output


def test_filter_matches_nothing(tmp_path: Path, lat_env, fake_tables) -> None:
    fake_tables.add_table(main_definition_table(LA), _flow_lookup())
    fake_tables.add_table(
        per_flow_table(LA, FLOW_ID, "runs"),
        _run_row(
            "lonely", "2024-05-15T10:00:00+00:00", "2024-05-15T10:01:00+00:00"
        ),
    )
    fake_tables.add_table(
        per_day_action_table(LA, FLOW_ID, "20240515"),
        _action_row(
            run_id="lonely", created="2024-05-15T10:00:30+00:00",
            outputs="no token here",
        ),
    )
    result = runner.invoke(
        app,
        [
            "runs", "generate-run-history-url",
            "-wf", "wfOne", "-d", "20240515", "-f", "ZZZ",
            "-o", str(tmp_path),
        ],
    )
    assert result.exit_code != 0
    assert "no failure run detect for filter" in result.output
