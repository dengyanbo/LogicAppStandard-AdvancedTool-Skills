# Reference 02 — Partition Key Derivation

For tables that store many rows per workflow (notably `…actions` and
`…variables`), Azure Logic Apps Standard assigns each entity a deterministic
partition key derived from its RowKey. The port must reproduce this exactly
to keep the 100-entity-per-transaction batching working in `MergeRunHistory`
and any future bulk-write commands.

## 1. C# source

`Shared/StoragePrefixGenerator.cs:21-30, 46-77`

```csharp
public static string GeneratePartitionKey(string rowKey)
{
    string key = rowKey.Split('_')[0];                    // (1) take everything before the first '_'
    byte[] data = Encoding.UTF8.GetBytes(key);
    uint result = MurmurHash32(data, 0U) % 1048576;       // (2) modulo 2^20
    return result.ToString("X5");                         // (3) 5-digit uppercase hex, zero-padded
}
```

`MurmurHash32` is the standard MurmurHash3 x86_32 variant (constants
`0xCC9E2D51`, `0x1B873593`, mixer constants `0x85EBCA6B`, `0xC2B2AE35`,
final additions `0xE6546B64`). It is **not** related to `MurmurHash64` from
reference 01 — they use different constants and structure.

## 2. RowKey format that feeds this function

Inside the action/variable tables, RowKeys look like:

```
<UPPER-GUID>_<sub-key>
e.g.  20D26F58B6A24A269A0D9DB7C7B0AE76_<actionInstanceId>
```

`Split('_')[0]` therefore takes only the leading uppercase GUID-without-
hyphens segment. This is what gets hashed.

> When the .NET code rewrites RowKeys in `MergeRunHistory.cs` it does:
> ```csharp
> te.RowKey = te.RowKey.Replace(sourceID.ToUpper(), targetID.ToUpper());
> string partitionKey = StoragePrefixGenerator.GeneratePartitionKey(te.RowKey);
> te.PartitionKey = partitionKey;
> ```
> i.e. it rewrites the GUID first (uppercase!) then recomputes the
> partition key from the new RowKey. The Python port must follow the same
> order.

## 3. Python implementation

```python
# src/lat/storage/prefix.py  (continuation of reference 01)

C1_32 = 0xCC9E2D51
C2_32 = 0x1B873593


def murmur_hash_32(data: bytes, seed: int = 0) -> int:
    length = len(data)
    h = seed & MASK32
    i = 0

    while i + 3 < length:
        k = _read_u32_le(data, i)
        k = (k * C1_32) & MASK32
        k = _rotl32(k, 15)
        k = (k * C2_32) & MASK32
        h ^= k
        h = _rotl32(h, 13)
        h = (h * 5 + 0xE6546B64) & MASK32
        i += 4

    tail = length - i
    if tail > 0:
        if tail == 3:
            k = data[i] | (data[i+1] << 8) | (data[i+2] << 16)
        elif tail == 2:
            k = data[i] | (data[i+1] << 8)
        else:
            k = data[i]
        k = (k * C1_32) & MASK32
        k = _rotl32(k, 15)
        k = (k * C2_32) & MASK32
        h ^= k

    h ^= length
    h = _fmix32(h)
    return h


def partition_key(row_key: str) -> str:
    key = row_key.split("_", 1)[0]
    h = murmur_hash_32(key.encode("utf-8"), 0)
    return f"{h % (1 << 20):05X}"   # uppercase 5-hex
```

## 4. Why 2^20?

`1048576 = 2^20`. This caps the partition cardinality at 1 048 576, keeping
the storage table behind a reasonable number of physical partitions. The
format string `X5` zero-pads to 5 hex chars (since `2^20 - 1 = 0xFFFFF`).
**Do not change to lowercase or to 6+ digit width** — the .NET runtime's
table queries use case-sensitive equality on PartitionKey.

## 5. Golden-vector tests

Capture vectors from a real `…actions` table on a sandbox LA Std:

```python
@pytest.mark.parametrize("row_key,expected_partition", [
    ("20D26F58B6A24A269A0D9DB7C7B0AE76_someAction", "<5-hex>"),
    ...
])
def test_partition_key_matches_dotnet(row_key, expected_partition):
    assert partition_key(row_key) == expected_partition
```

A simple way to harvest: query the table with the .NET tool's
`Tools GeneratePrefix` to find the right table name, then in Azure Storage
Explorer copy 5–10 (PartitionKey, RowKey) pairs.

## 6. Common bug

Calling `partition_key` with an already-trimmed key (i.e. without `_`) will
hash the entire key including any colons/dashes. That's actually fine — the
function happily returns `key` itself when no `_` is present — but make
sure callers in `MergeRunHistory` pass the *full* RowKey, not a pre-split
segment.
