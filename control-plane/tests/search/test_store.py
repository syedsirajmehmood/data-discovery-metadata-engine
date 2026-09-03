"""Integration tests for SearchIndex against a real OpenSearch (started by
`docker compose -f infra/docker-compose.yml up -d`). Skips if unreachable.
"""

from __future__ import annotations

import uuid

import pytest
from opensearchpy import OpenSearch
from opensearchpy.exceptions import ConnectionError as OSConnectionError

from storage.search.client import build_client
from storage.search.store import SearchIndex
from storage.types import EntityType, Operation


@pytest.fixture(scope="module")
def client():
    c = build_client()
    try:
        c.info()
    except OSConnectionError:
        pytest.skip("OpenSearch not reachable — run `docker compose -f infra/docker-compose.yml up -d`")
    return c


@pytest.fixture
def index_name():
    return f"catalog_entities_test_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def store(client, index_name):
    s = SearchIndex(client=client, index_name=index_name)
    s.ensure_index()
    yield s
    client.indices.delete(index=index_name, ignore=[404])


@pytest.fixture
def tenant_id():
    return str(uuid.uuid4())


def test_index_entity_then_search_by_name(store, tenant_id, make_entity_record):
    record = make_entity_record(
        tenant_id,
        "urn:postgres:prod-db-1:analytics:public.orders",
        EntityType.TABLE,
        {"table_name": "orders", "description": "Customer orders", "owner": "eli", "tags": ["core"]},
    )
    result = store.index_entity(record)
    assert result.created is True
    store.refresh()

    hits = store.search(tenant_id, "orders")
    assert hits["total"] >= 1
    assert any(h["urn"] == record.urn for h in hits["results"])


def test_search_is_tenant_scoped(store, make_entity_record):
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    store.index_entity(
        make_entity_record(tenant_a, "urn:postgres:x:a:public.foo", EntityType.TABLE, {"table_name": "foo_bar_unique"})
    )
    store.refresh()

    hits_a = store.search(tenant_a, "foo_bar_unique")
    hits_b = store.search(tenant_b, "foo_bar_unique")
    assert hits_a["total"] >= 1
    assert hits_b["total"] == 0  # never leaks across tenants


def test_index_entity_skips_non_searchable_entity_types(store, tenant_id, make_entity_record):
    record = make_entity_record(
        tenant_id, "urn:job:some-dag", EntityType.JOB, {"name": "some-dag", "job_type": "airflow_dag"}
    )
    result = store.index_entity(record)
    assert result.skipped is True


def test_index_entity_delete_tombstones_and_excludes_from_search(store, tenant_id, make_entity_record):
    urn = "urn:postgres:prod-db-1:analytics:public.to_drop"
    store.index_entity(make_entity_record(tenant_id, urn, EntityType.TABLE, {"table_name": "to_drop_unique_xyz"}))
    store.refresh()
    assert store.search(tenant_id, "to_drop_unique_xyz")["total"] >= 1

    store.index_entity(make_entity_record(tenant_id, urn, EntityType.TABLE, {}, operation=Operation.DELETE))
    store.refresh()

    assert store.search(tenant_id, "to_drop_unique_xyz")["total"] == 0  # tombstoned rows excluded from search


def test_search_filters_by_entity_type(store, tenant_id, make_entity_record):
    store.index_entity(
        make_entity_record(tenant_id, "urn:postgres:x:a:public.mixedkeyword", EntityType.TABLE, {"table_name": "mixedkeyword"})
    )
    store.index_entity(
        make_entity_record(tenant_id, "urn:s3:bucket/mixedkeyword", EntityType.DATASET, {"prefix": "mixedkeyword"})
    )
    store.refresh()

    table_only = store.search(tenant_id, "mixedkeyword", entity_types=["table"])
    assert all(r["entity_type"] == "table" for r in table_only["results"])
    assert table_only["total"] == 1

    both = store.search(tenant_id, "mixedkeyword")
    assert both["total"] == 2  # cross-source parity: table + dataset in one ranked list (AC-8)
