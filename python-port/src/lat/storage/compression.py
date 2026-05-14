"""ZSTD / Deflate compression — mirrors Shared/CompressUtility.cs.

See references/03-compression-codec.md for the full spec, including the
algorithm-byte dispatch (low 3 bits of the leading varint) and the
LEB128-like varint header used by the ZSTD path.
"""
from __future__ import annotations

import zlib

import zstandard as zstd


def _read_varint(buf: bytes, offset: int = 0) -> tuple[int, int]:
    value = 0
    shift = 0
    i = offset
    while True:
        b = buf[i]
        i += 1
        value |= (b & 0x7F) << shift
        if b < 0x80:
            return value, i
        shift += 7


def _write_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        chunk = value & 0x7F
        value >>= 7
        out.append(chunk | (0x80 if value else 0))
        if not value:
            break
    return bytes(out)


def compress(content: str) -> bytes:
    """Compress a string to ZSTD with the LA runtime's framing.

    Header varint = (uncompressed_length << 3) | 7 (algorithm byte = ZSTD).
    Compression level 1 (fastest), matching ModernCompressionUtility.
    """
    raw = content.encode("utf-8")
    header = _write_varint((len(raw) << 3) | 7)
    return header + zstd.ZstdCompressor(level=1).compress(raw)


def decompress(data: bytes | None) -> str | None:
    """Decompress a LA-runtime compressed payload.

    Dispatches by algorithm byte:
      * 7 → ZSTD (current default).
      * 6 → LZ4, not supported (raises).
      * else → Deflate (raw, no zlib header). Legacy pre-Nov-2024 rows.

    Returns None for empty / None input (mirrors C# null-return contract).
    """
    if not data:
        return None
    algorithm = data[0] & 7
    if algorithm == 7:
        length_and_algo, offset = _read_varint(data, 0)
        uncompressed_size = length_and_algo >> 3
        # The LA runtime omits the content size from the ZSTD frame header
        # itself (which python-zstandard requires by default); we recover it
        # from the varint prefix and pass it via max_output_size.
        return zstd.ZstdDecompressor().decompress(
            data[offset:], max_output_size=uncompressed_size
        ).decode("utf-8")
    if algorithm == 6:
        raise NotImplementedError("LZ4 compression is not supported")
    # Legacy Deflate path (raw deflate stream, no zlib header)
    return zlib.decompress(data, wbits=-zlib.MAX_WBITS).decode("utf-8")
