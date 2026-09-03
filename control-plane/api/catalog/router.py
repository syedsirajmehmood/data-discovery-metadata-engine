"""The catalog read API — exactly the four endpoints architecture.md §8
assigns to FE2:

    GET /v1/catalog/search
    GET /v1/catalog/tables/{urn}
    GET /v1/catalog/tables/{urn}/lineage
    GET /v1/catalog/sources/status

This is the contract FE3's UI builds against (``control-plane/web/``) —
FE3 consumes this API only, no direct storage access from the UI layer.

Every handler takes `tenant_id` from ``Depends(get_tenant_id)`` (resolved
server-side from the caller's API key, ``deps.py``) and nothing else —
per architecture.md §6, tenant_id is never accepted as a path or query
parameter.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.catalog.deps import get_graph_store, get_relational_store, get_search_index, get_tenant_id
from api.catalog.schemas import (
    LineageResponse,
    SearchResponse,
    SourcesStatusResponse,
    TableDetailResponse,
)
from storage.graph.store import GraphStore
from storage.relational.store import RelationalStore
from storage.search.store import SearchIndex

router = APIRouter(prefix="/v1/catalog", tags=["catalog"])


@router.get("/search", response_model=SearchResponse)
def search_catalog(
    q: str = Query(default="", description="Free-text search query; empty returns all (tenant-scoped, non-deleted) entities"),
    entity_type: Optional[List[str]] = Query(default=None, description="Filter to one or more of: table, column, dataset, dashboard"),
    source_type: Optional[List[str]] = Query(default=None, description="Filter to one or more of: postgres, s3"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    tenant_id: str = Depends(get_tenant_id),
    search_index: SearchIndex = Depends(get_search_index),
) -> SearchResponse:
    raw = search_index.search(
        tenant_id=tenant_id,
        query_text=q,
        entity_types=entity_type,
        source_types=source_type,
        limit=limit,
        offset=offset,
    )
    return SearchResponse(total=raw["total"], results=raw["results"])


# NOTE ON ROUTE ORDER: `{urn:path}` is a greedy converter (it matches "/"
# too), so `/tables/{urn:path}` would otherwise swallow the "/lineage"
# suffix and shadow the route below entirely. Starlette matches routes in
# registration order and stops at the first match, so the more specific
# `/tables/{urn:path}/lineage` route MUST be registered before the plain
# `/tables/{urn:path}` route. Do not reorder these two without re-running
# tests/catalog/test_router.py's lineage tests.


@router.get("/tables/{urn:path}/lineage", response_model=LineageResponse)
def get_table_lineage(
    urn: str,
    direction: str = Query(default="both", pattern="^(upstream|downstream|both)$"),
    max_hops: int = Query(default=5, ge=1, le=10),
    tenant_id: str = Depends(get_tenant_id),
    relational_store: RelationalStore = Depends(get_relational_store),
    graph_store: GraphStore = Depends(get_graph_store),
) -> LineageResponse:
    # 404 if the anchor table isn't even in the tenant's catalog, rather than
    # silently returning empty upstream/downstream lists either way.
    if relational_store.get_table_with_columns(tenant_id=tenant_id, urn=urn) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No table with urn={urn!r} for this tenant")
    result = graph_store.get_lineage(tenant_id=tenant_id, urn=urn, direction=direction, max_hops=max_hops)
    return LineageResponse(**result)


@router.get("/tables/{urn:path}", response_model=TableDetailResponse)
def get_table(
    urn: str,
    tenant_id: str = Depends(get_tenant_id),
    relational_store: RelationalStore = Depends(get_relational_store),
) -> TableDetailResponse:
    result = relational_store.get_table_with_columns(tenant_id=tenant_id, urn=urn)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No table with urn={urn!r} for this tenant")
    return TableDetailResponse(table=result["table"], columns=result["columns"])


@router.get("/sources/status", response_model=SourcesStatusResponse)
def get_sources_status(
    tenant_id: str = Depends(get_tenant_id),
    relational_store: RelationalStore = Depends(get_relational_store),
) -> SourcesStatusResponse:
    sources = relational_store.list_sources_status(tenant_id=tenant_id)
    return SourcesStatusResponse(sources=sources)
