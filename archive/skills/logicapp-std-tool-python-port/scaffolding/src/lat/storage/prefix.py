"""Murmur32 / Murmur64 hashes and storage-resource naming helpers.

Ported from Shared/StoragePrefixGenerator.cs. **DO NOT** substitute the
`mmh3` PyPI library — the hash produced here is custom-tail-handling and
must match the .NET output byte-for-byte. See
references/01-storage-prefix-hashing.md for the full spec.
"""
from __future__ import annotations

MASK32 = 0xFFFFFFFF
C1_64 = 0x239B961B  # 597399067
C2_64 = 0xAB0E9789  # 2869860233
C1_32 = 0xCC9E2D51
C2_32 = 0x1B873593


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
    return b[i] | (b[i + 1] << 8) | (b[i + 2] << 16) | (b[i + 3] << 24)


def murmur_hash_64(data: bytes, seed: int = 0) -> int:
    """Custom 64-bit Murmur variant used by the LA runtime.

    See Shared/StoragePrefixGenerator.cs:79-139.
    """
    length = len(data)
    h1 = seed & MASK32
    h2 = seed & MASK32
    i = 0

    while i + 7 < length:
        k1 = _read_u32_le(data, i)
        k2 = _read_u32_le(data, i + 4)

        k1 = (k1 * C1_64) & MASK32
        k1 = _rotl32(k1, 15)
        k1 = (k1 * C2_64) & MASK32
        h1 ^= k1
        h1 = _rotl32(h1, 19)
        h1 = (h1 + h2) & MASK32
        h1 = (h1 * 5 + 0x561CCD1B) & MASK32

        k2 = (k2 * C2_64) & MASK32
        k2 = _rotl32(k2, 17)
        k2 = (k2 * C1_64) & MASK32
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
            k1 = data[i] | (data[i + 1] << 8) | (data[i + 2] << 16)
        elif remaining == 2:
            k1 = data[i] | (data[i + 1] << 8)
        else:
            k1 = data[i]
        k1 = (k1 * C1_64) & MASK32
        k1 = _rotl32(k1, 15)
        k1 = (k1 * C2_64) & MASK32
        h1 ^= k1

        if remaining > 4:
            if remaining == 7:
                k2 = data[i + 4] | (data[i + 5] << 8) | (data[i + 6] << 16)
            elif remaining == 6:
                k2 = data[i + 4] | (data[i + 5] << 8)
            else:
                k2 = data[i + 4]
            k2 = (k2 * C2_64) & MASK32
            k2 = _rotl32(k2, 17)
            k2 = (k2 * C1_64) & MASK32
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


def murmur_hash_32(data: bytes, seed: int = 0) -> int:
    """Standard MurmurHash3 x86_32 — used for partition keys.

    See Shared/StoragePrefixGenerator.cs:46-77.
    """
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
            k = data[i] | (data[i + 1] << 8) | (data[i + 2] << 16)
        elif tail == 2:
            k = data[i] | (data[i + 1] << 8)
        else:
            k = data[i]
        k = (k * C1_32) & MASK32
        k = _rotl32(k, 15)
        k = (k * C2_32) & MASK32
        h ^= k

    h ^= length
    return _fmix32(h)


def _trim(hex_str: str, limit: int = 32) -> str:
    if limit < 17:
        raise ValueError("limit must be >= 17")
    keep = limit - 17
    return hex_str if len(hex_str) <= keep else hex_str[:keep]


def generate(name: str) -> str:
    """Generate the 15-char lowercase hex prefix for a UTF-8 name."""
    h = murmur_hash_64(name.encode("utf-8"), 0)
    return _trim(format(h, "X"), 32).lower()


def partition_key(row_key: str) -> str:
    """Derive a 5-uppercase-hex partition key from a RowKey.

    See Shared/StoragePrefixGenerator.cs:21-30.
    """
    key = row_key.split("_", 1)[0]
    h = murmur_hash_32(key.encode("utf-8"), 0)
    return f"{h % (1 << 20):05X}"


# ---------------------------------------------------------------------------
# Naming helpers (see references/04-table-schema.md and 05-resource-naming.md)
# ---------------------------------------------------------------------------


def logic_app_prefix(la_name: str) -> str:
    return generate(la_name.lower())


def workflow_prefix(flow_id: str) -> str:
    return generate(flow_id.lower())


def main_definition_table(la_name: str) -> str:
    return f"flow{logic_app_prefix(la_name)}flows"


def per_flow_table(la_name: str, flow_id: str, suffix: str) -> str:
    """suffix ∈ {flows, runs, histories}"""
    return f"flow{logic_app_prefix(la_name)}{workflow_prefix(flow_id)}{suffix}"


def per_day_action_table(la_name: str, flow_id: str, yyyymmdd: str) -> str:
    return f"flow{logic_app_prefix(la_name)}{workflow_prefix(flow_id)}{yyyymmdd}t000000zactions"


def per_day_variable_table(la_name: str, flow_id: str, yyyymmdd: str) -> str:
    return f"flow{logic_app_prefix(la_name)}{workflow_prefix(flow_id)}{yyyymmdd}t000000zvariables"


def per_flow_container_or_queue(la_name: str, flow_id: str) -> str:
    return f"flow{logic_app_prefix(la_name)}{workflow_prefix(flow_id)}"


def format_raw_key(raw: str) -> str:
    """Escape underscores and hyphens in RowKey segments.

    See Shared/TableOperations.cs:93-96.
    """
    return raw.replace("_", ":5F").replace("-", ":2D")


def flowlookup_rowkey(workflow_name: str) -> str:
    """RowKey of the FLOWLOOKUP row for an active workflow name (uppercased)."""
    return (
        "MYEDGEENVIRONMENT_FLOWLOOKUP-MYEDGERESOURCEGROUP-"
        + format_raw_key(workflow_name.upper())
    )
