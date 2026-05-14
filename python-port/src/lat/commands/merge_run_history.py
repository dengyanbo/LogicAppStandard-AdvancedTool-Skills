"""`MergeRunHistory` — destructive command: re-key one workflow's run history.

Mirrors `Operations/MergeRunHistory.cs`. Re-stamps every row in the
source workflow's main / runs / flows / histories / actions /
variables tables so they belong to the target workflow's FlowId. The
RowKey embedded source-FlowId-as-uppercase is replaced with the target
FlowId, and the partition key is recomputed.

This is irreversible and the .NET tool marks it experimental. The
Python port keeps the same semantics but adds `--yes` to skip the
confirmation prompt for scripted use.

The auto-create-target branch (when `--target-workflow` is empty) is
NOT implemented: it depends on the Logic App runtime ingesting a new
empty workflow.json into the storage table, which can't be simulated
offline. Instead, the user is expected to pre-create the target.
"""
from __future__ import annotations

import datetime as _dt
from collections import defaultdict
from typing import Any

import typer

from ..settings import settings
from ..storage import tables
from ..storage.prefix import (
    flowlookup_rowkey,
    logic_app_prefix,
    main_definition_table,
    partition_key,
    workflow_prefix,
)


def _re_key_main(entity: dict[str, Any], source_id: str, target_id: str) -> dict[str, Any]:
    """Main-table re-key: keeps source's PartitionKey, only rewrites RowKey + fields.

    Mirrors OverwriteFlowId in MergeRunHistory.cs.
    """
    out = dict(entity)
    out["FlowId"] = target_id
    rk = out.get("RowKey", "")
    if isinstance(rk, str):
        out["RowKey"] = rk.replace(source_id.upper(), target_id.upper())
    # Keep source's PartitionKey unchanged (out already has it).
    return out


def _re_key(entity: dict[str, Any], source_id: str, target_id: str) -> dict[str, Any]:
    """Per-flow table re-key: rewrites RowKey AND recomputes PartitionKey.

    Mirrors MergeTable in MergeRunHistory.cs.
    """
    out = dict(entity)
    out["FlowId"] = target_id
    rk = out.get("RowKey", "")
    if isinstance(rk, str):
        out["RowKey"] = rk.replace(source_id.upper(), target_id.upper())
    out["PartitionKey"] = partition_key(out["RowKey"])
    return out


def _overwrite_main_flow_id(
    source_id: str, target_id: str, target_workflow: str
) -> int:
    """Re-key every main-table row whose FlowId == source_id."""
    la = settings.logic_app_name
    if not la:
        raise RuntimeError("WEBSITE_SITE_NAME is not set")
    rows = list(tables.query_main_table(f"FlowId eq '{source_id}'"))
    if not rows:
        return 0
    client = tables.table_client(main_definition_table(la))
    for row in rows:
        updated = _re_key_main(row, source_id, target_id)
        updated["FlowName"] = target_workflow
        client.upsert_entity(updated)
    return len(rows)


def _merge_table(
    source_name: str, target_name: str, source_id: str, target_id: str
) -> int:
    """Copy every row from source_name into target_name, re-keyed."""
    try:
        # If source table doesn't exist in the fake (or live), skip.
        if not tables.table_exists(source_name):
            typer.echo(f"Skip merge for {source_name} due to not found.")
            return 0
    except Exception:  # noqa: BLE001
        typer.echo(f"Skip merge for {source_name} (lookup failed).")
        return 0

    rows = list(tables.query_paged(source_name))
    if not rows:
        typer.echo(f"Skip merge for {source_name}: no rows.")
        return 0

    target_client = tables.table_client(target_name)
    # Group by new partition key; submit in 100-entity batches per partition.
    batches: defaultdict[str, list[tuple[str, dict]]] = defaultdict(list)
    written = 0
    for row in rows:
        updated = _re_key(row, source_id, target_id)
        pk = updated["PartitionKey"]
        batches[pk].append(("upsert", updated))
        if len(batches[pk]) >= 100:
            target_client.submit_transaction(batches[pk])
            written += len(batches[pk])
            batches[pk] = []
    for pk, ops in list(batches.items()):
        if ops:
            target_client.submit_transaction(ops)
            written += len(ops)
    typer.echo(f"Merged {written} row(s) from {source_name} -> {target_name}.")
    return written


