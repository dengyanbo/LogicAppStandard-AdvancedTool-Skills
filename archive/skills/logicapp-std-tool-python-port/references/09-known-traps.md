# Reference 09 — Known Traps (Gotchas to Avoid)

A consolidated list of subtle bugs that have either been observed in the
.NET codebase, or that a Python re-implementation is almost guaranteed to
hit if the author doesn't know about them up front. Each entry has a
**symptom** an agent might observe and the **fix**.

## 1. RowKey GUID-case sensitivity

**Symptom.** After `MergeRunHistory`, half the merged runs show up in the
live workflow's history; the other half are orphaned in the source's old
tables.

**Cause.** `Operations/MergeRunHistory.cs:131-135`:

```csharp
te["FlowId"] = targetID;
te.RowKey = te.RowKey.Replace(sourceID.ToUpper(), targetID.ToUpper());
```

The replacement is **case-sensitive** and uses the uppercase GUID. If your
Python port lower-cases `sourceID` (e.g. because you canonicalize GUIDs in
storage helpers), the `.replace()` won't match and the rewritten RowKey
will contain the old source GUID. Storage Tables will then partition the
row to the wrong partition key, and the run is effectively orphaned.

**Fix.**

```python
src_upper = source_id.upper()
tgt_upper = target_id.upper()
new_row_key = entity["RowKey"].replace(src_upper, tgt_upper)
```

Always uppercase **before** the replace. Never normalize RowKeys.

## 2. PartitionKey re-derivation after RowKey rewrite

**Symptom.** Storage transactions fail with HTTP 400 *"All entities in a
batch must have the same PartitionKey"*, or rewritten rows are silently
unreachable.

**Cause.** When you rewrite a RowKey (as in §1), the partition key must be
re-derived from the new RowKey via `partition_key()` (`references/02`).
Carrying the old partition key forward sends the entity to the wrong
partition; the LA runtime will not find it.

**Fix.**

```python
new_row_key = entity["RowKey"].replace(source_id.upper(), target_id.upper())
new_pk = partition_key(new_row_key)
entity["RowKey"] = new_row_key
entity["PartitionKey"] = new_pk
```

## 3. The 100-entity / 4-MB transaction limit

**Symptom.** `submit_transaction` raises a 400 from Storage; only the first
99 entities of a batch are committed.

**Cause.** Storage Tables hard-limit transactions to 100 entities and
4 MB. The .NET tool groups by partition key and flushes at 100
(`Operations/MergeRunHistory.cs:144-149`). The Python port must do the
same and, for large payloads (compressed blobs in InputsLinkCompressed),
also flush early if total batch size approaches 3.5 MB.

**Fix.** See the batched-upsert helper in `references/04-table-schema.md`
§5. Add a byte-size guard:

```python
if len(json.dumps(batch).encode()) > 3_500_000:
    client.submit_transaction(batch)
    batch.clear()
```

## 4. Byte-for-byte hash mismatch

**Symptom.** `Tools GeneratePrefix -la <name>` from the .NET tool prints
`abc1234deadbeef` but your Python port prints `abc1234deadbeec`. All
subsequent table-name lookups return "table not found".

**Causes (ranked by frequency).**

1. Failure to mask intermediate `uint32` operations to 32 bits. Python
   integers are arbitrary-precision; without `& 0xFFFFFFFF` after every
   multiply/shift, values silently grow beyond 32 bits and break the
   subsequent mix steps.
2. Forgetting that callers lower-case the input *before* encoding to
   UTF-8 (`Shared/CommonOperations.cs:38`).
3. Using `mmh3.hash64` from the popular `mmh3` PyPI library. **The
   algorithm is similar but not identical**; constants and tail-handling
   differ subtly.
4. Confusing `Generate` (uses Murmur64) with `GeneratePartitionKey` (uses
   Murmur32). They share helpers but produce different outputs.

**Fix.** Use the implementation in `references/01-storage-prefix-hashing.md`
verbatim. Add unit tests with golden vectors harvested from the .NET tool.

## 5. ZSTD algorithm-byte rewind

**Symptom.** First ZSTD-encoded payload decodes as garbage; or
`zstandard.ZstdError: error reading frame header`.

**Cause.** `CompressUtility.DecompressContent` reads the first byte (low
3 bits) to dispatch, then rewinds (`memoryStream.Position--`) so the full
varint can be re-read. Forgetting to rewind makes you call ZSTD on bytes
starting one position past the frame header — corrupt output.

**Fix.** In Python you can work on `bytes` directly and just call the
varint reader from offset 0; see the implementation in
`references/03-compression-codec.md`.

## 6. Deflate path returns null in this fork

**Symptom.** `Backup` against an old Logic App (pre-Nov-2024) produces
empty definition files.

**Cause.** `CompressUtility.DecompressContent` has a `default: break;`
in the switch that returns `null` for any algorithm byte other than 6 or
7, even though the file `DeflateDecompress` private method still exists.
The Drac-Zhang fork's `CompressUtility.cs:24` returns `null` for legacy
Deflate rows.

**Fix.** Restore Deflate handling in the Python port (see
`references/03-compression-codec.md` §2). Use stdlib `zlib` with
`wbits=-zlib.MAX_WBITS` for raw Deflate (no zlib header).

## 7. Time-zone confusion in date filters

