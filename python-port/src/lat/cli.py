"""Typer entry point — wires commands into a single CLI app.

The placeholder structure mirrors the .NET tool's command grouping. Each
sub-app maps to a category under ../../playbooks/<category>/. As the
agent ports each command, it registers it with the matching sub-app.
"""
from __future__ import annotations

import typer

from . import logging_

app = typer.Typer(
    name="lat",
    help="Logic App Standard Advanced Tool (Python port).",
    no_args_is_help=True,
)

# Sub-apps mirror playbooks/* groupings.
workflow_app = typer.Typer(help="Workflow definition / version management")
runs_app = typer.Typer(help="Run-history triage")
cleanup_app = typer.Typer(help="Storage cleanup")
validate_app = typer.Typer(help="Connectivity / configuration validation")
site_app = typer.Typer(help="Site / file management")
tools_app = typer.Typer(help="Utility / debug helpers")

app.add_typer(workflow_app, name="workflow")
app.add_typer(runs_app, name="runs")
app.add_typer(cleanup_app, name="cleanup")
app.add_typer(validate_app, name="validate")
app.add_typer(site_app, name="site")
app.add_typer(tools_app, name="tools")


@app.callback()
def _root(
    log_level: str = typer.Option(
        None, "--log-level", help="DEBUG/INFO/WARNING/ERROR/CRITICAL"
    ),
) -> None:
    logging_.configure(log_level)


# ---------------------------------------------------------------------------
# Command registrations (filled in as commands are ported). Each playbook
# file under ../../playbooks/ has a "registration" stanza showing exactly
# what to add here.
# ---------------------------------------------------------------------------

from .commands.tools import register as _reg_tools
from .commands.tools_env import register as _reg_tools_env
from .commands.filter_host_logs import register as _reg_filter_host_logs
from .commands.endpoint_validation import register as _reg_endpoint_validation
from .commands.scan_connections import register as _reg_scan_connections

_reg_tools(tools_app)
_reg_tools_env(tools_app)
_reg_filter_host_logs(site_app)
_reg_endpoint_validation(validate_app)
_reg_scan_connections(validate_app)


if __name__ == "__main__":
    app()
