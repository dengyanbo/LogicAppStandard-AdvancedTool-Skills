"""Shared test fixtures for `lat` unit tests.

Provides an in-memory replacement for `azure.data.tables.TableClient` /
`TableServiceClient` so storage-table commands can be exercised without
spinning Azurite. The fake supports the subset of OData filter syntax
the .NET tool actually emits (eq/ne/ge/gt/le/lt with string/datetime/
number literals, joined by and/or).
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Iterable

import pytest


# ---------------------------------------------------------------------------
# Mini OData filter parser
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"""
    \s*(
        (?P<dt>datetime'(?P<dt_val>[^']*)')
      | (?P<str>'(?P<str_val>(?:[^']|'')*)')
      | (?P<num>-?\d+(?:\.\d+)?)
      | (?P<op>\b(?:eq|ne|ge|gt|le|lt|and|or|not)\b)
      | (?P<lpar>\()
      | (?P<rpar>\))
      | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
    )\s*
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _tokenize(filter_str: str) -> list[tuple[str, Any]]:
    tokens: list[tuple[str, Any]] = []
    pos = 0
    while pos < len(filter_str):
        m = _TOKEN_RE.match(filter_str, pos)
        if not m or m.end() == pos:
            raise ValueError(f"Cannot parse filter at {pos}: {filter_str!r}")
        pos = m.end()
        if m.group("dt") is not None:
            dt_val = m.group("dt_val").replace("Z", "+00:00")
            tokens.append(("LIT", _dt.datetime.fromisoformat(dt_val)))
        elif m.group("str") is not None:
            tokens.append(("LIT", m.group("str_val").replace("''", "'")))
        elif m.group("num") is not None:
            raw = m.group("num")
            tokens.append(("LIT", float(raw) if "." in raw else int(raw)))
        elif m.group("op") is not None:
            tokens.append(("OP", m.group("op").lower()))
        elif m.group("lpar") is not None:
            tokens.append(("LPAR", "("))
        elif m.group("rpar") is not None:
            tokens.append(("RPAR", ")"))
        else:
            tokens.append(("IDENT", m.group("ident")))
    return tokens


