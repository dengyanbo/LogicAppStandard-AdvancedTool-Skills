"""Tests for `lat runs retrieve-action-payload`."""
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
    action_name: str,
    run_id: str,
    created: str,
    inputs: str,
    outputs: str,
) -> dict:
    return {
        "PartitionKey": "PK",
        "RowKey": f"{action_name}-{run_id}",
        "ActionName": action_name,
        "FlowRunSequenceId": run_id,
        "CreatedTime": _dt.datetime.fromisoformat(created),
        "Timestamp": _dt.datetime.fromisoformat(created),
        "InputsLinkCompressed": _payload_bytes(inputs),
        "OutputsLinkCompressed": _payload_bytes(outputs),
        "RepeatItemIndex": None,
    }


def _trigger_row(
    *,
    trigger_name: str,
    run_id: str,
    created: str,
    inputs: str,
    outputs: str,
) -> dict:
    return {
        "PartitionKey": "PK",
        "RowKey": f"{trigger_name}-{run_id}",
        "TriggerName": trigger_name,
        "FlowRunSequenceId": run_id,
        "CreatedTime": _dt.datetime.fromisoformat(created),
        "Timestamp": _dt.datetime.fromisoformat(created),
        "InputsLinkCompressed": _payload_bytes(inputs),
        "OutputsLinkCompressed": _payload_bytes(outputs),
    }


def test_dumps_action_payloads(tmp_path: Path, lat_env, fake_tables) -> None:
    main = main_definition_table(LA)
    fake_tables.add_table(main, _flow_lookup())
    action_table = per_day_action_table(LA, FLOW_ID, "20240515")
    fake_tables.add_table(
        action_table,
        _action_row(
            action_name="My_Action",
            run_id="08585432198765432101",
            created="2024-05-15T10:00:00+00:00",
            inputs='{"x":1}',
            outputs='{"y":2}',
        ),
    )
    history_table = per_flow_table(LA, FLOW_ID, "histories")
    fake_tables.add_table(history_table)

    result = runner.invoke(
        app,
        [
            "runs", "retrieve-action-payload",
            "-wf", "wfOne",
            "-d", "20240515",
            "-a", "My_Action",
            "-o", str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    out_file = tmp_path / "wfOne_20240515_My_Action.json"
    assert out_file.exists()
    payload = json.loads(out_file.read_text(encoding="utf-8"))
    assert len(payload) == 1
    assert payload[0]["ActionName"] == "My_Action"
    assert payload[0]["FlowRunSequenceId"] == "08585432198765432101"
    assert payload[0]["InputContent"] == '{"x":1}'
    assert payload[0]["OutputContent"] == '{"y":2}'


def test_falls_back_to_trigger_table(tmp_path: Path, lat_env, fake_tables) -> None:
    main = main_definition_table(LA)
    fake_tables.add_table(main, _flow_lookup())
    fake_tables.add_table(per_day_action_table(LA, FLOW_ID, "20240515"))
    history_table = per_flow_table(LA, FLOW_ID, "histories")
    fake_tables.add_table(
        history_table,
        _trigger_row(
            trigger_name="manual",
            run_id="08585432198765432101",
            created="2024-05-15T09:30:00+00:00",
            inputs='{"trig":"in"}',
            outputs='{"trig":"out"}',
        ),
    )

    result = runner.invoke(
        app,
        [
            "runs", "retrieve-action-payload",
            "-wf", "wfOne", "-d", "20240515", "-a", "manual",
            "-o", str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(
        (tmp_path / "wfOne_20240515_manual.json").read_text(encoding="utf-8")
    )
    assert len(payload) == 1
    assert payload[0]["ActionName"] == "manual"


def test_no_records_errors(tmp_path: Path, lat_env, fake_tables) -> None:
    main = main_definition_table(LA)
    fake_tables.add_table(main, _flow_lookup())
    fake_tables.add_table(per_day_action_table(LA, FLOW_ID, "20240515"))
    fake_tables.add_table(per_flow_table(LA, FLOW_ID, "histories"))

    result = runner.invoke(
        app,
        [
            "runs", "retrieve-action-payload",
            "-wf", "wfOne", "-d", "20240515", "-a", "missing",
            "-o", str(tmp_path),
        ],
    )
    assert result.exit_code != 0
    assert "No records found" in result.output


def test_bad_date_format(tmp_path: Path, lat_env, fake_tables) -> None:
    main = main_definition_table(LA)
    fake_tables.add_table(main, _flow_lookup())
    result = runner.invoke(
        app,
        [
            "runs", "retrieve-action-payload",
            "-wf", "wfOne", "-d", "2024-05-15", "-a", "x",
            "-o", str(tmp_path),
        ],
    )
    assert result.exit_code != 0
    assert "yyyyMMdd" in result.output
