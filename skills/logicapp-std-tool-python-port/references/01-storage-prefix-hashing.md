# Reference 01 — Storage Prefix Hashing (Murmur32 / Murmur64)

The single most important thing the Python port must reproduce exactly. Every
table, queue, and per-flow blob container name is built from these hashes.
A single bit difference here means the tool operates on the wrong (or
nonexistent) storage resource.

## 1. Where the algorithm lives in the source

* `Shared/StoragePrefixGenerator.cs`
  * `Generate(string name)` — top-level entry, lines 12–19
  * `GeneratePartitionKey(string rowKey)` — lines 21–30 (covered in
    `references/02-partition-key.md`)
  * `TrimStorageKeyPrefix(string key, int limit)` — lines 32–43
  * `MurmurHash32(byte[] data, uint seed=0)` — lines 46–77
  * `MurmurHash64(byte[] data, uint seed=0)` — lines 79–139
  * `RotateLeft32(this uint value, int count)` — lines 141–144

The C# header comment is emphatic: **"DO NOT change anything in MurmurHash64
method"**. Treat the published implementation as the canonical specification.

## 2. `Generate(name)` — high-level

```csharp
public static string Generate(string name)
{
    byte[] data = Encoding.UTF8.GetBytes(name);          // (1)
    string hashResult = MurmurHash64(data, 0U).ToString("X");  // (2)
    return TrimStorageKeyPrefix(hashResult, 32).ToLower();     // (3)
}
```

Translation to Python (`src/lat/storage/prefix.py`):

```python
def generate(name: str) -> str:
    data = name.encode("utf-8")
    h = murmur_hash_64(data, seed=0)
    return _trim(format(h, "X"), 32).lower()
```

Key contract details — get every one of these right:

1. The input is **UTF-8** encoded. Do not normalize, lowercase, or BOM-prefix it.
   * Callers in `CommonOperations.cs:38-46` always `.ToLower()` the
     `LogicAppName` and `flowId` **before** calling `Generate`. The Python port
     must do the same in `commands/*` glue code, *not* inside `generate`.
2. The intermediate hex string uses `.ToString("X")` — uppercase, **no
     padding to 16 chars**. Python `format(h, "X")` matches.
3. `TrimStorageKeyPrefix(prefix, 32)` keeps at most `32 - 17 = 15` chars
   (see `TrimStorageKeyPrefix`). If the hex is shorter than 15 chars it is
   returned as-is. After trimming, the result is `.ToLower()`.

### `TrimStorageKeyPrefix` exact rule

```csharp
private static string TrimStorageKeyPrefix(string storageKeyPrefix, int limit)
{
    if (limit < 17) throw new ArgumentException(...);
    if (storageKeyPrefix.Length <= limit - 17) return storageKeyPrefix;
    return storageKeyPrefix.Substring(0, limit - 17);
}
```

So for `limit=32`: keep first 15 chars; otherwise return whole string.

## 3. `MurmurHash64` — pseudocode

This is a variant of MurmurHash3 x86_128 reduced to 64-bit output. **It is
not the standard mmh3 library output** — do not substitute `mmh3.hash64`. The
constants below must be byte-identical.

