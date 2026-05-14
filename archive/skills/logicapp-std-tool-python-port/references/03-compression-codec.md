# Reference 03 — Compression Codec (ZSTD / Deflate framing)

Workflow definitions and most run-history payload fields are stored as
**compressed binary blobs** in storage tables. The first byte of the blob
selects the codec; everything after that is the codec frame (with a
prepended variable-length integer header for ZSTD).

The Python port must:
1. Decode the algorithm byte to dispatch to the right codec.
2. Read the varint-encoded uncompressed-length prefix (ZSTD path).
3. Decompress.
4. UTF-8 decode the result.

## 1. C# source

* `Shared/CompressUtility.cs` (full file, ~104 lines)
  * `DecompressContent(byte[] compressedContent)` — entry point, lines 11–28
  * `CompressContent(string)` — entry point, lines 30–33 (delegates to ZSTD)
  * `DeflateDecompress(byte[])` — Deflate path, lines 36–41
    (currently unused after the Nov 2024 migration but still required for
    legacy rows)
  * `ZSTDCompress(string)` — lines 45–59
  * `WriteVariableLengthInteger(Stream, long)` — lines 61–69
  * `ZSTDDecompress(MemoryStream)` — lines 71–82
  * `ReadVariableLengthInteger(Stream)` — lines 84–101

## 2. Algorithm-byte dispatch (exact rule)

```csharp
public static string DecompressContent(byte[] compressedContent)
{
    MemoryStream ms = new MemoryStream(compressedContent);
    int algorithm = ms.ReadByte() & 7;        // low 3 bits of first byte
    switch (algorithm)
    {
        case 6:
            throw new Exception("LZ4 compression is not supported");
        case 7:
            ms.Position--;                    // rewind to include the byte
            return ZSTDDecompress(ms);
        default:
            // (Deflate path returned null in 2024-11-15 build; the runtime
            // now only writes ZSTD. Older rows may still be Deflate.)
            return null;
    }
}
```

> **Important Deflate caveat.** The current `DecompressContent` returns
> `null` for non-ZSTD payloads after the Nov 2024 refactor. The Python port
> **must** restore the Deflate path for backwards compatibility — older
> storage tables still contain pre-migration definitions, and the C# tool
> has lost the ability to read them in this fork. Use stdlib `zlib`:
>
> ```python
> import zlib
> def _deflate_decompress(data: bytes) -> str:
>     return zlib.decompress(data, wbits=-zlib.MAX_WBITS).decode("utf-8")
> ```
>
> Note `wbits=-MAX_WBITS` for raw deflate (no zlib header). Cross-check
> against the canonical `microsoft/Logic-App-STD-Advanced-Tools` fork —
> if it has restored the path, port that version instead.

## 3. ZSTD framing

```csharp
private static string ZSTDDecompress(MemoryStream compressedStream)
{
    int uncompressedLength = (int)(ReadVariableLengthInteger(compressedStream) >> 3);
    using (var decompressionStream = new DecompressionStream(compressedStream))
    using (var temp = new MemoryStream())
    {
        decompressionStream.CopyTo(temp);
        return Encoding.UTF8.GetString(temp.ToArray());
    }
}
```

Two non-obvious points:

1. The varint encodes `(uncompressedLength << 3) | algorithm_byte`. The
   algorithm-byte (`7`) is already in the *low 3 bits* of the first varint
   byte — that is why `DecompressContent` reads the first byte, masks `& 7`,
   then **rewinds** so `ReadVariableLengthInteger` can re-read it. After
   reading the full varint, the algorithm bits are discarded with `>> 3`.
2. The remaining bytes are a standard **ZSTD raw frame** — pass them
   straight to `zstandard.ZstdDecompressor().decompress(...)`.

## 4. Variable-length integer (LEB128-like)

```csharp
private static long ReadVariableLengthInteger(Stream s)
{
    long num = 0, shift = 0;
    while (true)
    {
        int b = s.ReadByte();
        num |= (long)(((ulong)b & 0x7F) << shift);
        if (b < 128) break;
        shift += 7;
    }
    return num;
}
```