**Symptom.** `Backup -d 20240115` against a Logic App in UTC+8 misses
workflows modified on Jan 15.

**Cause.** All dates accepted by the tool are **UTC**, but the tool
formats them as ``"yyyy-MM-ddT00:00:00Z"`` and feeds to OData. If the user
mentally pictures a local-time day boundary, the filter window is wrong
by up to 24 hours.

**Fix.** In the Python port:
* Document UTC clearly in `--help` for every `-d`/`-st`/`-et` flag.
* Internally always construct `datetime(..., tzinfo=timezone.utc)`.
* Format with `.isoformat(timespec="seconds").replace("+00:00", "Z")`.

## 8. ARM throttling in BatchResubmit

**Symptom.** After ~50 resubmits, the tool stalls or returns HTTP 429.

**Cause.** Hostruntime resubmit endpoint is rate-limited to ~50 calls per
5 minutes per workflow.

**Fix.** Catch HTTP 429, sleep `Retry-After` (default 120 s if header
missing), retry up to 5 times. The C# implementation in
`Operations/BatchResubmit.cs` waits 2 minutes statically; the Python port
should honor `Retry-After` first.

## 9. MI token cached past expiry

**Symptom.** Long-running `BatchResubmit` or `MergeRunHistory` fails
midway with HTTP 401.

**Cause.** Tokens expire ~1 hour after issue. `Shared/MSITokenService`
exposes `VerifyToken` but the .NET tool's loops don't always call it.

**Fix.** In Python, call `verify_token(token)` at the *top* of every loop
iteration. The helper is cheap when the token has >5 min remaining.

## 10. UTF-8 BOM in inlined blob payloads

**Symptom.** Searches via `SearchInHistory -k <keyword> -b true` miss
keywords at position 0 of a payload.

**Cause.** Some inlined blob contents start with the UTF-8 BOM
(`\xEF\xBB\xBF`). `ContentDecoder.cs:82-85` strips the BOM before searching.

**Fix.** Mirror the strip:

```python
BOM = "\ufeff"
if text.startswith(BOM):
    text = text[len(BOM):]
```

## 11. `$content-type: application/octet-stream` payloads

**Symptom.** `SearchInHistory` returns false negatives for binary payloads
that include the keyword.

**Cause.** Some action inputs/outputs are wrapped as a JSON envelope
`{"$content-type": "...", "$content": "<base64>"}`. `ContentDecoder.cs:87-95`
recurses into the JSON tree and base64-decodes `$content` before
searching. The Python port must do the same.

**Fix.** Implement `decode_stream_to_string` per
`references/03-compression-codec.md` §7 + the C# source.

## 12. `MERGEDRUNHISTORY` rows never deleted

The .NET tool **only** upserts when merging; it does not delete the
source rows. After a successful merge, the *target* workflow has all the
runs, but the source workflow's per-flow tables still exist and contain
the same data. Cleaning them up is intentionally left to a follow-up
`CleanUpTables` / `CleanUpContainers`. Do not change this behavior — it
gives the operator a chance to verify the merge.

## 13. Hard-coded `C:\home\site\wwwroot`

`Shared/AppSettings.cs:75-81` returns `RootFolder = "C:\\home\\site\\wwwroot"`.
On the Python port:

* Default to `os.environ.get("LAT_ROOT_FOLDER", "C:/home/site/wwwroot")`.
* Allow override via `--root-folder` flag at the CLI level.
* Use `pathlib.Path` everywhere to avoid Windows `\\` vs POSIX `/` bugs.

## 14. ConsoleTable index column

`Shared/ConsoleTable.cs` auto-generates a 1-based row index for many
outputs (e.g. `ListVersions`, `ListWorkflows`). When the user is prompted
for a numeric selection (`CommonOperations.PromptInput`), the value is
decremented by 1 before being used as an array index. **Off-by-one is a
classic bug here** — write a test that selects index 1 vs index N and
asserts the correct entity is acted upon.

## 15. `Tools RunIDToDateTime` parses 20 chars, not 19

`Tools/RunIDToDatetime.cs:13` reads `runID.Substring(0, 20)`. The 20-char
slice is parsed as `long`, then `DateTime` ticks = `long.MaxValue -
parsedValue`. Output: `dt.ToString("yyyy-MM-ddTHH:mm:ssZ")`.

In Python:

```python
def run_id_to_datetime(run_id: str) -> datetime:
    reversed_ticks = int(run_id[:20])
    ticks = (1 << 63) - 1 - reversed_ticks            # long.MaxValue == 2^63 - 1
    # .NET ticks: 100-ns intervals since 0001-01-01 UTC.
    return datetime(1, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=ticks / 10)
```

Watch the precision: `timedelta` has microsecond resolution, so dividing
ticks by 10 loses 100 ns. The .NET tool already formats to seconds so the
loss is invisible.

## 16. Service tags fetch needs subscription Reader

`Shared/ServiceTagRetriever.cs:27` throws "Cannot retrieve service tags due
to permission issue…" when the response lacks `.values`. **Do not** fail
hard in the Python port when this occurs — many users intentionally do
not grant subscription Reader to their LA's MI. Instead, log a warning
and continue without service-tag-based subnet inference.

---

If you find a *new* trap while doing the port, add it to this file with
**symptom**, **cause**, and **fix**. This document is the cumulative
memory of what's hard about the migration.
