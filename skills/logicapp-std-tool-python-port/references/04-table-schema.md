# Reference 04 — Storage Table Schema

Comprehensive guide to the tables, partitions, and row-key formats the tool
reads and writes. Without this reference the port will issue queries that
return nothing or, worse, write rows the LA runtime cannot index.

## 1. Tables the tool touches

| Logical name | Physical naming pattern | Scope | Source ref |
| --- | --- | --- | --- |
| Main definition table | `flow{laHash}flows` | Logic-App-wide | `Shared/TableOperations.cs:12-18` |
| Per-flow `flows` | `flow{laHash}{flowHash}flows` | per workflow | `Shared/TableOperations.cs:74-79` |
| Per-flow `runs` | `flow{laHash}{flowHash}runs` | per workflow | `Shared/TableOperations.cs:46-51` |
| Per-flow `histories` | `flow{laHash}{flowHash}histories` | per workflow | `Shared/TableOperations.cs:39-43` |
| Per-flow per-day `actions` | `flow{laHash}{flowHash}{yyyyMMdd}t000000zactions` | workflow + UTC day | `Shared/TableOperations.cs:60-65` |
| Per-flow per-day `variables` | `flow{laHash}{flowHash}{yyyyMMdd}t000000zvariables` | workflow + UTC day | `Operations/MergeRunHistory.cs:84-91` |
| Job queue | `flow{laHash}jobtriggers` / `…jobs` | Logic-App-wide | `Operations/ClearJobQueue.cs` (read source) |

* `laHash = MurmurHash64(LogicAppName.ToLower()).TrimTo15Chars().ToLower()`
* `flowHash = MurmurHash64(flowId.ToLower()).TrimTo15Chars().ToLower()`
* The `t000000z` infix is a literal lowercase ISO-8601-like marker; do not
  alter case.

## 2. Main definition table (the most important)

Holds three logical row types per workflow version. From
`Operations/Backup.cs:39-41`:

> *"In Storage Table, all the in-used workflows have duplicate records which
> start with `MYEDGEENVIRONMENT_FLOWIDENTIFIER` and
> `MYEDGEENVIRONMENT_FLOWLOOKUP`. Filter only for
> `MYEDGEENVIRONMENT_FLOWVERSION` to exclude duplicate workflow definitions."*

### 2.1 RowKey types

| RowKey prefix | Purpose |
| --- | --- |
| `MYEDGEENVIRONMENT_FLOWVERSION_*` | Canonical compressed workflow definition. One per (flowId, version). |
| `MYEDGEENVIRONMENT_FLOWLOOKUP_*` | Maps a workflow name → current `FlowId`. Exactly one per active workflow name. |
| `MYEDGEENVIRONMENT_FLOWIDENTIFIER_*` | Identifier metadata; supplemental. |

### 2.2 RowKey escape rule

`Shared/TableOperations.cs:93-96`:

```csharp
public static string FormatRawKey(string rawKey)
{
    return rawKey.Replace("_", ":5F").Replace("-", ":2D");
}
```

So the FLOWLOOKUP row for workflow named `My-Workflow_Name` is:

```
MYEDGEENVIRONMENT_FLOWLOOKUP-MYEDGERESOURCEGROUP-MY:2DWORKFLOW:5FNAME
```

Note:
* The **workflow name is uppercased** before escaping (`workflowName.ToUpper()`).
* Underscores → `:5F`, hyphens → `:2D` (lowercase `:` literally followed by
  hex). These are **not** percent-encodings — they substitute the URL-unsafe
  `_` and `-` chars with the explicit colon-hex form the LA runtime
  expects in RowKeys.

The Python port must implement this exactly:

```python
def format_raw_key(raw: str) -> str:
    return raw.replace("_", ":5F").replace("-", ":2D")

def flowlookup_rowkey(workflow_name: str) -> str:
    return f"MYEDGEENVIRONMENT_FLOWLOOKUP-MYEDGERESOURCEGROUP-{format_raw_key(workflow_name.upper())}"
```

### 2.3 Columns of interest

| Column | Type | Used by |
| --- | --- | --- |
| `FlowName` | string | Backup, ListWorkflows, MergeRunHistory.OverwriteFlowId |
| `FlowId` | string (GUID) | Backup, MergeRunHistory, RestoreWorkflowWithVersion |
| `FlowSequenceId` | string | Backup, Revert, Decode, RestoreWorkflowWithVersion |
| `ChangedTime` | DateTime | Backup date filter |
| `DefinitionCompressed` | binary | ZSTD/Deflate payload (see ref 03) |
| `Kind` | string | `Stateful` / `Stateless`; Backup, ConvertToStateful |

### 2.4 Common queries

```csharp
// Backup: all versions modified on/after a date
TableOperations.QueryMainTable(
    $"ChangedTime ge datetime'{formattedDate}'",
    new[] { "FlowName", "FlowSequenceId", "ChangedTime", "FlowId", "RowKey", "DefinitionCompressed", "Kind" });

// Find current flowId for a workflow name
TableOperations.QueryCurrentWorkflowByName(workflowName, new[] { "FlowId" });

// All historical versions of a workflow name
TableOperations.QueryMainTable($"FlowName eq '{workflowName}'", new[] { "FlowId" });
```