This is **unsigned LEB128**. Python equivalent:

```python
def _read_varint(buf: bytes, offset: int = 0) -> tuple[int, int]:
    """Return (value, new_offset)."""
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
```

## 5. Compress (writing definitions back via `IngestWorkflow`)

```csharp
private static byte[] ZSTDCompress(string uncompressedContent)
{
    byte[] raw = Encoding.UTF8.GetBytes(uncompressedContent);
    MemoryStream resultStream = new MemoryStream();
    using (var rawStream = new MemoryStream(raw))
    {
        WriteVariableLengthInteger(resultStream, (long)raw.Length * 8L | (byte)7);
        using (var compressStream = new CompressionStream(resultStream, 1, 0, false))  // level 1 = fastest
        {
            rawStream.CopyTo(compressStream);
        }
    }
    return resultStream.ToArray();
}
```

* The header varint = `(uncompressed_length * 8) | 7`. The `* 8` shifts the
  length 3 bits left to make room for the algorithm byte (`7` = ZSTD).
* ZSTD compression **level 1** (fastest). The Python `zstandard` package
  exposes this via `ZstdCompressor(level=1)`.

```python
import zstandard as zstd

def compress(content: str) -> bytes:
    raw = content.encode("utf-8")
    header = _write_varint((len(raw) << 3) | 7)
    compressor = zstd.ZstdCompressor(level=1)
    return header + compressor.compress(raw)


def decompress(data: bytes) -> str | None:
    if not data:
        return None
    algorithm = data[0] & 7
    if algorithm == 7:
        # Re-read varint from the *beginning* of data
        _length_and_algo, offset = _read_varint(data, 0)
        # Optional: uncompressed_length = _length_and_algo >> 3
        decompressor = zstd.ZstdDecompressor()
        return decompressor.decompress(data[offset:]).decode("utf-8")
    if algorithm == 6:
        raise NotImplementedError("LZ4 compression is not supported")
    # Legacy Deflate path
    return zlib.decompress(data, wbits=-zlib.MAX_WBITS).decode("utf-8")
```

## 6. Test vectors

* Round-trip a known JSON string and verify byte-for-byte equality of the
  compressed output against the .NET tool's `Tools` command (or run the
  .NET unit test if you add one). Note that ZSTD-level-1 output is
  deterministic for a fixed dictionary / level, but if the upstream
  switches level the byte equality may break; in that case test only
  decompression parity.
* Decode 3 real `DefinitionCompressed` values harvested from a sandbox
  Logic App storage table — one pre-Nov-2024 (Deflate) and two post (ZSTD).
* Decode an `InputsLinkCompressed` value from an actions table. The
  decoded JSON shape is described in `references/04-table-schema.md` and
  matched by `Structures/RunHistoryStructure.cs` (`CommonPayloadStructure`,
  `ConnectorPayloadStructure`).

## 7. Related: `ContentDecoder`

`Shared/ContentDecoder.cs` wraps `CompressUtility` and additionally:

* Parses the decompressed JSON into a `CommonPayloadStructure` (or
  `ConnectorPayloadStructure.nestedContentLinks.body`).
* Surfaces `inlinedContent` (Base64-encoded string) and `uri` (blob link
  for >32 KB payloads).
* Supports `SearchKeyword(keyword, includeBlob)` — fetches the blob if
  size < 1 MB and the caller opted in.

The Python port should mirror this in `lat/storage/payload.py`:

```python
@dataclass
class DecodedPayload:
    raw: dict | None
    inlined_content: str            # may be empty
    blob_uri: str                   # may be empty
    is_blob_link: bool
    is_empty: bool

    @property
    def actual_content(self) -> str:
        return self.inlined_content or self.blob_uri

    def search_keyword(self, keyword: str, include_blob: bool = False) -> bool: ...
```

See `Shared/ContentDecoder.cs:14-65` for the parsing rules and
`Shared/ContentDecoder.cs:107-136` for `DecodeStreamToString` (used when an
inlined payload has `$content-type: application/octet-stream`).
