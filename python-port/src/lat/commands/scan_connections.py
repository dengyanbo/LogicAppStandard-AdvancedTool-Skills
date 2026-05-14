"""`ScanConnections` — find connections declared but not referenced by any workflow.

Mirrors `Operations/ScanConnections.cs`. Walks `<root>/<workflow>/workflow.json`
files under wwwroot, collects connection references (recursing into control
actions: If/Switch/Until/Scope/Foreach), then diffs against the connections
declared in `<root>/connections.json`.

With `--apply`: also removes orphan connections from connections.json and
deletes any `@appsetting('NAME')` references they used from the site's
app settings (pushed via ARM). The Python port now matches the full .NET
behavior.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .. import arm
from ..settings import settings

console = Console()

# Control-flow action types that wrap nested actions (mirrors Enum.ActionType + ScanConnections.cs).
_CONTROL_ACTIONS = {"If", "Switch", "Until", "Scope", "Foreach"}

_APPSETTING_RE = re.compile(r"@appsetting\('([^']+)'\)")


def _collect_connections_from_actions(actions: dict | None) -> set[tuple[str, str]]:
    """Return {(type, name)} pairs from an actions dict, recursing into control flow."""
    found: set[tuple[str, str]] = set()
    if not isinstance(actions, dict):
        return found
    for _action_name, action in actions.items():
        if not isinstance(action, dict):
            continue
        atype = action.get("type")
        if atype in _CONTROL_ACTIONS:
            if atype == "If":
                found |= _collect_connections_from_actions(action.get("actions"))
                else_block = action.get("else") or {}
                found |= _collect_connections_from_actions(else_block.get("actions"))
            elif atype == "Switch":
                cases = action.get("cases") or {}
                for case in cases.values():
                    if isinstance(case, dict):
                        found |= _collect_connections_from_actions(case.get("actions"))
                default = action.get("default") or {}
                found |= _collect_connections_from_actions(default.get("actions"))
            else:  # Until, Scope, Foreach
                found |= _collect_connections_from_actions(action.get("actions"))
        elif atype == "ServiceProvider":
            name = (
                action.get("inputs", {})
                .get("serviceProviderConfiguration", {})
                .get("connectionName")
            )
            if name:
                found.add(("ServiceProvider", name))
        elif atype == "ApiConnection":
            name = (
                action.get("inputs", {})
                .get("host", {})
                .get("connection", {})
                .get("referenceName")
            )
            if name:
                found.add(("ApiConnection", name))
    return found


def collect_referenced_connections(root: Path) -> set[tuple[str, str]]:
    """Walk every workflow.json under root and collect referenced connections."""
    found: set[tuple[str, str]] = set()
    for path in sorted(root.glob("*/workflow.json")):
        try:
            definition = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        definition_block = definition.get("definition") or {}
        found |= _collect_connections_from_actions(definition_block.get("triggers"))
        found |= _collect_connections_from_actions(definition_block.get("actions"))
    return found


def collect_declared_connections(connections_json: Path) -> set[tuple[str, str]]:
    """Parse connections.json -> {(type, name)} pairs for declared connections."""
    if not connections_json.exists():
        raise typer.BadParameter(f"Cannot find connections.json at {connections_json}")
    data = json.loads(connections_json.read_text(encoding="utf-8"))
    declared: set[tuple[str, str]] = set()
    for name in (data.get("managedApiConnections") or {}):
        declared.add(("ApiConnection", name))
    for name in (data.get("serviceProviderConnections") or {}):
        declared.add(("ServiceProvider", name))
    return declared


def _collect_appsetting_refs(parameter_values: object) -> set[str]:
    """Find every `@appsetting('NAME')` reference inside parameterValues."""
    found: set[str] = set()
    if not isinstance(parameter_values, dict):
        return found
    for value in parameter_values.values():
        if isinstance(value, str):
            found.update(_APPSETTING_RE.findall(value))
    return found


def _apply_cleanup(
    connections_json: Path, orphans: set[tuple[str, str]]
) -> set[str]:
    """Remove orphans from connections.json. Returns app-setting names to delete."""
    data = json.loads(connections_json.read_text(encoding="utf-8"))
    api = data.get("managedApiConnections") or {}
    sp = data.get("serviceProviderConnections") or {}
    unused_appsettings: set[str] = set()

    for ctype, cname in orphans:
        if ctype == "ApiConnection" and cname in api:
            del api[cname]
        elif ctype == "ServiceProvider" and cname in sp:
            unused_appsettings.update(_collect_appsetting_refs(sp[cname].get("parameterValues")))
            del sp[cname]

    data["managedApiConnections"] = api
    data["serviceProviderConnections"] = sp
    connections_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return unused_appsettings


def scan_connections(
    root: Path = typer.Option(
        None, "--root",
        help=(
            "wwwroot path containing workflows and connections.json. "
            f"Defaults to LAT_ROOT_FOLDER env var or {settings.root_folder}."
        ),
    ),
    apply: bool = typer.Option(
        False, "--apply",
        help="Remove orphan connections from connections.json and delete the "
             "associated app settings via ARM (requires MI permissions).",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y",
        help="Skip the destructive-cleanup confirmation prompt (only with --apply).",
    ),
) -> None:
    """Find connections declared in connections.json but unused by any workflow."""
    root_path = root or settings.root_folder
    if not root_path.exists() or not root_path.is_dir():
        raise typer.BadParameter(f"Root folder does not exist: {root_path}")

    typer.echo("Retrieving API connections and Service Providers from all existing workflows.")
    referenced = collect_referenced_connections(root_path)
    typer.echo(f"{len(referenced)} identical connections found")

    conn_path = root_path / "connections.json"
    declared = collect_declared_connections(conn_path)
    typer.echo(f"{len(declared)} connections found in connections.json.")

    orphans = declared - referenced
    if not orphans:
        typer.echo("There's no unsed connections.")
        return

    typer.echo("Following connections are not used in your workflows")
    table = Table(show_header=True, header_style="bold")
    table.add_column("Connection Type")
    table.add_column("Connection Name")
    for ctype, cname in sorted(orphans):
        table.add_row(ctype, cname)
    console.print(table)

    if not apply:
        return

    if not yes:
        typer.confirm(
            "Whether you would like to remove those data in connections.json and appsettings?",
            abort=True,
        )

    typer.echo("Start to clean up...")
    unused_settings = _apply_cleanup(conn_path, orphans)

    if unused_settings:
        typer.echo(
            f"Removing {len(unused_settings)} unused app-setting(s) from ARM: "
            + ", ".join(sorted(unused_settings))
        )
        current = arm.get_appsettings()
        new_settings = {k: v for k, v in current.items() if k not in unused_settings}
        arm.put_appsettings(new_settings)

    typer.echo(
        "All data related to unused API connections and Service Providers have been cleaned up."
    )


def register(validate_app: typer.Typer) -> None:
    validate_app.command(
        "scan-connections",
        help="Find connections declared but unused by any workflow.",
    )(scan_connections)
