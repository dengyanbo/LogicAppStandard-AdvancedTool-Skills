"""Storage Tables helpers — mirrors Shared/TableOperations.cs.

Provides:
  * Lazy paged queries.
  * Batched upserts respecting the 100-entity-per-partition transaction
    limit and a 3.5-MB body cap.
  * Convenience query wrappers for the main definition table.
  * WorkflowsInfoQuery-style helpers used by Backup/ListVersions/...

See references/04-table-schema.md for the schema and known queries.
"""
from __future__ import annotations

import datetime as _dt
import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from azure.data.tables import TableClient, TableServiceClient, TransactionOperation

from ..settings import settings
from . import compression
from .prefix import (
    flowlookup_rowkey,
    main_definition_table,
    per_day_action_table,
    per_flow_table,
)


def _service_client() -> TableServiceClient:
    conn = settings.connection_string
    if not conn:
        raise RuntimeError("AzureWebJobsStorage is not set")
    return TableServiceClient.from_connection_string(conn)


def table_client(table_name: str) -> TableClient:
    conn = settings.connection_string
    if not conn:
        raise RuntimeError("AzureWebJobsStorage is not set")
    return TableClient.from_connection_string(conn, table_name)


def table_exists(table_name: str) -> bool:
    svc = _service_client()
    return any(t.name == table_name for t in svc.query_tables(f"TableName eq '{table_name}'"))


def query_paged(
    table_name: str,
    query_filter: str | None = None,
    select: list[str] | None = None,
    page_size: int = 1000,
) -> Iterator[dict]:
    """Yield entities lazily; memory bounded by `page_size` per page.

    Mirrors Shared/PageableTableQuery.cs.
    """
    client = table_client(table_name)
    pages = client.query_entities(
        query_filter=query_filter or "",
        select=select,
        results_per_page=page_size,
    ).by_page()
    for page in pages:
        yield from page


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------


def query_main_table(
    query_filter: str | None = None, select: list[str] | None = None
) -> Iterator[dict]:
    la = settings.logic_app_name
    if not la:
        raise RuntimeError("WEBSITE_SITE_NAME is not set")
    return query_paged(main_definition_table(la), query_filter, select)


def query_current_workflow_by_name(workflow_name: str, select: list[str] | None = None
                                   ) -> list[dict]:
    rk = flowlookup_rowkey(workflow_name)
    return list(query_main_table(f"RowKey eq '{rk}'", select))


def query_history_table(
    workflow_name: str, query_filter: str | None = None, select: list[str] | None = None
) -> Iterator[dict]:
    la = settings.logic_app_name
    if not la:
        raise RuntimeError("WEBSITE_SITE_NAME is not set")
    flow_id = _current_flow_id(workflow_name)
    return query_paged(per_flow_table(la, flow_id, "histories"), query_filter, select)


def query_run_table(
    workflow_name: str, query_filter: str | None = None, select: list[str] | None = None
) -> Iterator[dict]:
    la = settings.logic_app_name
    if not la:
        raise RuntimeError("WEBSITE_SITE_NAME is not set")
    flow_id = _current_flow_id(workflow_name)
    return query_paged(per_flow_table(la, flow_id, "runs"), query_filter, select)


def query_action_table(
    workflow_name: str,
    date: str,
    query_filter: str | None = None,
    select: list[str] | None = None,
) -> Iterator[dict]:
    la = settings.logic_app_name
    if not la:
        raise RuntimeError("WEBSITE_SITE_NAME is not set")
    flow_id = _current_flow_id(workflow_name)
    return query_paged(per_day_action_table(la, flow_id, date), query_filter, select)


def _current_flow_id(workflow_name: str) -> str:
    rows = query_current_workflow_by_name(workflow_name, ["FlowId"])
    if not rows:
        raise RuntimeError(
            f"{workflow_name} cannot be found in storage table, please check whether "
            "workflow is correct."
        )
    flow_id = rows[0].get("FlowId")
    if not flow_id:
        raise RuntimeError(f"FlowId missing for workflow {workflow_name!r}")
    return str(flow_id)


# ---------------------------------------------------------------------------
# WorkflowsInfoQuery — mirrors Shared/WorkflowInfoQuery.cs
# ---------------------------------------------------------------------------


def _changed_time_dt(entity: dict) -> _dt.datetime | None:
    value = entity.get("ChangedTime")
    if isinstance(value, _dt.datetime):
        return value
    if isinstance(value, str):
        try:
            return _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _group_latest_by(
    entities: Iterable[dict], key_field: str
) -> list[dict]:
    """Group by key_field and keep the row with the largest ChangedTime."""
    latest: dict[Any, dict] = {}
    for ent in entities:
        key = ent.get(key_field)
        if key is None:
            continue
        current = latest.get(key)
        if current is None:
            latest[key] = ent
            continue
        new_ts = _changed_time_dt(ent)
        old_ts = _changed_time_dt(current)
        if new_ts is None:
            continue
        if old_ts is None or new_ts > old_ts:
            latest[key] = ent
    return list(latest.values())