```text
const uint C1 = 597399067;       // 0x239B961B
const uint C2 = 2869860233;      // 0xAB0E9789
const uint C3 = 951274213;       // (unused here, kept for reference)
const uint C4 = 2716044179;      // (unused here, kept for reference)
const uint MIX_FINAL_1 = 2246822507;  // 0x85EBCA6B
const uint MIX_FINAL_2 = 3266489909;  // 0xC2B2AE35

uint h1 = seed;
uint h2 = seed;
int i = 0;

while (i + 7 < length):
    uint k1 = read_uint32_le(data[i..i+4])
    uint k2 = read_uint32_le(data[i+4..i+8])

    k1 *= C1;  k1 = rotl32(k1, 15);  k1 *= C2;  h1 ^= k1
    h1 = rotl32(h1, 19);  h1 += h2;  h1 = h1 * 5 + 1444728091          // 0x561CCD1B

    k2 *= C2;  k2 = rotl32(k2, 17);  k2 *= C1;  h2 ^= k2
    h2 = rotl32(h2, 13);  h2 += h1;  h2 = h2 * 5 + 197830471           // 0x0BCAA747

    i += 8

int remaining = length - i

if remaining > 0:
    uint k1 = 0
    if remaining >= 4:
        k1 = read_uint32_le(data[i..i+4])
    elif remaining == 3:
        k1 = data[i] | (data[i+1] << 8) | (data[i+2] << 16)
    elif remaining == 2:
        k1 = data[i] | (data[i+1] << 8)
    else:  # remaining == 1
        k1 = data[i]
    k1 *= C1;  k1 = rotl32(k1, 15);  k1 *= C2;  h1 ^= k1

    if remaining > 4:
        uint k2 = 0
        if remaining == 7:
            k2 = data[i+4] | (data[i+5] << 8) | (data[i+6] << 16)
        elif remaining == 6:
            k2 = data[i+4] | (data[i+5] << 8)
        else:  # remaining == 5
            k2 = data[i+4]
        k2 *= C2;  k2 = rotl32(k2, 17);  k2 *= C1;  h2 ^= k2

h1 ^= length
h2 ^= length

h1 += h2
h2 += h1

h1 = fmix32(h1)        // h ^= h>>16; h *= 0x85EBCA6B; h ^= h>>13; h *= 0xC2B2AE35; h ^= h>>16
h2 = fmix32(h2)

h1 += h2
h2 += h1

return (uint64) h2 << 32 | (uint64) h1
```

> Note: the C# code keeps both halves and concatenates as
> `((ulong)num3 << 32) | (ulong)num2` — `num3` is `h2`, `num2` is `h1`. The
> resulting 64-bit value formatted as uppercase hex (no padding) is the
> input to `TrimStorageKeyPrefix`.

## 4. Python implementation skeleton

```python
# src/lat/storage/prefix.py
from __future__ import annotations

C1 = 0x239B961B
C2 = 0xAB0E9789
MASK32 = 0xFFFFFFFF


def _rotl32(x: int, n: int) -> int:
    x &= MASK32
    return ((x << n) | (x >> (32 - n))) & MASK32


def _fmix32(h: int) -> int:
    h ^= h >> 16
    h = (h * 0x85EBCA6B) & MASK32
    h ^= h >> 13
    h = (h * 0xC2B2AE35) & MASK32
    h ^= h >> 16
    return h


def _read_u32_le(b: bytes, i: int) -> int:
    return b[i] | (b[i+1] << 8) | (b[i+2] << 16) | (b[i+3] << 24)


def murmur_hash_64(data: bytes, seed: int = 0) -> int:
    length = len(data)
    h1 = seed & MASK32
    h2 = seed & MASK32
    i = 0

    while i + 7 < length:
        k1 = _read_u32_le(data, i)
        k2 = _read_u32_le(data, i + 4)

        k1 = (k1 * C1) & MASK32
        k1 = _rotl32(k1, 15)
        k1 = (k1 * C2) & MASK32
        h1 ^= k1
        h1 = _rotl32(h1, 19)
        h1 = (h1 + h2) & MASK32
        h1 = (h1 * 5 + 0x561CCD1B) & MASK32

        k2 = (k2 * C2) & MASK32
        k2 = _rotl32(k2, 17)
        k2 = (k2 * C1) & MASK32
        h2 ^= k2
        h2 = _rotl32(h2, 13)
        h2 = (h2 + h1) & MASK32
        h2 = (h2 * 5 + 0x0BCAA747) & MASK32

        i += 8

    remaining = length - i
    if remaining > 0:
        if remaining >= 4:
            k1 = _read_u32_le(data, i)
        elif remaining == 3:
            k1 = data[i] | (data[i+1] << 8) | (data[i+2] << 16)
        elif remaining == 2:
            k1 = data[i] | (data[i+1] << 8)
        else:
            k1 = data[i]
        k1 = (k1 * C1) & MASK32
        k1 = _rotl32(k1, 15)
        k1 = (k1 * C2) & MASK32
        h1 ^= k1
        if remaining > 4:
            if remaining == 7:
                k2 = data[i+4] | (data[i+5] << 8) | (data[i+6] << 16)
            elif remaining == 6:
                k2 = data[i+4] | (data[i+5] << 8)
            else:
                k2 = data[i+4]
            k2 = (k2 * C2) & MASK32
            k2 = _rotl32(k2, 17)
            k2 = (k2 * C1) & MASK32
            h2 ^= k2

    h1 ^= length
    h2 ^= length
    h1 = (h1 + h2) & MASK32
    h2 = (h2 + h1) & MASK32
    h1 = _fmix32(h1)
    h2 = _fmix32(h2)
    h1 = (h1 + h2) & MASK32
    h2 = (h2 + h1) & MASK32
    return (h2 << 32) | h1


def _trim(hex_str: str, limit: int = 32) -> str:
    if limit < 17:
        raise ValueError("limit must be >= 17")
    keep = limit - 17
    return hex_str if len(hex_str) <= keep else hex_str[:keep]


def generate(name: str) -> str:
    """Generate a 15-char lowercase hex prefix from a name (UTF-8)."""
    h = murmur_hash_64(name.encode("utf-8"), 0)
    return _trim(format(h, "X"), 32).lower()
```