The `$filter` syntax is OData. The Python port uses
`TableClient.query_entities(query_filter=..., select=...)`.

## 3. Per-flow `runs`, `histories`, `flows`

The "runs" table records workflow run instances; "histories" records
top-level lifecycle events; the per-flow "flows" table stores per-flow
copies of the definition row (purpose overlaps with main table).

Schema details vary by Logic App version. The tool treats them as
opaque: it streams pages, optionally rewrites `FlowId`/`RowKey`/
`PartitionKey`, and upserts. The Python port should do the same — do **not**
deserialize into typed schemas.

## 4. Action / Variable tables (per-day)

Each row's RowKey starts with an uppercase GUID-without-hyphens, then `_`,
then a sub-key. The partition key is computed via
`StoragePrefixGenerator.GeneratePartitionKey(RowKey)` (see ref 02).

Notable columns in the actions table:

| Column | Type | Used by |
| --- | --- | --- |
| `InputsLinkCompressed` | binary | RetrieveFailures, RetrieveActionPayload, SearchInHistory |
| `OutputsLinkCompressed` | binary | RetrieveActionPayload, SearchInHistory |
| `Code` | string | RetrieveFailures (`"Failed"`, `"Cancelled"`, `"Succeeded"`) |
| `Error` | string (JSON) | RetrieveFailures error details |
| `StartTime` / `EndTime` | DateTime | reporting |

The compressed columns decode via `ContentDecoder`. See ref 03 §7.

## 5. The 100-entity per-partition transaction limit

`Operations/MergeRunHistory.cs:144-149`:

```csharp
if (actions[partitionKey].Count == 100)
{
    targetTableClient.SubmitTransaction(actions[partitionKey]);
    actions.Remove(partitionKey);
}
```

Azure Storage Tables enforces a 100-entity limit and 4-MB body cap per
transaction; all entities in a batch must share the same partition key.
The Python equivalent using `azure-data-tables`:

```python
from azure.data.tables import TableClient, TransactionOperation

def _batch_upsert(client: TableClient, entities: Iterable[dict]) -> None:
    partitions: dict[str, list[tuple]] = {}
    for ent in entities:
        pk = ent["PartitionKey"]
        partitions.setdefault(pk, []).append((TransactionOperation.UPSERT, ent))
        if len(partitions[pk]) == 100:
            client.submit_transaction(partitions[pk])
            partitions[pk] = []
    for batch in partitions.values():
        if batch:
            client.submit_transaction(batch)
```

## 6. Listing tables by prefix

`Operations/MergeRunHistory.cs:84-91`:

```csharp
serviceClient.Query().ToList()
    .Where(s => s.Name.StartsWith(prefix)
                && (s.Name.EndsWith("actions") || s.Name.EndsWith("variables"))
                && int.Parse(s.Name.Substring(34, 8)) >= startTime
                && int.Parse(s.Name.Substring(34, 8)) <= endTime)
    .Select(t => t.Name)
    .ToList();
```

Key insight: the date is at offset **34** in the table name, length 8
(`yyyyMMdd`). Computation:

```
4 ("flow") + 15 (laHash) + 15 (flowHash) = 34
```

The Python port should compute this offset from the prefix instead of
hard-coding 34:

```python
def list_per_day_tables(table_service, la_name: str, flow_id: str,
                       suffixes: tuple[str, ...] = ("actions", "variables"),
                       start_yyyymmdd: int = 0, end_yyyymmdd: int = 99991231) -> list[str]:
    prefix = f"flow{logic_app_prefix(la_name)}{workflow_prefix(flow_id)}"
    date_offset = len(prefix)
    out: list[str] = []
    for t in table_service.list_tables():
        name = t.name
        if not name.startswith(prefix):
            continue
        if not any(name.endswith(s) for s in suffixes):
            continue
        try:
            d = int(name[date_offset:date_offset + 8])
        except ValueError:
            continue
        if start_yyyymmdd <= d <= end_yyyymmdd:
            out.append(name)
    return out
```

## 7. Pagination

`Shared/PageableTableQuery.cs` (read in full) implements memory-bounded
streaming, especially for `SearchInHistory` which would otherwise pull a
full day's worth of action rows. The Python equivalent is straightforward —
`TableClient.query_entities` returns an `ItemPaged[TableEntity]` that
yields lazily.

## 8. Pitfalls to write tests for

1. **Wrong table name** → the test-harness should call `list_tables` and
   assert the predicted name exists before issuing a query.
2. **OData injection** in user-supplied filters (workflow name, date) —
   sanitize quotes, but escape via concatenation, not parameter binding
   (`azure-data-tables` doesn't support param binding).
3. **Time zone**. All dates the tool exchanges with users are interpreted
   as **UTC**. Mirror this in the Python port — never use `datetime.now()`,
   always `datetime.now(tz=timezone.utc)`.