def _to_dt(x: Any) -> _dt.datetime | None:
    if isinstance(x, _dt.datetime):
        return x
    if isinstance(x, str):
        try:
            return _dt.datetime.fromisoformat(x.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _cmp(left: Any, op: str, right: Any) -> bool:
    if isinstance(right, _dt.datetime):
        left = _to_dt(left)
    if op == "eq":
        return left == right
    if op == "ne":
        return left != right
    if left is None:
        return False
    try:
        if op == "ge":
            return left >= right
        if op == "gt":
            return left > right
        if op == "le":
            return left <= right
        if op == "lt":
            return left < right
    except TypeError:
        return False
    return False


def _eval_filter(filter_str: str, entity: dict[str, Any]) -> bool:
    """Evaluate an OData filter string against a single entity."""
    if not filter_str or not filter_str.strip():
        return True

    tokens = _tokenize(filter_str)
    pos = [0]

    def peek() -> tuple[str, Any]:
        return tokens[pos[0]] if pos[0] < len(tokens) else ("END", None)

    def consume() -> tuple[str, Any]:
        tok = tokens[pos[0]]
        pos[0] += 1
        return tok

    def cmp_expr() -> bool:
        t, v = peek()
        if t == "LPAR":
            consume()
            res = or_expr()
            t, _ = peek()
            if t != "RPAR":
                raise ValueError("Expected )")
            consume()
            return res
        if t == "OP" and v == "not":
            consume()
            return not cmp_expr()
        if t != "IDENT":
            raise ValueError(f"Expected identifier, got {t} {v}")
        field = v
        consume()
        t, op = peek()
        if t != "OP" or op not in ("eq", "ne", "ge", "gt", "le", "lt"):
            raise ValueError(f"Expected comparison op, got {t} {op}")
        consume()
        t, lit = peek()
        if t != "LIT":
            raise ValueError(f"Expected literal, got {t} {lit}")
        consume()
        return _cmp(entity.get(field), op, lit)

    def and_expr() -> bool:
        result = cmp_expr()
        while True:
            t, v = peek()
            if t == "OP" and v == "and":
                consume()
                rhs = cmp_expr()
                result = result and rhs
            else:
                return result

    def or_expr() -> bool:
        result = and_expr()
        while True:
            t, v = peek()
            if t == "OP" and v == "or":
                consume()
                rhs = and_expr()
                result = result or rhs
            else:
                return result

    res = or_expr()
    if pos[0] != len(tokens):
        raise ValueError(f"Trailing tokens at {pos[0]}: {tokens[pos[0]:]}")
    return res


# ---------------------------------------------------------------------------
# Fake TableClient + TableServiceClient
# ---------------------------------------------------------------------------


class _ItemPaged(list):
    """Stand-in for azure.data.tables ItemPaged: iter + by_page()."""

    def __init__(self, items: Iterable[dict[str, Any]], page_size: int = 1000) -> None:
        super().__init__(items)
        self._page_size = max(1, page_size)

    def by_page(self):
        for i in range(0, len(self), self._page_size):
            yield list(self[i : i + self._page_size])


class FakeTableClient:
    """In-memory replacement for azure.data.tables.TableClient."""

    def __init__(self, name: str = "") -> None:
        self.name = name
        self._rows: dict[tuple[str, str], dict[str, Any]] = {}
        # Test observability
        self.transactions: list[list[tuple[str, dict[str, Any]]]] = []
        self.create_calls: list[dict[str, Any]] = []
        self.upsert_calls: list[dict[str, Any]] = []
        self.update_calls: list[dict[str, Any]] = []
        self.delete_calls: list[tuple[str, str]] = []

    # Seeding helper for tests --------------------------------------------

    def seed(self, *entities: dict[str, Any]) -> "FakeTableClient":
        for ent in entities:
            self._rows[(ent["PartitionKey"], ent["RowKey"])] = dict(ent)
        return self

    @property
    def rows(self) -> dict[tuple[str, str], dict[str, Any]]:
        return self._rows

    # CRUD ----------------------------------------------------------------

    def get_entity(self, partition_key: str, row_key: str) -> dict[str, Any]:
        return self._rows[(partition_key, row_key)]

    def create_entity(self, entity: dict[str, Any]) -> None:
        self.create_calls.append(dict(entity))
        self._rows[(entity["PartitionKey"], entity["RowKey"])] = dict(entity)

    def upsert_entity(self, entity: dict[str, Any], mode: Any = "merge") -> None:
        self.upsert_calls.append(dict(entity))
        key = (entity["PartitionKey"], entity["RowKey"])
        if str(mode).lower().endswith("replace") or key not in self._rows:
            self._rows[key] = dict(entity)
        else:
            merged = dict(self._rows[key])
            merged.update(entity)
            self._rows[key] = merged

    def update_entity(self, entity: dict[str, Any], mode: Any = "merge") -> None:
        self.update_calls.append(dict(entity))
        key = (entity["PartitionKey"], entity["RowKey"])
        existing = dict(self._rows.get(key, {}))
        if str(mode).lower().endswith("replace"):
            self._rows[key] = dict(entity)
        else:
            existing.update(entity)
            self._rows[key] = existing

    def delete_entity(self, partition_key: str, row_key: str) -> None:
        self.delete_calls.append((partition_key, row_key))
        self._rows.pop((partition_key, row_key), None)

    # Query ---------------------------------------------------------------

    def query_entities(
        self,
        query_filter: str | None = None,
        select: list[str] | None = None,
        results_per_page: int | None = None,
        **_: Any,
    ) -> _ItemPaged:
        out: list[dict[str, Any]] = []
        for ent in self._rows.values():
            if not _eval_filter(query_filter or "", ent):
                continue
            if select:
                projected = {k: ent.get(k) for k in select if k in ent}
                projected.setdefault("PartitionKey", ent.get("PartitionKey"))
                projected.setdefault("RowKey", ent.get("RowKey"))
                out.append(projected)
            else:
                out.append(dict(ent))
        return _ItemPaged(out, page_size=results_per_page or 1000)

    def list_entities(self, **_: Any) -> _ItemPaged:
        return self.query_entities(None)

    # Transaction ---------------------------------------------------------

    def submit_transaction(
        self, operations: Iterable[tuple[Any, dict[str, Any]]]
    ) -> list[Any]:
        ops = [(str(op), dict(ent)) for op, ent in operations]
        self.transactions.append(ops)
        for op_raw, entity in ops:
            op = op_raw.lower()
            if "upsert" in op:
                self.upsert_entity(entity)
            elif "delete" in op:
                self.delete_entity(entity["PartitionKey"], entity["RowKey"])
            elif "create" in op:
                self.create_entity(entity)
            elif "update" in op:
                self.update_entity(entity)
            else:
                raise ValueError(f"Unsupported transaction op: {op_raw!r}")
        return [{"status_code": 204} for _ in ops]


class _TableItem:
    """Stand-in for azure.data.tables.TableItem (only `name` is accessed)."""

    def __init__(self, name: str) -> None:
        self.name = name


class FakeTableServiceClient:
    """In-memory replacement for azure.data.tables.TableServiceClient."""

    def __init__(self) -> None:
        self._tables: dict[str, FakeTableClient] = {}

    def __contains__(self, name: str) -> bool:
        return name in self._tables

    def get_table_client(self, name: str) -> FakeTableClient:
        if name not in self._tables:
            self._tables[name] = FakeTableClient(name)
        return self._tables[name]

    # Alias used by some tests
    table = get_table_client

    def add_table(self, name: str, *entities: dict[str, Any]) -> FakeTableClient:
        client = self.get_table_client(name)
        if entities:
            client.seed(*entities)
        return client

    def query_tables(self, query_filter: str | None = None) -> list[_TableItem]:
        items: list[_TableItem] = []
        for name in self._tables:
            ent = {"TableName": name, "name": name}
            try:
                if _eval_filter(query_filter or "", ent):
                    items.append(_TableItem(name))
            except ValueError:
                continue
        return items

    def delete_table(self, name: str) -> None:
        self._tables.pop(name, None)


# ---------------------------------------------------------------------------
# Fake BlobServiceClient (only the bits CleanUpContainers / Snapshot need)
# ---------------------------------------------------------------------------


class _ContainerItem:
    """Stand-in for azure.storage.blob.ContainerItem (only `name` is read)."""

    def __init__(self, name: str) -> None:
        self.name = name


class FakeBlobServiceClient:
    """In-memory replacement for azure.storage.blob.BlobServiceClient."""

    def __init__(self) -> None:
        self._containers: set[str] = set()
        self.delete_calls: list[str] = []

    def add_container(self, name: str) -> None:
        self._containers.add(name)

    @property
    def containers(self) -> set[str]:
        return set(self._containers)

    def list_containers(self, name_starts_with: str | None = None) -> list[_ContainerItem]:
        prefix = name_starts_with or ""
        return [_ContainerItem(c) for c in sorted(self._containers) if c.startswith(prefix)]

    def delete_container(self, name: str) -> None:
        self.delete_calls.append(name)
        self._containers.discard(name)


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_tables(monkeypatch: pytest.MonkeyPatch) -> FakeTableServiceClient:
    """Patch lat.storage.tables to use an in-memory backend.

    Tests can seed data via:
        fake_tables.add_table("flow<prefix>flows", entity1, entity2, ...)
    """
    svc = FakeTableServiceClient()

    from lat.storage import tables as _tables

    monkeypatch.setattr(_tables, "_service_client", lambda: svc)
    monkeypatch.setattr(
        _tables, "table_client", lambda name: svc.get_table_client(name)
    )
    return svc


@pytest.fixture()
def fake_blobs(monkeypatch: pytest.MonkeyPatch) -> FakeBlobServiceClient:
    """Patch lat.storage.blobs.service_client() to use an in-memory backend."""
    svc = FakeBlobServiceClient()
    from lat.storage import blobs as _blobs

    monkeypatch.setattr(_blobs, "service_client", lambda: svc)
    return svc


@pytest.fixture()
def lat_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set the minimum env vars the shared layer reads."""
    monkeypatch.setenv(
        "AzureWebJobsStorage",
        "DefaultEndpointsProtocol=https;AccountName=teststorage;"
        "AccountKey=Zm9vYmFy;EndpointSuffix=core.windows.net",
    )
    monkeypatch.setenv("WEBSITE_SITE_NAME", "testlogicapp")
    monkeypatch.setenv("WEBSITE_RESOURCE_GROUP", "test-rg")
    monkeypatch.setenv(
        "WEBSITE_OWNER_NAME", "00000000-0000-0000-0000-000000000000+test"
    )
    monkeypatch.setenv("REGION_NAME", "East US")


@pytest.fixture()
def lat_env_aad(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set env vars for AAD storage mode (no connection string, no key)."""
    # Explicitly unset the conn-string form
    monkeypatch.delenv("AzureWebJobsStorage", raising=False)
    monkeypatch.setenv("AzureWebJobsStorage__accountName", "teststorage")
    monkeypatch.setenv("WEBSITE_SITE_NAME", "testlogicapp")
    monkeypatch.setenv("WEBSITE_RESOURCE_GROUP", "test-rg")
    monkeypatch.setenv(
        "WEBSITE_OWNER_NAME", "00000000-0000-0000-0000-000000000000+test"
    )
    monkeypatch.setenv("REGION_NAME", "East US")
