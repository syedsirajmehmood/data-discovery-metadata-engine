"""Popularity signal computed from ClickHouse ``usage_events``.

architecture.md §4 defines the ClickHouse table this reads from:

    usage_events(tenant_id, urn, actor, action, occurred_at)
    ORDER BY (tenant_id, occurred_at), partitioned by month

and §8 scopes this engineer's work to "a popularity signal computed from
`usage_events` in ClickHouse (FE2's analytics client) blended into result
ranking." FE2 owns the actual ClickHouse client/connection
(`control-plane/storage/analytics/`); this module never opens a ClickHouse
connection itself. Instead it:

  1. Defines ``UsageEvent``, a plain dataclass mirroring the row shape above,
     so the scoring logic is testable against fixture data with zero live
     dependencies.
  2. Defines ``AnalyticsClientProtocol``, the *read-side* interface this
     module assumes FE2's analytics client exposes, and consumes it purely
     structurally (``typing.Protocol`` — no import of FE2's actual client
     class, no reimplementation of the ClickHouse query). See
     ../INTERFACE.md for why this is an assumption rather than a confirmed
     contract, and how to reconcile it.
  3. Computes a normalized, time-decayed popularity score per urn as a pure
     function (``compute_popularity_scores``) that takes a plain iterable of
     ``UsageEvent`` and returns ``{urn: score}`` with no I/O at all.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping, Protocol

# Per-action relative weight: an actual query/execution against a table is a
# much stronger popularity signal than a search-result impression. Actions
# not listed here default to 1.0 (see compute_popularity_scores) rather than
# being dropped, so an unrecognized/future action type still counts instead
# of silently vanishing from the signal.
DEFAULT_ACTION_WEIGHTS: Mapping[str, float] = {
    "view": 1.0,
    "search_result_click": 1.0,
    "detail_view": 1.5,
    "query": 3.0,
    "query_execute": 3.0,
    "download": 2.0,
}


@dataclass(frozen=True)
class UsageEvent:
    """Mirrors one row of ClickHouse `usage_events` (architecture.md §4)."""

    tenant_id: str
    urn: str
    actor: str
    action: str
    occurred_at: datetime


class AnalyticsClientProtocol(Protocol):
    """The read-side interface this module assumes FE2's analytics client exposes.

    architecture.md §8 only documents FE2's *write* method,
    ``AnalyticsStore.record_event()`` (used by the fan-out worker to record
    events as they happen). It does not specify a read method for querying
    `usage_events` back out — that's this module's own assumption, made
    explicit here (as a `typing.Protocol`, so this module never imports
    FE2's concrete class — only structurally depends on this shape) so it
    can be reconciled against FE2's actual `AnalyticsStore` once it lands.
    See ../INTERFACE.md.
    """

    def query_usage_events(
        self, *, tenant_id: str, since: datetime
    ) -> Iterable[UsageEvent]:
        """Return usage events for `tenant_id` with `occurred_at >= since`."""
        ...


def compute_popularity_scores(
    events: Iterable[UsageEvent],
    *,
    tenant_id: str,
    now: datetime,
    half_life_days: float = 14.0,
    action_weights: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """Compute a normalized [0, 1] popularity score per urn from usage events.

    score(urn) = sum over matching events of
                     action_weight(action) * 0.5 ** (age_days / half_life_days)
    then divided by the max raw score across urns, so the single most
    popular urn in the result set scores exactly 1.0 and everything else is
    relative to it (keeps the blend in `BoostProfile.popularity_weight`
    meaningful regardless of a tenant's absolute event volume).

    Tenant scoping is enforced *inside* this function (events not matching
    `tenant_id` are silently skipped) rather than trusted to the caller —
    per spec.md NFR-2 ("tenant_id must be enforced at the query/API layer
    as a mandatory filter... not just present as a column"), this is
    belt-and-suspenders: even if a caller accidentally passes
    unfiltered/mixed-tenant events, this function will not leak another
    tenant's popularity signal into results.

    Events with `occurred_at` in the future relative to `now` are treated
    as zero-age (clamped), not negative-age (which would otherwise inflate
    their weight above a same-instant event due to floating point).

    Returns {} for no matching events — callers should treat that as "no
    popularity signal available" and skip popularity blending entirely
    (this is what `hook.apply_relevance_boost` does), not as an error.
    """
    weights = dict(DEFAULT_ACTION_WEIGHTS)
    if action_weights:
        weights.update(action_weights)

    raw_scores: dict[str, float] = defaultdict(float)
    for event in events:
        if event.tenant_id != tenant_id:
            continue
        age_days = max((now - event.occurred_at).total_seconds(), 0.0) / 86400.0
        decay = 0.5 ** (age_days / half_life_days) if half_life_days > 0 else 1.0
        raw_scores[event.urn] += weights.get(event.action, 1.0) * decay

    if not raw_scores:
        return {}

    max_score = max(raw_scores.values())
    if max_score <= 0:
        return {urn: 0.0 for urn in raw_scores}
    return {urn: score / max_score for urn, score in raw_scores.items()}


def popularity_scores_from_analytics_client(
    client: AnalyticsClientProtocol,
    *,
    tenant_id: str,
    now: datetime | None = None,
    lookback_days: float = 90.0,
    half_life_days: float = 14.0,
    action_weights: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """Convenience wrapper: pull events from `client` and score them.

    This is the one place in the module that touches the (assumed)
    analytics client. Everything it does beyond the `client.query_usage_events`
    call is delegated to the pure `compute_popularity_scores` above, so this
    wrapper itself needs no test double beyond a trivial fake — the actual
    scoring logic is fully covered by pure-function tests.
    """
    resolved_now = now or datetime.now(timezone.utc)
    since = resolved_now - timedelta(days=lookback_days)
    events = list(client.query_usage_events(tenant_id=tenant_id, since=since))
    return compute_popularity_scores(
        events,
        tenant_id=tenant_id,
        now=resolved_now,
        half_life_days=half_life_days,
        action_weights=action_weights,
    )
