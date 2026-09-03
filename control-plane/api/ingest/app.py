"""FastAPI application factory for the ingest API.

Wires router.py's placeholder dependencies (get_auth_context,
get_ingest_dependencies) to real implementations via FastAPI's
`dependency_overrides`. By default, wires in-memory fakes for everything
(API key registry, idempotency store, and the 4 storage interfaces) so
`create_app()` produces a fully runnable service with zero external
dependencies - useful for local dev, demos, and this task's own tests.

Production wiring (once FE2's real storage clients exist) swaps the
`storage_deps` argument for one backed by real Postgres/Neo4j/OpenSearch/
ClickHouse clients - nothing in router.py or service.py needs to change.

Run locally (see control-plane/README.md for the full command, including
the PYTHONPATH note that `control-plane/` being hyphenated requires):

    uvicorn api.ingest.app:app --app-dir control-plane --reload
"""
from __future__ import annotations

from typing import Optional

from fastapi import FastAPI

from api.ingest.auth import APIKeyRegistry, InMemoryAPIKeyRegistry, make_auth_dependency
from api.ingest.idempotency import IdempotencyStore, InMemoryIdempotencyStore
from api.ingest.router import get_auth_context, get_ingest_dependencies, router
from api.ingest.service import IngestDependencies
from workers.fanout.fakes import (
    InMemoryAnalyticsStore,
    InMemoryGraphStore,
    InMemoryRelationalStore,
    InMemorySearchIndex,
)


def create_app(
    *,
    api_key_registry: Optional[APIKeyRegistry] = None,
    idempotency_store: Optional[IdempotencyStore] = None,
    ingest_deps: Optional[IngestDependencies] = None,
) -> FastAPI:
    app = FastAPI(
        title="Data Discovery Control Plane - Ingest API",
        description="Push contract endpoint: POST /v1/ingest/batches (architecture.md §2).",
        version="1.0.0",
    )
    app.include_router(router)

    registry = api_key_registry or InMemoryAPIKeyRegistry()
    idem_store = idempotency_store or InMemoryIdempotencyStore()
    deps = ingest_deps or IngestDependencies(
        idempotency_store=idem_store,
        relational_store=InMemoryRelationalStore(),
        graph_store=InMemoryGraphStore(),
        search_index=InMemorySearchIndex(),
        analytics_store=InMemoryAnalyticsStore(),
    )

    app.dependency_overrides[get_auth_context] = make_auth_dependency(registry)
    app.dependency_overrides[get_ingest_dependencies] = lambda: deps

    # Exposed for local dev/demo convenience (e.g. registering a demo API
    # key at startup) and for tests that want direct access to the fakes'
    # recorded state without re-deriving them from dependency_overrides.
    app.state.api_key_registry = registry
    app.state.ingest_dependencies = deps

    return app


app = create_app()

if __name__ == "__main__":  # pragma: no cover
    import uuid

    import uvicorn

    demo_key = "demo-key"
    app.state.api_key_registry.register(
        demo_key,
        tenant_id=str(uuid.uuid4()),
        data_plane_id="dp_demo",
        api_key_id="ak_demo",
    )
    print(f"Registered demo API key: {demo_key!r} (Authorization: Bearer {demo_key})")
    uvicorn.run(app, host="0.0.0.0", port=8000)
