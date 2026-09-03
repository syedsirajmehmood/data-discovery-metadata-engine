"""Integration tests against a real Postgres, seeded by
deploy/postgres-init/01_seed.sql (schema `analytics`: users, orders,
recent_orders view, users<-orders FK). Run via docker-compose -- see
README.
"""
import pytest

from connectors.core.types import EntityType, Operation
from connectors.postgres.connector import PostgresConnector

pytestmark = pytest.mark.integration


def _discover_and_extract(connector):
    normalized = []
    for raw in connector.discover():
        normalized.append(connector.extract_metadata(raw))
    return normalized


def test_discovers_seeded_tables_and_view(pg_config):
    connector = PostgresConnector()
    connector.connect(pg_config)
    try:
        entities = _discover_and_extract(connector)
    finally:
        connector._conn.close()

    tables = {e.payload["table_name"]: e for e in entities if e.entity_type == EntityType.TABLE.value}
    assert "users" in tables
    assert "orders" in tables
    assert "recent_orders" in tables
    assert tables["users"].payload["object_type"] == "table"
    assert tables["recent_orders"].payload["object_type"] == "view"


def test_extracted_table_fields_match_seed(pg_config):
    connector = PostgresConnector()
    connector.connect(pg_config)
    try:
        entities = _discover_and_extract(connector)
    finally:
        connector._conn.close()

    tables = {e.payload["table_name"]: e for e in entities if e.entity_type == EntityType.TABLE.value}
    users = tables["users"]
    assert users.payload["description"] == "Registered users"
    assert users.payload["description_source"] == "source_comment"
    assert users.payload["schema_name"] == "analytics"
    assert users.payload["database_name"] == "demo"
    assert users.payload["fully_qualified_name"].endswith("demo.analytics.users")
    assert users.urn == f"urn:postgres:{pg_config['host']}:demo:analytics.users"
    assert users.payload["row_count_estimate"] is not None  # ANALYZE was run in seed script


def test_columns_include_pk_fk_and_comments(pg_config):
    connector = PostgresConnector()
    connector.connect(pg_config)
    try:
        entities = _discover_and_extract(connector)
    finally:
        connector._conn.close()

    columns = [e for e in entities if e.entity_type == EntityType.COLUMN.value]
    users_id = next(c for c in columns if c.payload["table_urn"].endswith("analytics.users") and c.payload["name"] == "id")
    assert users_id.payload["is_primary_key"] is True
    assert users_id.payload["normalized_data_type"] == "integer"

    users_email = next(c for c in columns if c.payload["table_urn"].endswith("analytics.users") and c.payload["name"] == "email")
    assert users_email.payload["description"] == "Unique login email"

    orders_user_id = next(
        c for c in columns if c.payload["table_urn"].endswith("analytics.orders") and c.payload["name"] == "user_id"
    )
    assert orders_user_id.payload["is_foreign_key"] is True
    assert orders_user_id.payload["foreign_key_ref"]["column"] == "id"
    assert orders_user_id.payload["foreign_key_ref"]["table_urn"].endswith("analytics.users")


def test_extract_lineage_is_empty_for_mvp(pg_config):
    connector = PostgresConnector()
    connector.connect(pg_config)
    try:
        edges = list(connector.extract_lineage())
    finally:
        connector._conn.close()
    assert edges == []


def test_schema_drift_new_table_appears_and_dropped_table_becomes_delete(pg_config):
    import psycopg2

    admin_conn = psycopg2.connect(
        host=pg_config["host"], port=pg_config["port"], dbname=pg_config["database"],
        user=pg_config["user"], password=pg_config["password"],
    )
    admin_conn.autocommit = True

    connector = PostgresConnector()
    connector.connect(pg_config)
    try:
        # Set up a throwaway view (NOT the shared seed fixtures used by
        # other tests in this module) so this test's mutation/cleanup is
        # fully self-contained and re-runnable.
        with admin_conn.cursor() as cur:
            cur.execute("DROP VIEW IF EXISTS analytics.drift_view_test")
            cur.execute("DROP TABLE IF EXISTS analytics.drift_test")
            cur.execute("CREATE VIEW analytics.drift_view_test AS SELECT 1 AS one")

        # Cycle 1: baseline discovery, persist cursor in-process.
        list(map(connector.extract_metadata, connector.discover()))
        cursor_after_cycle1 = connector.get_cursor()

        # Mutate the source out-of-band: add a new table, drop the throwaway view.
        with admin_conn.cursor() as cur:
            cur.execute("CREATE TABLE analytics.drift_test (id INT PRIMARY KEY)")
            cur.execute("DROP VIEW analytics.drift_view_test")

        # Cycle 2: reuse the same cursor state (simulating the agent
        # reloading the persisted cursor for this source connection).
        connector.set_cursor(cursor_after_cycle1)
        raws = list(connector.discover())
        normalized = [connector.extract_metadata(r) for r in raws]

        new_table = next(n for n in normalized if n.payload.get("table_name") == "drift_test")
        assert new_table.operation == Operation.UPSERT.value

        deleted = [n for n in normalized if n.operation == Operation.DELETE.value]
        assert any(n.urn.endswith("analytics.drift_view_test") for n in deleted)
    finally:
        # cleanup regardless of assertion outcome -- leaves the shared seed
        # schema (users/orders/recent_orders) untouched for other tests.
        with admin_conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS analytics.drift_test")
            cur.execute("DROP VIEW IF EXISTS analytics.drift_view_test")
        admin_conn.close()
        connector._conn.close()
