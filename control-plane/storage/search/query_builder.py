"""Base search query builder + the ML engineer's extension hook.

Per architecture.md §8: FE2 "leaves a call-out hook in the search query
builder for ML's `relevance/` boost profile (additive — baseline keyword
search must work with no boost profile present)."

**How to plug in** (for whoever implements
``control-plane/storage/search/relevance/``, ML engineer's directory —
untouched by FE2):

1. Implement a class satisfying ``RelevanceBoostHook`` below (structurally —
   no import of this module is required, just the ``apply`` method shape).
2. Construct ``SearchIndex(boost_hook=YourHook())`` (or call
   ``search_index.set_boost_hook(YourHook())`` after construction).
3. ``build_search_query`` calls ``hook.apply(query_body, tenant_id=...,
   query_text=...)`` *after* building the tenant-filtered base query, and
   passes the hook's return value through — so the hook can add
   ``function_score`` boosting (field-weight boosts, a popularity signal
   from ``AnalyticsStore``/ClickHouse `usage_events`, etc.) without owning
   the tenant-scoping or base multi_match logic.
4. Safety net: ``build_search_query`` asserts the tenant filter is still
   present in whatever the hook returns, and raises if it was stripped —
   a boost profile can change ranking, never remove tenant isolation
   (architecture.md §6).

No boost profile is registered by default; baseline relevance is OpenSearch's
stock BM25 over the ``multi_match`` below.
"""

from __future__ import annotations

from typing import Any, Optional, Protocol

from storage.search.mapping import SEARCHABLE_ENTITY_TYPES


class RelevanceBoostHook(Protocol):
    def apply(self, query_body: dict[str, Any], *, tenant_id: str, query_text: str) -> dict[str, Any]:
        """Return a (possibly modified) OpenSearch query body. Must preserve
        the tenant `term` filter that was present on input."""
        ...


class TenantFilterStrippedError(RuntimeError):
    pass


def build_search_query(
    tenant_id: str,
    query_text: str = "",
    entity_types: Optional[list[str]] = None,
    source_types: Optional[list[str]] = None,
    limit: int = 20,
    offset: int = 0,
    boost_hook: Optional[RelevanceBoostHook] = None,
) -> dict[str, Any]:
    if query_text:
        must: list[dict] = [
            {
                "multi_match": {
                    "query": query_text,
                    "fields": ["name^3", "tags^2", "description", "owner"],
                    "type": "best_fields",
                    "fuzziness": "AUTO",
                }
            }
        ]
    else:
        must = [{"match_all": {}}]

    filters: list[dict] = [
        {"term": {"tenant_id": tenant_id}},
        {"term": {"is_deleted": False}},
    ]
    requested_types = set(entity_types) if entity_types else set(SEARCHABLE_ENTITY_TYPES)
    filters.append({"terms": {"entity_type": sorted(requested_types & SEARCHABLE_ENTITY_TYPES)}})
    if source_types:
        filters.append({"terms": {"source_type": source_types}})

    query_body: dict[str, Any] = {
        "query": {"bool": {"must": must, "filter": filters}},
        "from": offset,
        "size": limit,
    }

    if boost_hook is not None:
        query_body = boost_hook.apply(query_body, tenant_id=tenant_id, query_text=query_text)
        if not _has_tenant_filter(query_body, tenant_id):
            raise TenantFilterStrippedError(
                "relevance boost hook returned a query body without the tenant_id filter — refusing to execute it"
            )

    return query_body


def _has_tenant_filter(query_body: Any, tenant_id: str) -> bool:
    if isinstance(query_body, dict):
        term = query_body.get("term")
        if isinstance(term, dict) and term.get("tenant_id") == tenant_id:
            return True
        return any(_has_tenant_filter(v, tenant_id) for v in query_body.values())
    if isinstance(query_body, list):
        return any(_has_tenant_filter(v, tenant_id) for v in query_body)
    return False
