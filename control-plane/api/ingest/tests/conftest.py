from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from api.ingest.app import create_app
from api.ingest.auth import InMemoryAPIKeyRegistry
from api.ingest.idempotency import InMemoryIdempotencyStore
from api.ingest.service import IngestDependencies
from workers.fanout.fakes import (
    InMemoryAnalyticsStore,
    InMemoryGraphStore,
    InMemoryRelationalStore,
    InMemorySearchIndex,
)

TENANT_ID = "22222222-2222-2222-2222-222222222222"
DATA_PLANE_ID = "dp_test_1"
API_KEY = "test-api-key"
OTHER_DATA_PLANE_ID = "dp_test_other"
OTHER_TENANT_ID = "33333333-3333-3333-3333-333333333333"
OTHER_API_KEY = "other-tenant-key"


@pytest.fixture
def stores():
    return {
        "relational": InMemoryRelationalStore(),
        "graph": InMemoryGraphStore(),
        "search": InMemorySearchIndex(),
        "analytics": InMemoryAnalyticsStore(),
    }


@pytest.fixture
def ingest_deps(stores):
    return IngestDependencies(
        idempotency_store=InMemoryIdempotencyStore(),
        relational_store=stores["relational"],
        graph_store=stores["graph"],
        search_index=stores["search"],
        analytics_store=stores["analytics"],
    )


@pytest.fixture
def api_key_registry():
    registry = InMemoryAPIKeyRegistry()
    registry.register(API_KEY, tenant_id=TENANT_ID, data_plane_id=DATA_PLANE_ID, api_key_id="ak_1")
    registry.register(
        OTHER_API_KEY, tenant_id=OTHER_TENANT_ID, data_plane_id=OTHER_DATA_PLANE_ID, api_key_id="ak_2"
    )
    return registry


@pytest.fixture
def client(api_key_registry, ingest_deps):
    app = create_app(api_key_registry=api_key_registry, ingest_deps=ingest_deps)
    return TestClient(app)


def auth_headers(api_key: str = API_KEY) -> dict:
    return {"Authorization": f"Bearer {api_key}"}


def make_table_entity(urn: str = "urn:postgres:h:analytics:public.orders", **overrides) -> dict:
    payload = {
        "source_connection_id": "prod-postgres-1",
        "source_type": "postgres",
        "database_name": "analytics",
        "schema_name": "public",
        "table_name": "orders",
        "fully_qualified_name": "postgres://h/analytics.public.orders",
        "object_type": "table",
    }
    payload.update(overrides.pop("payload_overrides", {}))
    item = {
        "urn": urn,
        "entity_type": "table",
        "operation": "upsert",
        "content_hash": "sha256:abc123",
        "extracted_at": "2026-09-02T10:14:50Z",
        "payload": payload,
    }
    item.update(overrides)
    return item


def make_envelope(entities=None, **overrides) -> dict:
    envelope = {
        "batch_id": str(uuid.uuid4()),
        "data_plane_id": DATA_PLANE_ID,
        "connector_type": "postgres",
        "schema_version": "1.0",
        "sent_at": "2026-09-02T10:15:00Z",
        "entities": entities if entities is not None else [make_table_entity()],
    }
    envelope.update(overrides)
    return envelope