def list_all_workflows(extra_select: Iterable[str] = ()) -> list[dict]:
    """Latest row per FlowName from the main definition table.

    Mirrors WorkflowsInfoQuery.ListAllWorkflows. Raises if zero rows match.
    """
    select = list(dict.fromkeys(["FlowName", "ChangedTime", "Kind", *extra_select]))
    rows = list(query_main_table(None, select=select))
    grouped = _group_latest_by(rows, "FlowName")
    grouped.sort(
        key=lambda e: _changed_time_dt(e) or _dt.datetime.min, reverse=True
    )
    if not grouped:
        raise RuntimeError("No workflows found.")
    return grouped


def list_workflows_by_name(
    workflow_name: str, extra_select: Iterable[str] = ()
) -> list[dict]:
    """Latest row per FlowId for a given FlowName.

    Mirrors WorkflowsInfoQuery.ListWorkflowsByName.
    """
    select = list(dict.fromkeys(["FlowId", "ChangedTime", "Kind", *extra_select]))
    rows = list(query_main_table(f"FlowName eq '{workflow_name}'", select=select))
    grouped = _group_latest_by(rows, "FlowId")
    grouped.sort(
        key=lambda e: _changed_time_dt(e) or _dt.datetime.min, reverse=True
    )
    if not grouped:
        raise RuntimeError("No workflows found.")
    return grouped


def list_versions_by_id(
    flow_id: str, extra_select: Iterable[str] = ()
) -> list[dict]:
    """All FLOWVERSION rows for a given FlowId, newest first.

    Mirrors WorkflowsInfoQuery.ListVersionsByID.
    """
    select = list(
        dict.fromkeys(["RowKey", "ChangedTime", "FlowSequenceId", *extra_select])
    )
    rows = [
        r
        for r in query_main_table(f"FlowId eq '{flow_id}'", select=select)
        if str(r.get("RowKey", "")).startswith("MYEDGEENVIRONMENT_FLOWVERSION")
    ]
    rows.sort(
        key=lambda e: _changed_time_dt(e) or _dt.datetime.min, reverse=True
    )
    if not rows:
        raise RuntimeError("No workflows found.")
    return rows


# ---------------------------------------------------------------------------
# Definition save helper (mirrors Shared/Common.SaveDefinition)
# ---------------------------------------------------------------------------


def save_definition(
    folder: Path,
    file_name: str,
    entity: dict,
    *,
    overwrite: bool = True,
) -> Path:
    """Write a decompressed + formatted workflow definition to disk.

    Returns the resulting file path. If overwrite is False and the file
    already exists, raises FileExistsError.
    """
    compressed = entity.get("DefinitionCompressed")
    if compressed is None:
        raise ValueError("Entity does not contain DefinitionCompressed")
    if isinstance(compressed, str):
        # Azure SDK sometimes hands back base64-encoded blob payloads.
        import base64

        compressed = base64.b64decode(compressed)
    decoded = compression.decompress(compressed)
    if decoded is None:
        raise ValueError("DefinitionCompressed decompressed to None")
    kind = entity.get("Kind") or ""
    payload = {"definition": json.loads(decoded), "kind": kind}
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / file_name
    if target.exists() and not overwrite:
        raise FileExistsError(target)
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# Batched upsert (respecting Azure Tables transaction limits)
# ---------------------------------------------------------------------------

_MAX_ENTITIES_PER_TX = 100
_MAX_TX_BODY_BYTES = 3_500_000  # 4 MB hard limit; conservative ceiling


def batched_upsert(client: TableClient, entities: Iterable[dict]) -> int:
    """Upsert entities in batches grouped by PartitionKey.

    Returns the number of entities written.
    """
    total = 0
    partitions: dict[str, list[tuple[str, dict]]] = {}
    sizes: dict[str, int] = {}

    def flush(pk: str) -> None:
        nonlocal total
        if not partitions.get(pk):
            return
        client.submit_transaction(partitions[pk])
        total += len(partitions[pk])
        partitions[pk] = []
        sizes[pk] = 0

    for ent in entities:
        pk = ent["PartitionKey"]
        size = len(json.dumps(ent, default=str).encode("utf-8"))
        bucket = partitions.setdefault(pk, [])
        bucket.append((TransactionOperation.UPSERT, ent))
        sizes[pk] = sizes.get(pk, 0) + size
        if len(bucket) >= _MAX_ENTITIES_PER_TX or sizes[pk] >= _MAX_TX_BODY_BYTES:
            flush(pk)

    for pk in list(partitions):
        flush(pk)
    return total
