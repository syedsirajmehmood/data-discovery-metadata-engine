"""Unit tests for PostgresConnector's extraction/transform logic and its
cursor-driven schema-drift-as-delete handling. `discover()` is tested here
by monkeypatching the `introspection` module (so no real DB is needed) --
`tests/integration/test_postgres_integration.py` covers the real-Postgres
path via docker-compose.
"""
from connectors.core.types import Cursor, EntityType, Operation, RawEntity
from connectors.postgres import introspection
from connectors.postgres.connector import PostgresConfig, PostgresConnector


def make_connector(**overrides):
    connector = PostgresConnector()
    config = PostgresConfig(
        source_connection_id="pg-1",
        host="host1",
        database="mydb",
        user="u",
        password="p",
        **overrides,
    )
    connector._config = config
    connector._conn = object()  # unused when discover()'s introspection calls are monkeypatched
    connector._cursor_state = Cursor.empty(config.source_connection_id)
    return connector


# -- extract_metadata: table -------------------------------------------------


def test_extract_metadata_table_populates_spec_fields():
    connector = make_connector()
    raw = RawEntity(
        entity_type=EntityType.TABLE.value,
        key="public.orders",
        raw={
            "schema": "public",
            "table": {
                "table_name": "orders",
                "object_type": "table",
                "row_count_estimate": 1000,
                "size_bytes_estimate": 65536,
                "description": "order records",
                "db_owner_role": "app_user",
                "table_oid": 1,
            },
            "column_count": 1,
        },
    )
    normalized = connector.extract_metadata(raw)

    assert normalized.urn == "urn:postgres:host1:mydb:public.orders"
    assert normalized.entity_type == "table"
    assert normalized.operation == "upsert"
    p = normalized.payload
    assert p["database_name"] == "mydb"
    assert p["schema_name"] == "public"
    assert p["table_name"] == "orders"
    assert p["fully_qualified_name"] == "postgres://host1/mydb.public.orders"
    assert p["object_type"] == "table"
    assert p["description"] == "order records"
    assert p["description_source"] == "source_comment"
    assert p["owner"] == "app_user"
    assert p["owner_source"] == "source"
    assert p["row_count_estimate"] == 1000
    assert p["size_bytes_estimate"] == 65536


def test_extract_metadata_table_no_comment_has_null_description_source():
    connector = make_connector()
    raw = RawEntity(
        entity_type=EntityType.TABLE.value,
        key="public.t",
        raw={
            "schema": "public",
            "table": {
                "table_name": "t", "object_type": "view", "row_count_estimate": None,
                "size_bytes_estimate": None, "description": None, "db_owner_role": None,
                "table_oid": 2,
            },
            "column_count": 0,
        },
    )
    normalized = connector.extract_metadata(raw)
    assert normalized.payload["description"] is None
    assert normalized.payload["description_source"] is None
    assert normalized.payload["owner"] is None
    assert normalized.payload["owner_source"] is None
    assert normalized.payload["object_type"] == "view"


def test_extract_metadata_uses_host_alias_in_urn_but_real_host_in_fqn():
    connector = make_connector(host_alias="prod-db-1")
    raw = RawEntity(
        entity_type=EntityType.TABLE.value,
        key="public.t",
        raw={
            "schema": "public",
            "table": {
                "table_name": "t", "object_type": "table", "row_count_estimate": 0,
                "size_bytes_estimate": 0, "description": None, "db_owner_role": None,
                "table_oid": 3,
            },
            "column_count": 0,
        },
    )
    normalized = connector.extract_metadata(raw)
    assert normalized.urn == "urn:postgres:prod-db-1:mydb:public.t"
    assert normalized.payload["fully_qualified_name"] == "postgres://host1/mydb.public.t"


# -- extract_metadata: column ------------------------------------------------


def test_extract_metadata_column_basic():
    connector = make_connector()
    raw = RawEntity(
        entity_type=EntityType.COLUMN.value,
        key="public.orders.id",
        raw={
            "schema": "public",
            "table_name": "orders",
            "table_urn": "urn:postgres:host1:mydb:public.orders",
            "column": {
                "column_name": "id", "ordinal_position": 1, "native_data_type": "integer",
                "is_nullable": False, "description": None,
            },
            "is_primary_key": True,
            "foreign_key_ref": None,
        },
    )
    normalized = connector.extract_metadata(raw)
    assert normalized.urn == "urn:postgres:host1:mydb:public.orders.id"
    p = normalized.payload
    assert p["table_urn"] == "urn:postgres:host1:mydb:public.orders"
    assert p["name"] == "id"
    assert p["ordinal_position"] == 1
    assert p["native_data_type"] == "integer"
    assert p["normalized_data_type"] == "integer"
    assert p["is_nullable"] is False
    assert p["is_primary_key"] is True
    assert p["is_foreign_key"] is False
    assert p["foreign_key_ref"] is None


def test_extract_metadata_column_with_foreign_key():
    connector = make_connector()
    raw = RawEntity(
        entity_type=EntityType.COLUMN.value,
        key="public.orders.user_id",
        raw={
            "schema": "public",
            "table_name": "orders",
            "table_urn": "urn:postgres:host1:mydb:public.orders",
            "column": {
                "column_name": "user_id", "ordinal_position": 2, "native_data_type": "integer",
                "is_nullable": True, "description": "fk to users",
            },
            "is_primary_key": False,
            "foreign_key_ref": {"schema": "public", "table": "users", "column": "id"},
        },
    )
    normalized = connector.extract_metadata(raw)
    p = normalized.payload
    assert p["is_foreign_key"] is True
    assert p["foreign_key_ref"] == {"table_urn": "urn:postgres:host1:mydb:public.users", "column": "id"}
    assert p["description"] == "fk to users"
    assert p["description_source"] == "source_comment"


