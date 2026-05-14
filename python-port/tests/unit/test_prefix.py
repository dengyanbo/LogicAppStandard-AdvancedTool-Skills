"""Golden-vector tests for storage prefix hashing.

All `EXPECTED_*` constants were captured by running the .NET
`LogicAppAdvancedTool.exe Tools GeneratePrefix` against the same inputs on
2026-05-14. If any of these tests fail the Python port will compute the
wrong storage resource names and silently target the wrong workflow.
"""
from __future__ import annotations

import pytest

from lat.storage.prefix import (
    generate,
    logic_app_prefix,
    main_definition_table,
    murmur_hash_32,
    murmur_hash_64,
    partition_key,
    per_day_action_table,
    per_day_variable_table,
    per_flow_container_or_queue,
    per_flow_table,
    workflow_prefix,
)


# ---------------------------------------------------------------------------
# Bare `generate()` vectors — match Tools GeneratePrefix (no input lowercasing)
# ---------------------------------------------------------------------------

GENERATE_VECTORS = [
    ("myla", "7af80ee1bb2e167"),
    ("MyLogicApp", "9584982b3a036bb"),
    ("mylogicapp", "3fa3e8f6cecdc74"),
    ("test-la-1", "25b536ddefd5aaa"),
    ("logicapp-2026", "4bdc1530df0d03a"),
    ("logicapp-with-mixed-case-2026", "bd8d56e2cf517bc"),
    ("logicapp-with-very-long-name-2025", "c54f8578ef707b0"),
    ("a", "25488a37fbdfb87"),
    ("11111111-1111-1111-1111-111111111111", "f64208cfbb7a724"),
    ("abc12345-6789-0abc-def0-123456789abc", "d0b0d1172c798b8"),
    ("00000000-0000-0000-0000-000000000000", "81d01d0b42a4e11"),
    ("fedcba98-7654-3210-fedc-ba9876543210", "97c913ed401c0cc"),
]


@pytest.mark.parametrize("inp,expected", GENERATE_VECTORS)
def test_generate_matches_dotnet(inp: str, expected: str) -> None:
    """Verify bare `generate()` against captured .NET vectors."""
    assert generate(inp) == expected


def test_generate_output_format() -> None:
    """Every output is 15 lowercase hex chars (15 = 32 - 17 trim)."""
    for inp, _ in GENERATE_VECTORS:
        out = generate(inp)
        assert len(out) == 15, f"length != 15 for {inp!r}: {out!r}"
        assert out == out.lower(), f"not lowercase: {out!r}"
        int(out, 16)


# ---------------------------------------------------------------------------
# Production helpers (lowercase input) — match Common.cs:38,43,45 pattern.
# ---------------------------------------------------------------------------


def test_logic_app_prefix_lowercases_input() -> None:
    """logic_app_prefix mirrors AppSettings.LogicAppName.ToLower() in Common.cs."""
    assert logic_app_prefix("MyLogicApp") == "3fa3e8f6cecdc74"
    assert logic_app_prefix("mylogicapp") == "3fa3e8f6cecdc74"
    assert logic_app_prefix("MyLogicApp") == logic_app_prefix("MYLOGICAPP")


def test_workflow_prefix_lowercases_input() -> None:
    """workflow_prefix lowercases per Common.cs:45 production usage."""
    assert workflow_prefix("ABC12345-6789-0ABC-DEF0-123456789ABC") == "d0b0d1172c798b8"
    assert workflow_prefix("abc12345-6789-0abc-def0-123456789abc") == "d0b0d1172c798b8"


# ---------------------------------------------------------------------------
# Murmur32 — standard MurmurHash3 x86_32 with seed 0 (public test vectors).
# Sources: https://github.com/aappleby/smhasher KAT.
# ---------------------------------------------------------------------------


def test_murmur_hash_32_known_vectors() -> None:
    assert murmur_hash_32(b"", 0) == 0
    assert murmur_hash_32(b"", 1) == 0x514E28B7
    assert murmur_hash_32(b"a", 0) == 0x3C2569B2
    assert murmur_hash_32(b"abc", 0) == 0xB3DD93FA
    assert murmur_hash_32(b"abcd", 0) == 0x43ED676A
    assert murmur_hash_32(b"Hello, world!", 0) == 0xC0363E43


def test_murmur_hash_64_lengths_and_determinism() -> None:
    """The custom Murmur64 returns a 64-bit value, deterministic for same input."""
    h = murmur_hash_64(b"hello", 0)
    assert 0 <= h < (1 << 64)
    assert murmur_hash_64(b"hello", 0) == h
    assert murmur_hash_64(b"hello", 0) != murmur_hash_64(b"hello", 1)


def test_murmur_hash_64_matches_dotnet_via_generate() -> None:
    """Indirectly verify Murmur64 by exercising generate(), which formats it."""
    h = murmur_hash_64(b"a", 0)
    full_hex = format(h, "X")
    assert full_hex[:15].lower() == "25488a37fbdfb87"


# ---------------------------------------------------------------------------
# partition_key — Murmur32 of pre-underscore segment, mod 2^20, 5-uppercase-hex.
# ---------------------------------------------------------------------------


def test_partition_key_format() -> None:
    out = partition_key("anyrowkey")
    assert len(out) == 5
    assert out == out.upper()
    int(out, 16)


def test_partition_key_splits_on_underscore() -> None:
    assert partition_key("abc_def_ghi") == partition_key("abc")
    assert partition_key("abc") == partition_key("abc_anything")


def test_partition_key_range() -> None:
    """All outputs are < 2^20 = 1048576."""
    for key in ["abc", "abc123", "RUNID", "08584737551867954143243946780CU57"]:
        out = partition_key(key)
        assert int(out, 16) < (1 << 20)


# ---------------------------------------------------------------------------
# Naming helpers — end-to-end production table names.
# ---------------------------------------------------------------------------


def test_main_definition_table_shape() -> None:
    """Main table = flow + 15-hex-LA-prefix + 'flows'."""
    name = main_definition_table("MyLogicApp")
    assert name == "flow3fa3e8f6cecdc74flows"


def test_per_flow_table_shape() -> None:
    name = per_flow_table("MyLogicApp", "abc12345-6789-0abc-def0-123456789abc", "runs")
    assert name == "flow3fa3e8f6cecdc74d0b0d1172c798b8runs"


def test_per_day_action_table_shape() -> None:
    name = per_day_action_table("mylogicapp", "abc12345-6789-0abc-def0-123456789abc", "20260514")
    assert name == "flow3fa3e8f6cecdc74d0b0d1172c798b820260514t000000zactions"


def test_per_day_variable_table_shape() -> None:
    name = per_day_variable_table("mylogicapp", "abc12345-6789-0abc-def0-123456789abc", "20260514")
    assert name == "flow3fa3e8f6cecdc74d0b0d1172c798b820260514t000000zvariables"


def test_per_flow_container_or_queue_shape() -> None:
    name = per_flow_container_or_queue("mylogicapp", "abc12345-6789-0abc-def0-123456789abc")
    assert name == "flow3fa3e8f6cecdc74d0b0d1172c798b8"
