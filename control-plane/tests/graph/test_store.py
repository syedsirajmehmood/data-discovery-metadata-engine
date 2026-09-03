"""Integration tests for GraphStore against a real Neo4j (started by
`docker compose -f infra/docker-compose.yml up -d`). Skips if unreachable.
"""

from __future__ import annotations

import uuid

import pytest
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable

from storage.graph.store import GraphStore, build_uri
from storage.types import EntityType, Operation


@pytest.fixture(scope="module")
def driver():
    drv = GraphDatabase.driver(build_uri(), auth=("neo4j", "neo4jpassword"))
    try:
        drv.verify_connectivity()
    except ServiceUnavailable:
        pytest.skip("Neo4j not reachable — run `docker compose -f infra/docker-compose.yml up -d`")
    yield drv
    drv.close()


@pytest.fixture
def store(driver):
    s = GraphStore(driver=driver)
    s.ensure_constraints()
    return s


@pytest.fixture
def tenant_id():
    return str(uuid.uuid4())


def _cleanup_tenant(driver, tenant_id):
    with driver.session() as session:
        session.run("MATCH (n {tenant_id: $tenant_id}) DETACH DELETE n", tenant_id=tenant_id)


def test_upsert_table_creates_node(store, driver, tenant_id, make_entity_record):
    urn = "urn:postgres:prod-db-1:analytics:public.orders"
    record = make_entity_record(tenant_id, urn, EntityType.TABLE, {"table_name": "orders", "owner": "eli"})

    result = store.upsert_entity(record)
    assert result.created is True

    with driver.session() as session:
        rows = list(session.run("MATCH (t:Table {tenant_id: $tenant_id, urn: $urn}) RETURN t.table_name AS name", tenant_id=tenant_id, urn=urn))
    assert rows[0]["name"] == "orders"

    _cleanup_tenant(driver, tenant_id)


def test_upsert_column_creates_has_column_edge(store, driver, tenant_id, make_entity_record):
    table_urn = "urn:postgres:prod-db-1:analytics:public.orders"
    column_urn = f"{table_urn}#id"
    store.upsert_entity(make_entity_record(tenant_id, table_urn, EntityType.TABLE, {"table_name": "orders"}))
    store.upsert_entity(
        make_entity_record(tenant_id, column_urn, EntityType.COLUMN, {"table_urn": table_urn, "name": "id"})
    )

    with driver.session() as session:
        rows = list(
            session.run(
                "MATCH (t:Table {tenant_id: $tenant_id, urn: $table_urn})-[:HAS_COLUMN]->(c:Column {urn: $column_urn}) RETURN c.name AS name",
                tenant_id=tenant_id,
                table_urn=table_urn,
                column_urn=column_urn,
            )
        )
    assert rows[0]["name"] == "id"

    _cleanup_tenant(driver, tenant_id)


def test_upsert_entity_with_owner_creates_owned_by_edge(store, driver, tenant_id, make_entity_record):
    urn = "urn:postgres:prod-db-1:analytics:public.owned_table"
    store.upsert_entity(make_entity_record(tenant_id, urn, EntityType.TABLE, {"table_name": "owned_table", "owner": "eli"}))

    with driver.session() as session:
        rows = list(
            session.run(
                "MATCH (t:Table {tenant_id: $tenant_id, urn: $urn})-[:OWNED_BY]->(o:Owner) RETURN o.name AS owner",
                tenant_id=tenant_id,
                urn=urn,
            )
        )
    assert rows[0]["owner"] == "eli"

    _cleanup_tenant(driver, tenant_id)


