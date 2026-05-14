"""Run-history payload decoder — mirrors Shared/ContentDecoder.cs.

Action / history table rows store inputs and outputs as compressed JSON
blobs in `InputsLinkCompressed` / `OutputsLinkCompressed`. The decoded
JSON has two shapes:

  * `{"nestedContentLinks": {"body": {...}}}` — connector body payload
  * `{...}` — flat `CommonPayloadStructure`

Each `body` carries either an `inlinedContent` (base64 string) or a
`uri` pointing at a blob in storage. `actual_content()` returns the
decoded inlined content when present, otherwise the blob URI string.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

from . import compression


@dataclass
class DecodedContent:
    raw: dict[str, Any] | None
    inlined_content: str = ""
    blob_uri: str = ""
    is_empty: bool = False

    @property
    def is_blob_link(self) -> bool:
        return bool(self.blob_uri)

    @property
    def actual_content(self) -> str:
        return self.inlined_content or self.blob_uri

    def search_keyword(self, keyword: str) -> bool:
        """Mirrors ContentDecoder.SearchKeyword(includeBlob=false)."""
        if self.is_empty:
            return False
        if self.inlined_content and keyword in self.inlined_content:
            return True
        return False


def _payload_body(payload: dict[str, Any]) -> dict[str, Any]:
    nested = payload.get("nestedContentLinks") or {}
    body = nested.get("body") if isinstance(nested, dict) else None
    if isinstance(body, dict):
        return body
    return payload


def decode_content(binary: bytes | None) -> DecodedContent:
    """Decompress + parse a *Compressed binary column from a run-history row."""
    if not binary:
        return DecodedContent(raw=None, is_empty=True)
    raw_str = compression.decompress(binary)
    if not raw_str:
        return DecodedContent(raw=None, is_empty=True)
    try:
        raw_obj: Any = json.loads(raw_str)
    except json.JSONDecodeError:
        return DecodedContent(raw=None, inlined_content=raw_str)
    if not isinstance(raw_obj, dict):
        return DecodedContent(raw=None, inlined_content=raw_str)
    body = _payload_body(raw_obj)
    inlined_b64 = body.get("inlinedContent") if isinstance(body, dict) else None
    blob_uri = body.get("uri") if isinstance(body, dict) else None
    inlined = ""
    if isinstance(inlined_b64, str) and inlined_b64:
        try:
            inlined = base64.b64decode(inlined_b64).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            inlined = ""
    return DecodedContent(
        raw=raw_obj,
        inlined_content=inlined,
        blob_uri=blob_uri or "",
    )


def decode_error(binary: bytes | None) -> str:
    """Decompress an Error column to a raw JSON string (or empty)."""
    if not binary:
        return ""
    return compression.decompress(binary) or ""
