"""Integration tests for RelationalStore against a real Postgres (started by
`docker compose -f infra/docker-compose.yml up -d`). Skips (not fails) if
Postgres isn't reachable, so `pytest` still runs cleanly without Docker.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from storage.relational.db import make_engine, make_session_factory
from storage.relational.models import Base
from storage.relational.store import RelationalStore
from storage.types import EntityType, Operation


@pytest.fixture(scope="module")
def engine():
    eng = make_engine()
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError:
        pytest.skip("Postgres not reachable at POSTGRES_* settings — run `docker compose -f infra/docker-compose.yml up -d`")
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def store(engine):
    session_factory = make_session_factory(engine)
    return RelationalStore(engine=engine, session_factory=session_factory)


@pytest.fixture
def tenant_id(store):
    # Seed a real Tenant row: api_keys and data_plane_registrations have a
    # genuine FK to tenants.id (unlike the entities_* tables, which only
    # carry tenant_id as a plain scoping column, not a hard FK — see
    # EntityCommonMixin's docstring). Seeding here keeps every test using
    # this fixture valid regardless of which tables it touches.
    from storage.relational.models import Tenant

    new_id = uuid.uuid4()
    with store._session_factory() as session:  # noqa: SLF001
        session.add(Tenant(id=new_id, name=f"test-tenant-{new_id}"))
        session.commit()
    return str(new_id)


def _table_payload(**overrides):
    payload = {
        "database_name": "analytics",
        "schema_name": "public",
        "table_name": "orders",
        "fully_qualified_name": "postgres://prod-db-1/analytics.public.orders",
        "object_type": "table",
        "description": "Customer orders",
        "description_source": "source_comment",
        "owner": "eli",
        "owner_source": "source",
        "tags": ["orders", "core"],
    }
    payload.update(overrides)
    return payload


def test_upsert_entity_creates_table_row(store, tenant_id, make_entity_record):
    urn = f"urn:postgres:prod-db-1:analytics:public.orders:{uuid.uuid4()}"
    record = make_entity_record(tenant_id, urn, EntityType.TABLE, _table_payload(), content_hash="hash-v1")

    result = store.upsert_entity(record)

    assert result.created is True
    assert result.skipped is False

    detail = store.get_table_with_columns(tenant_id, urn)
    assert detail is not None
    assert detail["table"]["table_name"] == "orders"
    assert detail["table"]["owner"] == "eli"
    assert detail["table"]["is_deleted"] is False


def test_upsert_entity_is_idempotent_on_replay(store, tenant_id, make_entity_record):
    urn = f"urn:postgres:prod-db-1:analytics:public.replay:{uuid.uuid4()}"
    record = make_entity_record(tenant_id, urn, EntityType.TABLE, _table_payload(table_name="replay"), content_hash="hash-v1")

    first = store.upsert_entity(record)
    second = store.upsert_entity(record)  # same content_hash -> cheap no-op path

    assert first.created is True
    assert second.created is False
    assert second.skipped is True


def test_upsert_entity_updates_on_content_change(store, tenant_id, make_entity_record):
    urn = f"urn:postgres:prod-db-1:analytics:public.changed:{uuid.uuid4()}"
    v1 = make_entity_record(tenant_id, urn, EntityType.TABLE, _table_payload(table_name="changed", owner="eli"), content_hash="hash-v1")
    store.upsert_entity(v1)

    v2 = make_entity_record(tenant_id, urn, EntityType.TABLE, _table_payload(table_name="changed", owner="dana"), content_hash="hash-v2")
    result = store.upsert_entity(v2)

    assert result.created is False
    assert result.skipped is False
    detail = store.get_table_with_columns(tenant_id, urn)
    assert detail["table"]["owner"] == "dana"


def test_upsert_entity_tombstones_on_delete(store, tenant_id, make_entity_record):
    urn = f"urn:postgres:prod-db-1:analytics:public.dropped:{uuid.uuid4()}"
    store.upsert_entity(make_entity_record(tenant_id, urn, EntityType.TABLE, _table_payload(table_name="dropped")))

    delete_record = make_entity_record(
        tenant_id, urn, EntityType.TABLE, {}, operation=Operation.DELETE
    )
    result = store.upsert_entity(delete_record)

    assert result.tombstoned is True
    detail = store.get_table_with_columns(tenant_id, urn)
    assert detail["table"]["is_deleted"] is True  # tombstoned, not hard-deleted (AC-6)


def test_upsert_entity_delete_of_unknown_urn_is_noop(store, tenant_id, make_entity_record):
    urn = f"urn:postgres:prod-db-1:analytics:public.never_seen:{uuid.uuid4()}"
    result = store.upsert_entity(make_entity_record(tenant_id, urn, EntityType.TABLE, {}, operation=Operation.DELETE))
    assert result.skipped is True
    assert result.created is False


def test_get_table_with_columns_includes_ordered_columns(store, tenant_id, make_entity_record):
    table_urn = f"urn:postgres:prod-db-1:analytics:public.widgets:{uuid.uuid4()}"
    store.upsert_entity(make_entity_record(tenant_id, table_urn, EntityType.TABLE, _table_payload(table_name="widgets")))

    for i, col_name in enumerate(["id", "name", "created_at"]):
        col_urn = f"{table_urn}#{col_name}"
        store.upsert_entity(
            make_entity_record(
                tenant_id,
                col_urn,
                EntityType.COLUMN,
                {
                    "table_urn": table_urn,
                    "name": col_name,
                    "ordinal_position": i,
                    "native_data_type": "text",
                    "normalized_data_type": "string",
                    "is_nullable": True,
                    "is_primary_key": col_name == "id",
                    "is_foreign_key": False,
                    "tags": [],
                },
            )
        )

    detail = store.get_table_with_columns(tenant_id, table_urn)
    assert [c["name"] for c in detail["columns"]] == ["id", "name", "created_at"]
    assert detail["columns"][0]["is_primary_key"] is True


def test_tenant_isolation_get_table_with_columns(store, make_entity_record):
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    urn = f"urn:postgres:prod-db-1:analytics:public.shared_urn:{uuid.uuid4()}"
    store.upsert_entity(make_entity_record(tenant_a, urn, EntityType.TABLE, _table_payload()))

    assert store.get_table_with_columns(tenant_a, urn) is not None
    assert store.get_table_with_columns(tenant_b, urn) is None  # never leaks across tenants


def test_record_connector_run_and_list_sources_status(store, tenant_id):
    data_plane_id = str(uuid.uuid4())
    with store._session_factory() as session:  # noqa: SLF001 - test needs to seed a registration row
        from storage.relational.models import DataPlaneRegistration

        session.add(
            DataPlaneRegistration(id=data_plane_id, tenant_id=uuid.UUID(tenant_id), name="prod-dp-1")
        )
        session.commit()

    store.record_connector_run(
        tenant_id=tenant_id,
        data_plane_id=data_plane_id,
        source_connection_id="prod-postgres-1",
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        status="success",
        entities_seen_count=10,
        entities_created_count=2,
        entities_tombstoned_count=0,
    )

    sources = store.list_sources_status(tenant_id)
    assert len(sources) == 1
    assert sources[0]["data_plane_name"] == "prod-dp-1"
    assert sources[0]["source_connections"][0]["source_connection_id"] == "prod-postgres-1"
    assert sources[0]["source_connections"][0]["last_run_status"] == "success"


def test_resolve_tenant_id_for_api_key_hash(store, tenant_id):
    from storage.relational.models import ApiKey

    key_hash = "deadbeef" * 8
    with store._session_factory() as session:  # noqa: SLF001
        session.add(ApiKey(tenant_id=uuid.UUID(tenant_id), key_hash=key_hash, label="test-key"))
        session.commit()

    resolved = store.resolve_tenant_id_for_api_key_hash(key_hash)
    assert resolved == tenant_id
    assert store.resolve_tenant_id_for_api_key_hash("nonexistent" * 8) is None