def test_upsert_entity_delete_tombstones_node(store, driver, tenant_id, make_entity_record):
    urn = "urn:postgres:prod-db-1:analytics:public.dropped_table"
    store.upsert_entity(make_entity_record(tenant_id, urn, EntityType.TABLE, {"table_name": "dropped_table"}))
    result = store.upsert_entity(make_entity_record(tenant_id, urn, EntityType.TABLE, {}, operation=Operation.DELETE))
    assert result.tombstoned is True

    with driver.session() as session:
        rows = list(session.run("MATCH (t:Table {tenant_id: $tenant_id, urn: $urn}) RETURN t.is_deleted AS d", tenant_id=tenant_id, urn=urn))
    assert rows[0]["d"] is True

    _cleanup_tenant(driver, tenant_id)


def test_lineage_edge_upsert_and_downstream_traversal(store, driver, tenant_id, make_entity_record):
    raw_urn = "urn:postgres:prod-db-1:raw:public.raw_orders"
    staging_urn = "urn:postgres:prod-db-1:staging:public.stg_orders"
    mart_urn = "urn:postgres:prod-db-1:mart:public.orders_mart"

    for urn, name in [(raw_urn, "raw_orders"), (staging_urn, "stg_orders"), (mart_urn, "orders_mart")]:
        store.upsert_entity(make_entity_record(tenant_id, urn, EntityType.TABLE, {"table_name": name}))

    # staging DERIVES_FROM raw, mart DERIVES_FROM staging
    store.upsert_entity(
        make_entity_record(
            tenant_id,
            "urn:lineage:edge-1",
            EntityType.LINEAGE_EDGE,
            {
                "upstream_urn": raw_urn,
                "upstream_entity_type": "table",
                "downstream_urn": staging_urn,
                "downstream_entity_type": "table",
                "confidence": "inferred",
            },
        )
    )
    store.upsert_entity(
        make_entity_record(
            tenant_id,
            "urn:lineage:edge-2",
            EntityType.LINEAGE_EDGE,
            {
                "upstream_urn": staging_urn,
                "upstream_entity_type": "table",
                "downstream_urn": mart_urn,
                "downstream_entity_type": "table",
                "confidence": "inferred",
            },
        )
    )

    lineage = store.get_lineage(tenant_id, raw_urn, direction="downstream", max_hops=5)
    downstream_urns = {n["urn"] for n in lineage["downstream"]}
    assert staging_urn in downstream_urns
    assert mart_urn in downstream_urns  # multi-hop: mart is 2 hops downstream of raw

    upstream_of_mart = store.get_lineage(tenant_id, mart_urn, direction="upstream", max_hops=5)
    upstream_urns = {n["urn"] for n in upstream_of_mart["upstream"]}
    assert staging_urn in upstream_urns
    assert raw_urn in upstream_urns

    _cleanup_tenant(driver, tenant_id)


def test_lineage_tenant_isolation(store, driver, make_entity_record):
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    upstream_urn = "urn:postgres:iso:public.upstream"
    downstream_urn = "urn:postgres:iso:public.downstream"

    for tenant in (tenant_a, tenant_b):
        store.upsert_entity(make_entity_record(tenant, upstream_urn, EntityType.TABLE, {"table_name": "upstream"}))
        store.upsert_entity(make_entity_record(tenant, downstream_urn, EntityType.TABLE, {"table_name": "downstream"}))

    store.upsert_entity(
        make_entity_record(
            tenant_a,
            "urn:lineage:iso-edge",
            EntityType.LINEAGE_EDGE,
            {
                "upstream_urn": upstream_urn,
                "upstream_entity_type": "table",
                "downstream_urn": downstream_urn,
                "downstream_entity_type": "table",
            },
        )
    )

    lineage_a = store.get_lineage(tenant_a, upstream_urn, direction="downstream")
    lineage_b = store.get_lineage(tenant_b, upstream_urn, direction="downstream")
    assert downstream_urn in {n["urn"] for n in lineage_a["downstream"]}
    assert lineage_b["downstream"] == []  # tenant_b never sees tenant_a's edge

    _cleanup_tenant(driver, tenant_a)
    _cleanup_tenant(driver, tenant_b)
