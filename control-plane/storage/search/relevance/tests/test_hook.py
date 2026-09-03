import warnings

import pytest

from relevance.boost_profile import BoostProfile
from relevance.hook import apply_popularity_boost, apply_relevance_boost, build_popularity_functions


def _base_query(tenant_id="tenant-1"):
    return {
        "query": {
            "bool": {
                "must": [
                    {
                        "multi_match": {
                            "query": "orders",
                            "fields": ["name", "description", "tags"],
                        }
                    }
                ],
                "filter": [{"term": {"tenant_id": tenant_id}}],
            }
        },
        "size": 20,
    }


def test_apply_relevance_boost_applies_field_weights_with_no_popularity_data():
    """This is the 'genuinely additive' baseline case: FE2's query builder
    calls the hook, but no popularity signal is available yet (e.g. ML's
    popularity precompute job hasn't run) — field weighting still applies
    and the query is still a plain, valid OpenSearch body, not wrapped in
    an empty/broken function_score."""
    result = apply_relevance_boost(_base_query(), tenant_id="tenant-1")
    assert "function_score" not in result
    fields = result["query"]["bool"]["must"][0]["multi_match"]["fields"]
    assert fields[0].startswith("name^")
    assert fields[1].startswith("description^")
    assert fields[2].startswith("tags^")


def test_apply_relevance_boost_blends_in_popularity_when_scores_present():
    scores = {"urn:table:orders": 1.0, "urn:table:other": 0.2}
    result = apply_relevance_boost(
        _base_query(), tenant_id="tenant-1", popularity_scores=scores
    )
    assert "function_score" in result
    fn = result["function_score"]
    assert fn["score_mode"] == "sum"
    assert fn["boost_mode"] == "multiply"
    # field boosting still happened on the inner query
    inner_fields = fn["query"]["query"]["bool"]["must"][0]["multi_match"]["fields"]
    assert inner_fields[0].startswith("name^")
    # both urns represented, ordered by score descending
    weights_by_urn = {f["filter"]["term"]["urn"]: f["weight"] for f in fn["functions"]}
    assert weights_by_urn["urn:table:orders"] > weights_by_urn["urn:table:other"] > 1.0


def test_apply_relevance_boost_never_mutates_base_query():
    base = _base_query()
    import copy

    snapshot = copy.deepcopy(base)
    apply_relevance_boost(base, tenant_id="tenant-1", popularity_scores={"x": 1.0})
    assert base == snapshot


def test_apply_relevance_boost_warns_when_tenant_filter_missing():
    query_without_tenant_filter = {
        "query": {"multi_match": {"query": "orders", "fields": ["name"]}}
    }
    with pytest.warns(RuntimeWarning, match="tenant_id"):
        apply_relevance_boost(query_without_tenant_filter, tenant_id="tenant-1")


def test_apply_relevance_boost_does_not_warn_when_tenant_filter_present():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        apply_relevance_boost(_base_query(tenant_id="tenant-1"), tenant_id="tenant-1")


def test_build_popularity_functions_caps_at_max_popularity_functions():
    profile = BoostProfile(max_popularity_functions=2)
    scores = {"a": 0.9, "b": 0.8, "c": 0.7, "d": 0.6}
    functions = build_popularity_functions(scores, profile)
    assert len(functions) == 2
    urns = {f["filter"]["term"]["urn"] for f in functions}
    assert urns == {"a", "b"}  # the two highest scores


def test_build_popularity_functions_drops_zero_and_negative_scores():
    scores = {"a": 1.0, "b": 0.0, "c": -0.1}
    functions = build_popularity_functions(scores)
    urns = {f["filter"]["term"]["urn"] for f in functions}
    assert urns == {"a"}


def test_apply_popularity_boost_is_noop_passthrough_for_empty_scores():
    query = _base_query()
    result = apply_popularity_boost(query, {})
    assert "function_score" not in result
    assert result == query


def test_apply_relevance_boost_default_profile_is_used_when_none_given():
    result = apply_relevance_boost(_base_query(), tenant_id="tenant-1")
    fields = result["query"]["bool"]["must"][0]["multi_match"]["fields"]
    assert fields == ["name^5", "description^2", "tags^1"]
