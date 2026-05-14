"""Tests for ZSTD/Deflate compression framing.

Round-trip and cross-language compatibility verified manually via
`_smoke_compression.py` against the .NET `Tools DecodeZSTD` CLI.
"""
from __future__ import annotations

import pytest

from lat.storage.compression import (
    _read_varint,
    _write_varint,
    compress,
    decompress,
)


ROUND_TRIP_PAYLOADS = [
    pytest.param("", id="empty"),
    pytest.param("a", id="single-char"),
    pytest.param("short", id="short"),
    pytest.param("{}", id="empty-json"),
    pytest.param('{"hello":"world"}', id="small-json"),
    pytest.param('{"name":"MyWorkflow","kind":"Stateful","definition":{}}', id="workflow-shell"),
    pytest.param("a" * 500, id="500-a"),
    pytest.param("x" * 50_000, id="50k-x"),
    pytest.param("日本語テスト", id="japanese"),
    pytest.param("   leading/trailing whitespace   ", id="whitespace"),
    pytest.param("Mixed 中文 + emoji 🚀 + tabs\tand\nnewlines", id="mixed-unicode"),
]


@pytest.mark.parametrize("payload", ROUND_TRIP_PAYLOADS)
def test_round_trip(payload: str) -> None:
    if payload == "":
        out = decompress(compress(payload))
        assert out == ""
    else:
        assert decompress(compress(payload)) == payload


def test_decompress_none_returns_none() -> None:
    assert decompress(None) is None


def test_decompress_empty_returns_none() -> None:
    assert decompress(b"") is None


def test_decompress_lz4_raises() -> None:
    bad = bytes([0b0000_0110]) + b"\x00" * 4
    with pytest.raises(NotImplementedError):
        decompress(bad)


def test_compress_sets_algorithm_byte_to_zstd() -> None:
    raw = compress("hello")
    assert raw[0] & 0b111 == 7


def test_zstd_header_length_encodes_uncompressed_size() -> None:
    """varint value >> 3 == uncompressed length."""
    payload = "hello world"
    raw = compress(payload)
    value, _offset = _read_varint(raw, 0)
    assert value >> 3 == len(payload.encode("utf-8"))


@pytest.mark.parametrize(
    "value",
    [0, 1, 7, 0x7F, 0x80, 0xFF, 0x3FFF, 0x4000, 0xFFFFFF, 0x7FFFFFFF, 0xFFFFFFFF, 1 << 40],
)
def test_varint_round_trip(value: int) -> None:
    encoded = _write_varint(value)
    decoded, offset = _read_varint(encoded, 0)
    assert decoded == value
    assert offset == len(encoded)


def test_varint_encoding_examples() -> None:
    """Specific encodings per LEB128-like little-endian 7-bit chunks."""
    assert _write_varint(0) == b"\x00"
    assert _write_varint(0x7F) == b"\x7F"
    assert _write_varint(0x80) == b"\x80\x01"
    assert _write_varint(0x3FFF) == b"\xFF\x7F"
    assert _write_varint(0x4000) == b"\x80\x80\x01"


def test_decompress_zstd_frame_without_content_size() -> None:
    """Mirrors what the LA runtime emits: ZSTD frame WITHOUT content size hint.

    The .NET runtime compresses with the content size omitted from the ZSTD
    frame header (it relies on the varint prefix carrying the uncompressed
    length). python-zstandard's default `ZstdCompressor().compress()` *does*
    embed the content size; we have to construct the no-size frame by hand
    via stream_writer to exercise the same code path.
    """
    import io

    import zstandard as zstd

    payload = '{"definition":{"actions":{"a":{}}},"kind":"Stateful"}'
    raw = payload.encode("utf-8")

    # Build a ZSTD frame that omits the content-size header.
    buf = io.BytesIO()
    writer = zstd.ZstdCompressor(level=1).stream_writer(buf, size=-1)
    writer.write(raw)
    writer.flush(zstd.FLUSH_FRAME)
    compressed_no_size = buf.getvalue()

    # Verify the frame really lacks the content size (4th bit of frame header
    # descriptor is the "content size flag"; bytes 4-5 are header descriptor).
    # Easier sanity check: the default-decompressor without size hint must fail.
    with pytest.raises(zstd.ZstdError):
        zstd.ZstdDecompressor().decompress(compressed_no_size)

    # Now wrap with our LA-runtime varint header and verify our decompress()
    # recovers the original payload via the max_output_size fallback path.
    header = _write_varint((len(raw) << 3) | 7)
    framed = header + compressed_no_size

    out = decompress(framed)
    assert out == payload
