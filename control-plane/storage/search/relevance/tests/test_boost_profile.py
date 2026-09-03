import copy

import pytest

from relevance.boost_profile import BoostProfile, DEFAULT_BOOST_PROFILE, apply_field_boosts


def test_default_profile_orders_name_above_description_above_tags():
    assert DEFAULT_BOOST_PROFILE.name_weight > DEFAULT_BOOST_PROFILE.description_weight
    assert DEFAULT_BOOST_PROFILE.description_weight > DEFAULT_BOOST_PROFILE.tags_weight


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(name_weight=1.0, description_weight=2.0, tags_weight=0.5),  # name < description
        dict(name_weight=3.0, description_weight=1.0, tags_weight=2.0),  # tags > description
        dict(name_weight=1.0, description_weight=1.0, tags_weight=1.0),  # all equal
        dict(name_weight=-1.0, description_weight=0.5, tags_weight=0.1),  # negative
    ],
)
def test_boost_profile_rejects_orderings_that_violate_name_gt_description_gt_tags(kwargs):
    with pytest.raises(ValueError):
        BoostProfile(**kwargs)


def test_boost_profile_rejects_negative_popularity_weight():
    with pytest.raises(ValueError):
        BoostProfile(popularity_weight=-0.1)


def test_boost_profile_rejects_negative_max_popularity_functions():
    with pytest.raises(ValueError):
        BoostProfile(max_popularity_functions=-1)


def _basic_query():
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
                "filter": [{"term": {"tenant_id": "tenant-1"}}],
            }
        }
    }


def test_apply_field_boosts_weights_name_description_tags_in_that_order():
    boosted = apply_field_boosts(_basic_query())
    fields = boosted["query"]["bool"]["must"][0]["multi_match"]["fields"]

    parsed = {f.split("^")[0]: float(f.split("^")[1]) for f in fields}
    assert parsed["name"] > parsed["description"] > parsed["tags"]
    assert parsed["name"] == DEFAULT_BOOST_PROFILE.name_weight
    assert parsed["description"] == DEFAULT_BOOST_PROFILE.description_weight
    assert parsed["tags"] == DEFAULT_BOOST_PROFILE.tags_weight


def test_apply_field_boosts_respects_custom_profile():
    profile = BoostProfile(name_weight=10.0, description_weight=4.0, tags_weight=1.0)
    boosted = apply_field_boosts(_basic_query(), profile)
    fields = boosted["query"]["bool"]["must"][0]["multi_match"]["fields"]
    assert fields == ["name^10", "description^4", "tags^1"]


def test_apply_field_boosts_leaves_unrecognized_fields_untouched():
    query = {
        "query": {
            "multi_match": {
                "query": "orders",
                "fields": ["name", "owner", "custom_field"],
            }
        }
    }
    boosted = apply_field_boosts(query)
    fields = boosted["query"]["multi_match"]["fields"]
    assert fields[0].startswith("name^")
    assert fields[1] == "owner"
    assert fields[2] == "custom_field"


def test_apply_field_boosts_is_a_noop_passthrough_when_no_multi_match_present():
    """Baseline additivity guarantee: a base query this module doesn't
    recognize at all (no multi_match clause anywhere) must still come back
    usable, unchanged in content — this is what lets FE2's baseline keyword
    search work correctly with zero boost profile present."""
    query = {
        "query": {"term": {"name.keyword": "orders_fact"}},
        "size": 20,
        "from": 0,
    }
    boosted = apply_field_boosts(query)
    assert boosted == query


def test_apply_field_boosts_finds_multi_match_nested_arbitrarily_deep():
    query = {
        "query": {
            "bool": {
                "should": [
                    {
                        "bool": {
                            "must": [
                                {
                                    "multi_match": {
                                        "query": "churn",
                                        "fields": ["name", "tags"],
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        }
    }
    boosted = apply_field_boosts(query)
    nested_fields = boosted["query"]["bool"]["should"][0]["bool"]["must"][0]["multi_match"][
        "fields"
    ]
    assert nested_fields[0].startswith("name^")
    assert nested_fields[1].startswith("tags^")


def test_apply_field_boosts_does_not_mutate_input_query():
    original = _basic_query()
    snapshot = copy.deepcopy(original)
    apply_field_boosts(original)
    assert original == snapshot


def test_apply_field_boosts_handles_multiple_multi_match_clauses():
    query = {
        "query": {
            "bool": {
                "should": [
                    {"multi_match": {"query": "a", "fields": ["name"]}},
                    {"multi_match": {"query": "a", "fields": ["description", "tags"]}},
                ]
            }
        }
    }
    boosted = apply_field_boosts(query)
    should = boosted["query"]["bool"]["should"]
    assert should[0]["multi_match"]["fields"] == [f"name^{DEFAULT_BOOST_PROFILE.name_weight:g}"]
    assert should[1]["multi_match"]["fields"] == [
        f"description^{DEFAULT_BOOST_PROFILE.description_weight:g}",
        f"tags^{DEFAULT_BOOST_PROFILE.tags_weight:g}",
    ]
