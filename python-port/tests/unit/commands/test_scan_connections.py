"""Tests for `lat validate scan-connections`."""
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from lat.cli import app
from lat.commands.scan_connections import (
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


def test_scan_apply_flag_not_implemented(tmp_path: Path) -> None:
    """--apply currently raises BadParameter until ARM client is fleshed out."""
    _make_workflow(tmp_path, "wf1", {"actions": {}})
    _make_connections_json(tmp_path, api=["orphan"])
    result = runner.invoke(
        app,
        ["validate", "scan-connections", "--root", str(tmp_path), "--apply"],
    )
    assert result.exit_code != 0
    assert "not yet implemented" in result.output


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
