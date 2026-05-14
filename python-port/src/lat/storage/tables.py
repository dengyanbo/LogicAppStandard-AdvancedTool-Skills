"""Storage Tables helpers — mirrors Shared/TableOperations.cs.

Provides:
  * Lazy paged queries.
  * Batched upserts respecting the 100-entity-per-partition transaction
    limit and a 3.5-MB body cap.
  * Convenience query wrappers for the main definition table.

See references/04-table-schema.md for the schema and known queries.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Iterator

from azure.data.tables import TableClient, TableServiceClient, TransactionOperation

from ..settings import settings
from .prefix import flowlookup_rowkey, main_definition_table


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
