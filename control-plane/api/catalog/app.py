"""Standalone FastAPI app exposing the catalog read API — useful for local
dev/testing FE2's slice in isolation. In a full deployment this router is
expected to be mounted into the control plane's main FastAPI app alongside
FE1's ``api/ingest`` router; either way, the router itself
(``router.py``) has no dependency on how it's mounted.

Run locally (after `docker compose -f infra/docker-compose.yml up -d` and
`python -m storage.relational.migrate`):

    uvicorn api.catalog.app:app --reload --port 8001

See ``control-plane/README.md`` for full local setup.
"""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI

from api.catalog.deps import get_graph_store, get_relational_store, get_search_index
from api.catalog.router import router
from storage.graph.store import GraphStore
from storage.relational.store import RelationalStore
from storage.search.store import SearchIndex

app = FastAPI(title="Catalog Read API", version="1.0")
app.include_router(router)

_relational_store: Optional[RelationalStore] = None
_graph_store: Optional[GraphStore] = None
_search_index: Optional[SearchIndex] = None


@app.on_event("startup")
def _wire_stores() -> None:
    global _relational_store, _graph_store, _search_index
    _relational_store = RelationalStore()
    _graph_store = GraphStore()
    _search_index = SearchIndex()

    app.dependency_overrides[get_relational_store] = lambda: _relational_store
    app.dependency_overrides[get_graph_store] = lambda: _graph_store
    app.dependency_overrides[get_search_index] = lambda: _search_index


@app.on_event("shutdown")
def _close_stores() -> None:
    if _graph_store is not None:
        _graph_store.close()


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