# -- tombstones (schema drift -> delete) -------------------------------------


def test_extract_metadata_tombstone_produces_delete_operation():
    connector = make_connector()
    raw = RawEntity(
        entity_type=EntityType.TABLE.value,
        key="urn:postgres:host1:mydb:public.dropped_table",
        raw={},
        tombstone=True,
    )
    normalized = connector.extract_metadata(raw)
    assert normalized.operation == Operation.DELETE.value
    assert normalized.urn == "urn:postgres:host1:mydb:public.dropped_table"
    assert normalized.payload["source_connection_id"] == "pg-1"


def test_extract_metadata_updates_cursor_state():
    connector = make_connector()
    raw = RawEntity(
        entity_type=EntityType.TABLE.value,
        key="public.t",
        raw={
            "schema": "public",
            "table": {
                "table_name": "t", "object_type": "table", "row_count_estimate": 0,
                "size_bytes_estimate": 0, "description": None, "db_owner_role": None,
                "table_oid": 1,
            },
            "column_count": 0,
        },
    )
    normalized = connector.extract_metadata(raw)
    cursor = connector.get_cursor()
    assert normalized.urn in cursor.entries
    assert cursor.entries[normalized.urn].content_hash == normalized.content_hash


def test_extract_metadata_delete_forgets_cursor_entry():
    connector = make_connector()
    connector.get_cursor().record("urn:postgres:host1:mydb:public.gone", "table", "sha256:aaa")
    raw = RawEntity(
        entity_type=EntityType.TABLE.value,
        key="urn:postgres:host1:mydb:public.gone",
        raw={},
        tombstone=True,
    )
    connector.extract_metadata(raw)
    assert "urn:postgres:host1:mydb:public.gone" not in connector.get_cursor().entries


# -- discover(): full orchestration with introspection monkeypatched --------


class _CursorCM:
    def __enter__(self):
        return object()

    def __exit__(self, *exc):
        return False


class _FakeConn:
    def cursor(self):
        return _CursorCM()


def test_discover_yields_tables_columns_and_drift_deletes(monkeypatch):
    connector = make_connector()
    connector._conn = _FakeConn()

    # Pre-seed cursor with entities that will NOT be re-discovered this
    # cycle, to exercise schema-drift-as-delete.
    cursor = connector.get_cursor()
    cursor.record("urn:postgres:host1:mydb:public.old_table", "table", "sha256:x")
    cursor.record("urn:postgres:host1:mydb:public.orders.old_col", "column", "sha256:y")

    monkeypatch.setattr(introspection, "list_schemas", lambda cur, include=None, exclude=(): ["public"])
    monkeypatch.setattr(
        introspection,
        "list_tables",
        lambda cur, schema: [
            {
                "schema_name": "public", "table_name": "orders", "object_type": "table",
                "row_count_estimate": 10, "size_bytes_estimate": 100, "description": None,
                "db_owner_role": None, "table_oid": 1,
            }
        ],
    )
    monkeypatch.setattr(
        introspection, "list_primary_and_foreign_keys", lambda cur, table_oid: ({"id"}, {})
    )
    monkeypatch.setattr(
        introspection,
        "list_columns",
        lambda cur, table_oid: [
            {"column_name": "id", "ordinal_position": 1, "native_data_type": "integer",
             "is_nullable": False, "description": None}
        ],
    )

    raws = list(connector.discover())
    by_key = {(r.entity_type, r.key, r.tombstone) for r in raws}

    assert (EntityType.TABLE.value, "public.orders", False) in by_key
    assert (EntityType.COLUMN.value, "public.orders.id", False) in by_key
    # drift deletes: full urns as key, tombstone=True
    assert (EntityType.TABLE.value, "urn:postgres:host1:mydb:public.old_table", True) in by_key
    assert (EntityType.COLUMN.value, "urn:postgres:host1:mydb:public.orders.old_col", True) in by_key
    assert len(raws) == 4


def test_full_cycle_table_dropped_becomes_delete_not_error(monkeypatch):
    """End-to-end (discover -> extract_metadata) drift check: a table
    present in a prior cursor but absent from this cycle's discovery must
    surface as an operation="delete" NormalizedEntity, never raise."""
    connector = make_connector()
    connector._conn = _FakeConn()
    connector.get_cursor().record("urn:postgres:host1:mydb:public.dropped", "table", "sha256:z")

    monkeypatch.setattr(introspection, "list_schemas", lambda cur, include=None, exclude=(): [])

    raws = list(connector.discover())
    assert len(raws) == 1
    normalized = connector.extract_metadata(raws[0])
    assert normalized.operation == Operation.DELETE.value
    assert normalized.urn == "urn:postgres:host1:mydb:public.dropped"


def test_get_set_cursor_roundtrip():
    connector = make_connector()
    cursor = Cursor.empty("pg-1")
    cursor.record("urn:a", "table", "sha256:aaa")
    connector.set_cursor(cursor)
    assert connector.get_cursor() is cursor
