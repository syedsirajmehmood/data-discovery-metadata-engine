from datetime import datetime, timedelta, timezone
from typing import Iterable

from relevance.popularity import (
    UsageEvent,
    compute_popularity_scores,
    popularity_scores_from_analytics_client,
)

NOW = datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc)
TENANT = "tenant-1"


def _event(urn, action="view", days_ago=0.0, tenant_id=TENANT, actor="dana"):
    return UsageEvent(
        tenant_id=tenant_id,
        urn=urn,
        actor=actor,
        action=action,
        occurred_at=NOW - timedelta(days=days_ago),
    )


def test_empty_events_yields_empty_scores():
    assert compute_popularity_scores([], tenant_id=TENANT, now=NOW) == {}


def test_most_active_urn_scores_exactly_one_after_normalization():
    events = [
        _event("urn:table:orders", days_ago=0),
        _event("urn:table:orders", days_ago=0),
        _event("urn:table:orders", days_ago=0),
        _event("urn:table:customers", days_ago=0),
    ]
    scores = compute_popularity_scores(events, tenant_id=TENANT, now=NOW)
    assert scores["urn:table:orders"] == 1.0
    assert 0.0 < scores["urn:table:customers"] < 1.0


def test_recent_events_score_higher_than_old_events_of_equal_weight():
    events = [
        _event("urn:table:recent", action="view", days_ago=0),
        _event("urn:table:old", action="view", days_ago=60),
    ]
    scores = compute_popularity_scores(events, tenant_id=TENANT, now=NOW, half_life_days=14)
    assert scores["urn:table:recent"] > scores["urn:table:old"]


def test_half_life_decay_is_approximately_correct():
    # raw score for "x" = 1.0 (today) + 0.5 (exactly one half-life ago) = 1.5.
    # Normalization divides by the max raw score, so introduce a third,
    # dominant urn to make that ratio observable rather than trivially 1.0.
    events_with_dominant = [
        _event("urn:table:dominant", action="query", days_ago=0),  # weight 3.0
        _event("urn:table:x", action="view", days_ago=0),  # weight 1.0
        _event("urn:table:x", action="view", days_ago=14),  # weight 1.0 * 0.5 decay
    ]
    scores = compute_popularity_scores(
        events_with_dominant, tenant_id=TENANT, now=NOW, half_life_days=14
    )
    assert scores["urn:table:dominant"] == 1.0
    assert abs(scores["urn:table:x"] - (1.5 / 3.0)) < 1e-9


def test_events_from_other_tenants_are_excluded():
    events = [
        _event("urn:table:mine", tenant_id="tenant-1"),
        _event("urn:table:mine", tenant_id="tenant-2"),  # different tenant, same urn
        _event("urn:table:not-mine", tenant_id="tenant-2"),
    ]
    scores = compute_popularity_scores(events, tenant_id="tenant-1", now=NOW)
    assert "urn:table:not-mine" not in scores
    # only the tenant-1 event counted, so "mine" should reflect exactly 1 event's weight
    assert scores["urn:table:mine"] == 1.0


def test_future_occurred_at_is_clamped_to_zero_age_not_negative():
    events = [_event("urn:table:future", action="view", days_ago=-5)]  # in the future
    scores = compute_popularity_scores(events, tenant_id=TENANT, now=NOW, half_life_days=14)
    assert scores["urn:table:future"] == 1.0


def test_custom_action_weights_override_defaults():
    events = [
        _event("urn:table:a", action="custom_action", days_ago=0),
        _event("urn:table:b", action="view", days_ago=0),
    ]
    scores = compute_popularity_scores(
        events,
        tenant_id=TENANT,
        now=NOW,
        action_weights={"custom_action": 100.0},
    )
    assert scores["urn:table:a"] == 1.0
    assert scores["urn:table:b"] < scores["urn:table:a"]


def test_unrecognized_action_defaults_to_weight_one_rather_than_being_dropped():
    events = [_event("urn:table:a", action="totally_unknown_action", days_ago=0)]
    scores = compute_popularity_scores(events, tenant_id=TENANT, now=NOW)
    assert scores == {"urn:table:a": 1.0}


class _FakeAnalyticsClient:
    """Minimal stand-in satisfying AnalyticsClientProtocol structurally."""

    def __init__(self, events):
        self._events = events

    def query_usage_events(self, *, tenant_id: str, since: datetime) -> Iterable[UsageEvent]:
        return [
            e
            for e in self._events
            if e.tenant_id == tenant_id and e.occurred_at >= since
        ]


def test_popularity_scores_from_analytics_client_filters_by_lookback_and_scores():
    events = [
        _event("urn:table:recent", days_ago=1),
        _event("urn:table:ancient", days_ago=365),  # outside default 90-day lookback
    ]
    client = _FakeAnalyticsClient(events)
    scores = popularity_scores_from_analytics_client(
        client, tenant_id=TENANT, now=NOW, lookback_days=90
    )
    assert "urn:table:recent" in scores
    assert "urn:table:ancient" not in scores