## 5. Putting prefixes together (resource names)

Callers in `Shared/CommonOperations.cs:36-63`:

```csharp
string logicAppPrefix = StoragePrefixGenerator.Generate(AppSettings.LogicAppName.ToLower());
string workflowPrefix = StoragePrefixGenerator.Generate(workflowID.ToLower());

string mainDefinitionTable    = $"flow{logicAppPrefix}flows";
string perFlowFlowsTable      = $"flow{logicAppPrefix}{workflowPrefix}flows";
string perFlowRunsTable       = $"flow{logicAppPrefix}{workflowPrefix}runs";
string perFlowHistoriesTable  = $"flow{logicAppPrefix}{workflowPrefix}histories";
// Date-partitioned action / variable tables (note the t000000z infix):
string actionTable    = $"flow{logicAppPrefix}{workflowPrefix}{yyyyMMdd}t000000zactions";
string variableTable  = $"flow{logicAppPrefix}{workflowPrefix}{yyyyMMdd}t000000zvariables";
```

The Python port should expose these as helper functions in
`storage/prefix.py`:

```python
def logic_app_prefix(la_name: str) -> str:
    return generate(la_name.lower())

def workflow_prefix(flow_id: str) -> str:
    return generate(flow_id.lower())

def main_definition_table(la_name: str) -> str:
    return f"flow{logic_app_prefix(la_name)}flows"

def workflow_table(la_name: str, flow_id: str, kind: str, date: str | None = None) -> str:
    base = f"flow{logic_app_prefix(la_name)}{workflow_prefix(flow_id)}"
    if kind in ("actions", "variables"):
        if date is None:
            raise ValueError(f"date required for {kind} table")
        return f"{base}{date}t000000z{kind}"
    return f"{base}{kind}"  # flows / runs / histories
```

## 6. Golden-vector tests (mandatory before declaring this module done)

Generate these once against the .NET binary (deploy it to a sandbox LA Std
and call `Tools GeneratePrefix -la <name> -wf <flowId>`) then bake them into
`tests/unit/test_prefix.py`:

```python
@pytest.mark.parametrize("la_name,flow_id,expected_prefix", [
    # Capture from `Tools GeneratePrefix` output in your sandbox:
    ("my-sandbox-la", "<some-guid>", "<15-char-lowercase-hex>"),
    ...
])
def test_prefix_matches_dotnet(la_name, flow_id, expected_prefix):
    p = workflow_prefix(flow_id)
    assert p == expected_prefix
```

If the test fails: re-check that you `.lower()` *before* `encode("utf-8")`,
not after, and that you're using the 64-bit variant (not the 32-bit
variant from `GeneratePartitionKey`).
