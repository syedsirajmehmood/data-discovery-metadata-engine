"""``SearchIndex`` — OpenSearch client for the full-text catalog search
projection.

``index_entity`` is the exact method name FE1's fan-out worker calls
(architecture.md §8) for every accepted entity. Only entity types in
``mapping.SEARCHABLE_ENTITY_TYPES`` (table/column/dataset/dashboard) produce
a document; others are a documented no-op (see ``mapping.py``).
"""

from __future__ import annotations

from typing import Any, Optional

from opensearchpy import OpenSearch
from opensearchpy.exceptions import NotFoundError

from storage.search.client import build_client
from storage.search.mapping import INDEX_BODY, INDEX_NAME, SEARCHABLE_ENTITY_TYPES
from storage.search.query_builder import RelevanceBoostHook, build_search_query
from storage.types import EntityRecord, EntityType, UpsertResult


class SearchIndex:
    def __init__(
        self,
        client: Optional[OpenSearch] = None,
        index_name: str = INDEX_NAME,
        boost_hook: Optional[RelevanceBoostHook] = None,
    ) -> None:
        self._client = client or build_client()
        self._index_name = index_name
        self._boost_hook = boost_hook

    def set_boost_hook(self, hook: Optional[RelevanceBoostHook]) -> None:
        """Registration point for ML's `relevance/` boost profile — additive,
        see query_builder.py. Passing None restores baseline BM25 search."""
        self._boost_hook = hook

    def ensure_index(self) -> None:
        if not self._client.indices.exists(index=self._index_name):
            self._client.indices.create(index=self._index_name, body=INDEX_BODY)

    def refresh(self) -> None:
        """Force the index to be immediately searchable. OpenSearch is
        near-real-time by default (~1s refresh interval) which is fine for
        production (ingestion latency budget is a minute, per spec.md NFR-1)
        but tests need deterministic visibility, hence this helper."""
        self._client.indices.refresh(index=self._index_name)

    # ------------------------------------------------------------------
    # The seam: index_entity
    # ------------------------------------------------------------------

    def index_entity(self, record: EntityRecord) -> UpsertResult:
        entity_type = record.entity_type.value if isinstance(record.entity_type, EntityType) else record.entity_type
        if entity_type not in SEARCHABLE_ENTITY_TYPES:
            return UpsertResult(urn=record.urn, created=False, skipped=True)

        doc_id = _doc_id(record.tenant_id, record.urn)

        if record.is_delete:
            try:
                self._client.update(index=self._index_name, id=doc_id, body={"doc": {"is_deleted": True}})
            except NotFoundError:
                return UpsertResult(urn=record.urn, created=False, skipped=True)
            return UpsertResult(urn=record.urn, created=False, tombstoned=True)

        existed = self._client.exists(index=self._index_name, id=doc_id)
        document = _build_document(entity_type, record)
        self._client.index(index=self._index_name, id=doc_id, body=document, refresh=False)
        return UpsertResult(urn=record.urn, created=not existed)

    # ------------------------------------------------------------------
    # Read path for control-plane/api/catalog/search
    # ------------------------------------------------------------------

    def search(
        self,
        tenant_id: str,
        query_text: str = "",
        entity_types: Optional[list[str]] = None,
        source_types: Optional[list[str]] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Tenant-scoped search. `tenant_id` must come from the
        server-resolved auth context (architecture.md §6), never a
        client-supplied query parameter."""
        body = build_search_query(
            tenant_id=tenant_id,
            query_text=query_text,
            entity_types=entity_types,
            source_types=source_types,
            limit=limit,
            offset=offset,
            boost_hook=self._boost_hook,
        )
        response = self._client.search(index=self._index_name, body=body)
        hits = response.get("hits", {}).get("hits", [])
        total = response.get("hits", {}).get("total", {})
        total_value = total.get("value", len(hits)) if isinstance(total, dict) else total
        results = [{**hit["_source"], "urn": hit["_source"].get("urn", hit["_id"]), "score": hit["_score"]} for hit in hits]
        return {"total": total_value, "results": results}


def _doc_id(tenant_id: str, urn: str) -> str:
    return f"{tenant_id}:{urn}"


def _resolve_name(entity_type: str, payload: dict[str, Any]) -> str:
    if entity_type == "table":
        return payload.get("table_name") or payload.get("fully_qualified_name") or ""
    if entity_type == "dataset":
        return payload.get("prefix") or payload.get("fully_qualified_name") or ""
    # column, dashboard, and any future searchable type: a plain "name" field.
    return payload.get("name") or payload.get("fully_qualified_name") or ""


def _build_document(entity_type: str, record: EntityRecord) -> dict[str, Any]:
    payload = record.payload
    return {
        "tenant_id": record.tenant_id,
        "urn": record.urn,
        "entity_type": entity_type,
        "source_type": payload.get("source_type"),
        "data_plane_id": record.data_plane_id,
        "source_connection_id": record.source_connection_id,
        "name": _resolve_name(entity_type, payload),
        "description": payload.get("description"),
        "tags": payload.get("tags") or [],
        "owner": payload.get("owner"),
        "fully_qualified_name": payload.get("fully_qualified_name"),
        "first_seen_at": payload.get("first_seen_at") or record.extracted_at.isoformat(),
        "last_scraped_at": record.extracted_at.isoformat(),
        "is_deleted": False,
    }
