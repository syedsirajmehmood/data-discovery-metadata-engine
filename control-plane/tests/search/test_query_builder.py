"""Pure unit tests for the query builder + ML relevance-hook seam — no
OpenSearch required.
"""

from __future__ import annotations

import pytest

from storage.search.query_builder import TenantFilterStrippedError, build_search_query


def test_build_search_query_includes_tenant_filter():
    body = build_search_query(tenant_id="t1", query_text="orders")
    filters = body["query"]["bool"]["filter"]
    assert {"term": {"tenant_id": "t1"}} in filters


def test_build_search_query_defaults_to_match_all_when_no_query_text():
    body = build_search_query(tenant_id="t1", query_text="")
    assert body["query"]["bool"]["must"] == [{"match_all": {}}]


def test_boost_hook_can_add_function_score_without_removing_tenant_filter():
    class AddsPopularityBoost:
        def apply(self, query_body, *, tenant_id, query_text):
            inner_query = query_body["query"]
            return {
                "query": {"function_score": {"query": inner_query, "field_value_factor": {"field": "popularity"}}},
                "from": query_body["from"],
                "size": query_body["size"],
            }

    body = build_search_query(tenant_id="t1", query_text="orders", boost_hook=AddsPopularityBoost())
    assert "function_score" in body["query"]


def test_boost_hook_stripping_tenant_filter_is_rejected():
    class BuggyHook:
        def apply(self, query_body, *, tenant_id, query_text):
            return {"query": {"match_all": {}}}  # drops the tenant filter entirely

    with pytest.raises(TenantFilterStrippedError):
        build_search_query(tenant_id="t1", query_text="orders", boost_hook=BuggyHook())


def test_entity_type_filter_only_allows_searchable_types():
    body = build_search_query(tenant_id="t1", query_text="x", entity_types=["table", "lineage_edge", "bogus"])
    filters = body["query"]["bool"]["filter"]
    entity_type_filter = next(f["terms"]["entity_type"] for f in filters if "terms" in f and "entity_type" in f["terms"])
    assert entity_type_filter == ["table"]  # lineage_edge/bogus silently dropped, not passed through to OpenSearch