def _date_range_tables(prefix: str, start_int: int, end_int: int) -> list[str]:
    out: list[str] = []
    for name in tables.list_tables_with_prefix(prefix):
        if not (name.endswith("actions") or name.endswith("variables")):
            continue
        if len(name) < 42:
            continue
        try:
            d = int(name[34:42])
        except ValueError:
            continue
        if start_int <= d <= end_int:
            out.append(name)
    return out


def merge_run_history(
    source_workflow: str = typer.Option(
        ..., "-s", "--source-workflow",
        help="Source workflow name whose run history should be merged.",
    ),
    target_workflow: str = typer.Option(
        ..., "-t", "--target-workflow",
        help="Target workflow name (must already exist).",
    ),
    start_date: str = typer.Option(
        ..., "--start", help="Start date (yyyyMMdd, inclusive) for action/variable tables.",
    ),
    end_date: str = typer.Option(
        ..., "--end", help="End date (yyyyMMdd, inclusive) for action/variable tables.",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the experimental-feature prompt.",
    ),
) -> None:
    """Merge run history from one workflow into another (irreversible)."""
    if not yes:
        typer.echo(
            "Warning: this is an experimental, irreversible operation.\n"
            "Make sure the Logic App is healthy and the target workflow exists."
        )
        typer.confirm("Continue?", abort=True)

    try:
        start_int = int(_dt.datetime.strptime(start_date, "%Y%m%d").strftime("%Y%m%d"))
        end_int = int(_dt.datetime.strptime(end_date, "%Y%m%d").strftime("%Y%m%d"))
    except ValueError as exc:
        raise typer.BadParameter("Both --start and --end must be yyyyMMdd.") from exc

    target_lookup = tables.query_current_workflow_by_name(
        target_workflow, ["FlowId"]
    )
    if not target_lookup:
        raise typer.BadParameter(
            f"Cannot find existing workflow with name {target_workflow}, "
            "please review your input."
        )
    target_id = str(target_lookup[0].get("FlowId") or "")
    if not target_id:
        raise typer.BadParameter("Target workflow has no FlowId.")

    source_ids = tables.list_flow_ids_by_name(source_workflow)
    if not source_ids:
        raise typer.BadParameter(
            f"Cannot find source workflow {source_workflow} in storage table."
        )
    # If multiple FlowIds, pick the first non-target one (the .NET tool prompts).
    source_id = next((fid for fid in source_ids if fid != target_id), "")
    if not source_id:
        raise typer.BadParameter(
            "Source workflow id and target workflow id are the same; "
            "please select different workflows."
        )

    typer.echo(
        f"Merging {source_workflow} ({source_id}) -> {target_workflow} ({target_id})"
    )

    main_count = _overwrite_main_flow_id(source_id, target_id, target_workflow)
    typer.echo(f"Re-keyed {main_count} main-table row(s).")

    la_name = settings.logic_app_name or ""
    la_pref = logic_app_prefix(la_name)
    src_pref = f"flow{la_pref}{workflow_prefix(source_id)}"
    tgt_pref = f"flow{la_pref}{workflow_prefix(target_id)}"

    for suffix in ("runs", "flows", "histories"):
        _merge_table(f"{src_pref}{suffix}", f"{tgt_pref}{suffix}", source_id, target_id)

    for name in _date_range_tables(src_pref, start_int, end_int):
        target_name = name.replace(src_pref, tgt_pref)
        _merge_table(name, target_name, source_id, target_id)


def register(workflow_app: typer.Typer) -> None:
    workflow_app.command(
        "merge-run-history",
        help="Merge one workflow's run history into another (destructive).",
    )(merge_run_history)
