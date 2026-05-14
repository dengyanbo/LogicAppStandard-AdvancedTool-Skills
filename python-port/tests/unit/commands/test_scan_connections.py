"""Tests for `lat validate scan-connections`."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from lat import arm
from lat.cli import app
from lat.commands.scan_connections import (
    _collect_appsetting_refs,
    _collect_connections_from_actions,
    collect_declared_connections,
    collect_referenced_connections,
)

runner = CliRunner()


def _make_workflow(root: Path, name: str, definition: dict) -> Path:
    """Create root/<name>/workflow.json with the given definition wrapper."""
    wf_dir = root / name
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / "workflow.json").write_text(
        json.dumps({"definition": definition}), encoding="utf-8"
    )
    return wf_dir


def _make_connections_json(root: Path, *, api: list[str] | None = None, sp: list[str] | None = None) -> Path:
    data = {
        "managedApiConnections": {n: {} for n in (api or [])},
        "serviceProviderConnections": {n: {} for n in (sp or [])},
    }
    p = root / "connections.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Action parser
# ---------------------------------------------------------------------------


def test_collect_finds_flat_api_connection() -> None:
    actions = {
        "Send_email": {
            "type": "ApiConnection",
            "inputs": {"host": {"connection": {"referenceName": "office365"}}},
        }
    }
    assert _collect_connections_from_actions(actions) == {("ApiConnection", "office365")}


def test_collect_finds_flat_service_provider() -> None:
    actions = {
        "Get_blob": {
            "type": "ServiceProvider",
            "inputs": {"serviceProviderConfiguration": {"connectionName": "azureBlob_1"}},
        }
    }
    assert _collect_connections_from_actions(actions) == {("ServiceProvider", "azureBlob_1")}


def test_collect_recurses_into_if() -> None:
    actions = {
        "Condition": {
            "type": "If",
            "actions": {
                "Yes_branch": {
                    "type": "ApiConnection",
                    "inputs": {"host": {"connection": {"referenceName": "office365"}}},
                }
            },
            "else": {
                "actions": {
                    "No_branch": {
                        "type": "ServiceProvider",
                        "inputs": {
                            "serviceProviderConfiguration": {"connectionName": "sb_1"}
                        },
                    }
                }
            },
        }
    }
    assert _collect_connections_from_actions(actions) == {
        ("ApiConnection", "office365"),
        ("ServiceProvider", "sb_1"),
    }


def test_collect_recurses_into_switch() -> None:
    actions = {
        "Route": {
            "type": "Switch",
            "cases": {
                "Case_A": {
                    "actions": {
                        "A1": {
                            "type": "ApiConnection",
                            "inputs": {
                                "host": {"connection": {"referenceName": "a-conn"}}
                            },
                        }
                    }
                }
            },
            "default": {
                "actions": {
                    "D1": {
                        "type": "ApiConnection",
                        "inputs": {
                            "host": {"connection": {"referenceName": "d-conn"}}
                        },
                    }
                }
            },
        }
    }
    assert _collect_connections_from_actions(actions) == {
        ("ApiConnection", "a-conn"),
        ("ApiConnection", "d-conn"),
    }


def test_collect_recurses_into_until_scope_foreach() -> None:
    actions = {
        f"Block_{i}": {
            "type": kind,
            "actions": {
                "Inner": {
                    "type": "ApiConnection",
                    "inputs": {"host": {"connection": {"referenceName": f"conn-{kind}"}}},
                }
            },
        }
        for i, kind in enumerate(["Until", "Scope", "Foreach"])
    }
    expected = {
        ("ApiConnection", "conn-Until"),
        ("ApiConnection", "conn-Scope"),
        ("ApiConnection", "conn-Foreach"),
    }
    assert _collect_connections_from_actions(actions) == expected


def test_collect_ignores_unknown_action_types() -> None:
    actions = {
        "Compose": {"type": "Compose", "inputs": "literal"},
        "Wait": {"type": "Wait", "inputs": {"interval": {"count": 5}}},
    }
    assert _collect_connections_from_actions(actions) == set()


# ---------------------------------------------------------------------------
# End-to-end via CLI
# ---------------------------------------------------------------------------


def test_scan_no_orphans(tmp_path: Path) -> None:
    _make_workflow(
        tmp_path,
        "wf1",
        {
            "actions": {
                "A": {
                    "type": "ApiConnection",
                    "inputs": {"host": {"connection": {"referenceName": "office365"}}},
                }
            }
        },
    )
    _make_connections_json(tmp_path, api=["office365"])
    result = runner.invoke(app, ["validate", "scan-connections", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "There's no unsed connections." in result.stdout


def test_scan_reports_orphans(tmp_path: Path) -> None:
    _make_workflow(
        tmp_path,
        "wf1",
        {
            "actions": {
                "A": {
                    "type": "ApiConnection",
                    "inputs": {"host": {"connection": {"referenceName": "office365"}}},
                }
            }
        },
    )
    _make_connections_json(
        tmp_path,
        api=["office365", "orphan-api"],
        sp=["orphan-sp"],
    )
    result = runner.invoke(app, ["validate", "scan-connections", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "Following connections are not used" in result.stdout
    assert "orphan-api" in result.stdout
    assert "orphan-sp" in result.stdout
    # office365 IS used, so it should not be listed under orphans table.
    # (Just verify the orphan strings are mentioned — full table parsing is rich's concern.)


def test_scan_missing_connections_json(tmp_path: Path) -> None:
    _make_workflow(tmp_path, "wf1", {"actions": {}})
    result = runner.invoke(app, ["validate", "scan-connections", "--root", str(tmp_path)])
    assert result.exit_code != 0
    assert "Cannot find connections.json" in result.output


def test_scan_apply_removes_orphans_and_pushes_appsettings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--apply: orphans deleted from connections.json + app-settings push via ARM."""
    # Two API conns (one orphan), one SP orphan referencing two app settings.
    data = {
        "managedApiConnections": {
            "used-api": {},
            "orphan-api": {},
        },
        "serviceProviderConnections": {
            "orphan-sp": {
                "parameterValues": {
                    "endpoint": "@appsetting('SP_ENDPOINT')",
                    "key": "@appsetting('SP_KEY')",
                    "static": "plain-value",
                }
            }
        },
    }
    (tmp_path / "connections.json").write_text(json.dumps(data), encoding="utf-8")
    # One workflow that uses ONLY used-api
    wf_dir = tmp_path / "wf1"
    wf_dir.mkdir()
    (wf_dir / "workflow.json").write_text(
        json.dumps(
            {
                "definition": {
                    "actions": {
                        "A": {
                            "type": "ApiConnection",
                            "inputs": {
                                "host": {"connection": {"referenceName": "used-api"}}
                            },
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    # Mock ARM
    put_calls: list[dict[str, str]] = []
    monkeypatch.setattr(
        arm, "get_appsettings", lambda: {
            "SP_ENDPOINT": "v1",
            "SP_KEY": "v2",
            "KEEP_ME": "v3",
        }
    )
    monkeypatch.setattr(arm, "put_appsettings", lambda props: put_calls.append(dict(props)))

    result = runner.invoke(
        app,
        ["validate", "scan-connections", "--root", str(tmp_path), "--apply", "--yes"],
    )
    assert result.exit_code == 0, result.stdout

    # connections.json updated
    after = json.loads((tmp_path / "connections.json").read_text(encoding="utf-8"))
    assert after["managedApiConnections"] == {"used-api": {}}
    assert after["serviceProviderConnections"] == {}

    # ARM put called once with only the unrelated setting
    assert put_calls == [{"KEEP_ME": "v3"}]
    assert "have been cleaned up" in result.stdout


def test_scan_apply_no_orphans_no_arm_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--apply with no orphans is a no-op (no ARM call)."""
    _make_workflow(
        tmp_path,
        "wf1",
        {
            "actions": {
                "A": {
                    "type": "ApiConnection",
                    "inputs": {"host": {"connection": {"referenceName": "used"}}},
                }
            }
        },
    )
    _make_connections_json(tmp_path, api=["used"])

    arm_called: list[bool] = []
    monkeypatch.setattr(arm, "get_appsettings", lambda: arm_called.append(True) or {})
    monkeypatch.setattr(arm, "put_appsettings", lambda props: arm_called.append(True))

    result = runner.invoke(
        app,
        ["validate", "scan-connections", "--root", str(tmp_path), "--apply", "--yes"],
    )
    assert result.exit_code == 0
    assert arm_called == []


def test_scan_apply_sp_without_appsettings_skips_arm_put(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Orphan SP with no @appsetting refs: connections.json mutated, no ARM put."""
    data = {
        "managedApiConnections": {},
        "serviceProviderConnections": {
            "orphan-sp": {"parameterValues": {"key": "literal-string"}}
        },
    }
    (tmp_path / "connections.json").write_text(json.dumps(data), encoding="utf-8")
    (tmp_path / "wf1").mkdir()
    (tmp_path / "wf1" / "workflow.json").write_text(
        json.dumps({"definition": {"actions": {}}}), encoding="utf-8"
    )

    put_calls: list[dict] = []
    monkeypatch.setattr(arm, "get_appsettings", lambda: {"OTHER": "v"})
    monkeypatch.setattr(arm, "put_appsettings", lambda p: put_calls.append(p))

    result = runner.invoke(
        app,
        ["validate", "scan-connections", "--root", str(tmp_path), "--apply", "--yes"],
    )
    assert result.exit_code == 0
    # connections.json mutated
    after = json.loads((tmp_path / "connections.json").read_text(encoding="utf-8"))
    assert after["serviceProviderConnections"] == {}
    # No app-settings push (nothing to remove)
    assert put_calls == []


def test_scan_apply_requires_confirmation_without_yes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_workflow(tmp_path, "wf1", {"actions": {}})
    _make_connections_json(tmp_path, api=["orphan"])

    put_calls: list[dict] = []
    monkeypatch.setattr(arm, "get_appsettings", lambda: {})
    monkeypatch.setattr(arm, "put_appsettings", lambda p: put_calls.append(p))

    # Decline at the prompt
    result = runner.invoke(
        app,
        ["validate", "scan-connections", "--root", str(tmp_path), "--apply"],
        input="n\n",
    )
    assert result.exit_code != 0
    # connections.json NOT mutated
    after = json.loads((tmp_path / "connections.json").read_text(encoding="utf-8"))
    assert "orphan" in after["managedApiConnections"]
    assert put_calls == []


def test_collect_appsetting_refs_finds_all_in_string_values() -> None:
    """Detects every @appsetting reference, ignores literals."""
    params = {
        "endpoint": "@appsetting('VAR_A')",
        "key": "@appsetting('VAR_B')",
        "literal": "no-substitution-here",
        "nested": {"ignored": "@appsetting('VAR_C')"},  # only top-level strings parsed
    }
    refs = _collect_appsetting_refs(params)
    assert refs == {"VAR_A", "VAR_B"}


def test_collect_appsetting_refs_handles_non_dict() -> None:
    assert _collect_appsetting_refs(None) == set()
    assert _collect_appsetting_refs("not-a-dict") == set()


def test_collect_referenced_skips_invalid_json(tmp_path: Path) -> None:
    """Malformed workflow.json files are skipped (no crash)."""
    (tmp_path / "wf-good").mkdir()
    (tmp_path / "wf-good" / "workflow.json").write_text(
        json.dumps({"definition": {"actions": {}}}), encoding="utf-8"
    )
    (tmp_path / "wf-bad").mkdir()
    (tmp_path / "wf-bad" / "workflow.json").write_text("{garbage", encoding="utf-8")
    found = collect_referenced_connections(tmp_path)
    assert found == set()


def test_declared_connections_handles_missing_sections(tmp_path: Path) -> None:
    """connections.json may lack managedApiConnections or serviceProviderConnections."""
    (tmp_path / "connections.json").write_text("{}", encoding="utf-8")
    assert collect_declared_connections(tmp_path / "connections.json") == set()
