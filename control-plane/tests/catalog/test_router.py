"""Unit tests for the catalog read API's routing/auth/response-shape logic.

Uses hand-written fakes for the three store dependencies (already covered
by their own integration tests under tests/relational, tests/graph,
tests/search) so these tests run with no external services and focus on
what's actually FE2's contract risk here: auth resolution and — the
single most important property per architecture.md §6 — that tenant_id is
always server-resolved and a request can never see another tenant's data
by supplying a URN that happens to exist for someone else.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.catalog.deps import get_graph_store, get_relational_store, get_search_index, hash_api_key
from api.catalog.router import router

TENANT_A = "tenant-a"
RAW_KEY_A = "raw-key-for-tenant-a"


class FakeRelationalStore:
    def __init__(self):
        self._keys: dict[str, str] = {}
        self._tables: dict[tuple, dict] = {}
        self._sources: dict[str, list] = {}

    def register_key(self, raw_key: str, tenant_id: str) -> None:
        self._keys[hash_api_key(raw_key)] = tenant_id

    def resolve_tenant_id_for_api_key_hash(self, key_hash: str):
        return self._keys.get(key_hash)

    def seed_table(self, tenant_id: str, urn: str, table=None, columns=None) -> None:
        self._tables[(tenant_id, urn)] = {"table": table or _default_table(urn), "columns": columns or []}

    def get_table_with_columns(self, tenant_id: str, urn: str):
        return self._tables.get((tenant_id, urn))

    def seed_sources(self, tenant_id: str, sources: list) -> None:
        self._sources[tenant_id] = sources

    def list_sources_status(self, tenant_id: str):
        return self._sources.get(tenant_id, [])


class FakeGraphStore:
    def __init__(self):
        self._lineage: dict[tuple, dict] = {}

    def seed_lineage(self, tenant_id: str, urn: str, upstream=None, downstream=None) -> None:
        self._lineage[(tenant_id, urn)] = {"urn": urn, "upstream": upstream or [], "downstream": downstream or []}

    def get_lineage(self, tenant_id: str, urn: str, direction: str = "both", max_hops: int = 5):
        return self._lineage.get((tenant_id, urn), {"urn": urn, "upstream": [], "downstream": []})


class FakeSearchIndex:
    def __init__(self):
        self._results: dict[tuple, dict] = {}

    def seed_search(self, tenant_id: str, query_text: str, results: list, total=None) -> None:
        self._results[(tenant_id, query_text)] = {"total": total if total is not None else len(results), "results": results}

    def search(self, tenant_id: str, query_text: str = "", entity_types=None, source_types=None, limit=20, offset=0):
        return self._results.get((tenant_id, query_text), {"total": 0, "results": []})


def _default_table(urn: str) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "urn": urn,
        "fully_qualified_name": "postgres://prod-db-1/analytics.public.orders",
        "source_type": "postgres",
        "database_name": "analytics",
        "schema_name": "public",
        "table_name": "orders",
        "object_type": "table",
        "description": None,
        "description_source": None,
        "owner": None,
        "owner_source": None,
        "tags": [],
        "row_count_estimate": None,
        "size_bytes_estimate": None,
        "source_connection_id": "prod-postgres-1",
        "data_plane_id": "dp-1",
        "first_seen_at": now,
        "last_scraped_at": now,
        "is_deleted": False,
    }


@pytest.fixture
def relational():
    return FakeRelationalStore()


@pytest.fixture
def graph():
    return FakeGraphStore()


@pytest.fixture
def search():
    return FakeSearchIndex()


@pytest.fixture
def client(relational, graph, search):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_relational_store] = lambda: relational
    app.dependency_overrides[get_graph_store] = lambda: graph
    app.dependency_overrides[get_search_index] = lambda: search
    return TestClient(app)


def _auth_headers(raw_key: str) -> dict:
    return {"Authorization": f"Bearer {raw_key}"}


def test_search_requires_auth(client):
    resp = client.get("/v1/catalog/search?q=orders")
    assert resp.status_code == 401


def test_search_rejects_unknown_key(client):
    resp = client.get("/v1/catalog/search?q=orders", headers=_auth_headers("not-a-real-key"))
    assert resp.status_code == 401


def test_search_returns_results_for_valid_key(client, relational, search):
    relational.register_key(RAW_KEY_A, TENANT_A)
    search.seed_search(
        TENANT_A, "orders", [{"urn": "urn:postgres:x:a:public.orders", "entity_type": "table", "name": "orders"}]
    )

    resp = client.get("/v1/catalog/search?q=orders", headers=_auth_headers(RAW_KEY_A))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["results"][0]["urn"] == "urn:postgres:x:a:public.orders"


def test_get_table_404_when_not_found(client, relational):
    relational.register_key(RAW_KEY_A, TENANT_A)
    resp = client.get("/v1/catalog/tables/urn:postgres:x:a:public.nope", headers=_auth_headers(RAW_KEY_A))
    assert resp.status_code == 404


def test_get_table_returns_detail(client, relational):
    relational.register_key(RAW_KEY_A, TENANT_A)
    urn = "urn:postgres:x:a:public.orders"
    relational.seed_table(TENANT_A, urn)
    resp = client.get(f"/v1/catalog/tables/{urn}", headers=_auth_headers(RAW_KEY_A))
    assert resp.status_code == 200
    assert resp.json()["table"]["urn"] == urn


def test_get_table_never_leaks_across_tenants(client, relational):
    relational.register_key(RAW_KEY_A, TENANT_A)
    urn = "urn:postgres:x:a:public.orders"
    relational.seed_table("some-other-tenant", urn)

    resp = client.get(f"/v1/catalog/tables/{urn}", headers=_auth_headers(RAW_KEY_A))
    # Exists — but for a different tenant. tenant_id is server-resolved from
    # the API key, never accepted from the client, so this must 404, not 200.
    assert resp.status_code == 404


def test_lineage_404s_if_table_not_in_tenant_catalog(client, relational):
    relational.register_key(RAW_KEY_A, TENANT_A)
    resp = client.get("/v1/catalog/tables/urn:postgres:x:a:public.nope/lineage", headers=_auth_headers(RAW_KEY_A))
    assert resp.status_code == 404


def test_lineage_returns_upstream_and_downstream(client, relational, graph):
    relational.register_key(RAW_KEY_A, TENANT_A)
    urn = "urn:postgres:x:a:public.mart"
    relational.seed_table(TENANT_A, urn)
    graph.seed_lineage(
        TENANT_A, urn, upstream=[{"urn": "urn:postgres:x:a:public.staging", "entity_type": "table", "hops": 1}]
    )

    resp = client.get(f"/v1/catalog/tables/{urn}/lineage", headers=_auth_headers(RAW_KEY_A))
    assert resp.status_code == 200
    body = resp.json()
    assert body["upstream"][0]["urn"] == "urn:postgres:x:a:public.staging"
    assert body["downstream"] == []


def test_lineage_rejects_invalid_direction(client, relational):
    relational.register_key(RAW_KEY_A, TENANT_A)
    urn = "urn:postgres:x:a:public.mart"
    relational.seed_table(TENANT_A, urn)
    resp = client.get(f"/v1/catalog/tables/{urn}/lineage?direction=sideways", headers=_auth_headers(RAW_KEY_A))
    assert resp.status_code == 422


def test_sources_status_is_tenant_scoped(client, relational):
    relational.register_key(RAW_KEY_A, TENANT_A)
    relational.seed_sources(TENANT_A, [{"data_plane_id": "dp-1", "data_plane_name": "prod-dp-1", "source_connections": []}])
    relational.seed_sources("other-tenant", [{"data_plane_id": "dp-2", "data_plane_name": "someone-elses-dp", "source_connections": []}])

    resp = client.get("/v1/catalog/sources/status", headers=_auth_headers(RAW_KEY_A))
    assert resp.status_code == 200
    names = [s["data_plane_name"] for s in resp.json()["sources"]]
    assert names == ["prod-dp-1"]
