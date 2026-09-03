"""Run the ingest API locally against the REAL Postgres/Neo4j/OpenSearch/
ClickHouse stores (not FE1's in-memory fakes). Run bootstrap_local.py first.
See RUNBOOK.md for the full local-run walkthrough.

    PYTHONPATH="$(pwd)" .venv/bin/python scripts/run_ingest_local.py
"""
from __future__ import annotations

import uvicorn

from api.ingest.app import create_app
from api.ingest.auth import InMemoryAPIKeyRegistry
from api.ingest.idempotency import InMemoryIdempotencyStore
from api.ingest.service import IngestDependencies
from scripts.local_constants import LOCAL_API_KEY, LOCAL_DATA_PLANE_ID, LOCAL_TENANT_ID
from storage.analytics.store import AnalyticsStore
from storage.graph.store import GraphStore
from storage.relational.store import RelationalStore
from storage.search.store import SearchIndex

PORT = 8090


def main() -> None:
    registry = InMemoryAPIKeyRegistry()
    registry.register(
        LOCAL_API_KEY,
        tenant_id=str(LOCAL_TENANT_ID),
        data_plane_id=LOCAL_DATA_PLANE_ID,
        api_key_id="ak-local-1",
    )

    deps = IngestDependencies(
        idempotency_store=InMemoryIdempotencyStore(),
        relational_store=RelationalStore(),
        graph_store=GraphStore(),
        search_index=SearchIndex(),
        analytics_store=AnalyticsStore(),
    )

    app = create_app(api_key_registry=registry, ingest_deps=deps)

    print(f"Ingest API on http://0.0.0.0:{PORT}")
    print(f"  data_plane_id = {LOCAL_DATA_PLANE_ID!r}")
    print(f"  api_key       = {LOCAL_API_KEY!r}  (Authorization: Bearer {LOCAL_API_KEY})")
    uvicorn.run(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
