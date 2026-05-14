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
from .commands.validate_sp_connectivity import register as _reg_validate_sp_conn
from .commands.validate_storage_connectivity import register as _reg_validate_storage_conn
from .commands.validate_workflows import register as _reg_validate_workflows
from .commands.batch_resubmit import register as _reg_batch_resubmit
from .commands.snapshot import register as _reg_snapshot
from .commands.sync_to_local import register as _reg_sync_to_local
from .commands.whitelist_connector_ip import register as _reg_whitelist_ip
from .commands.list_versions import register as _reg_list_versions
from .commands.list_workflows import register as _reg_list_workflows
from .commands.backup import register as _reg_backup
from .commands.decode import register as _reg_decode
from .commands.generate_table_prefix import register as _reg_generate_table_prefix
from .commands.retrieve_action_payload import register as _reg_retrieve_action_payload
from .commands.generate_run_history_url import register as _reg_generate_run_history_url

_reg_tools(tools_app)
_reg_tools_env(tools_app)
_reg_filter_host_logs(site_app)
_reg_endpoint_validation(validate_app)
_reg_scan_connections(validate_app)
_reg_validate_sp_conn(validate_app)
_reg_validate_storage_conn(validate_app)
_reg_validate_workflows(validate_app)
_reg_batch_resubmit(runs_app)
_reg_snapshot(site_app)
_reg_sync_to_local(site_app)
_reg_whitelist_ip(validate_app)
_reg_list_versions(workflow_app)
_reg_list_workflows(workflow_app)
_reg_backup(workflow_app)
_reg_decode(workflow_app)
_reg_generate_table_prefix(tools_app)
_reg_retrieve_action_payload(runs_app)
_reg_generate_run_history_url(runs_app)


if __name__ == "__main__":
    app()
