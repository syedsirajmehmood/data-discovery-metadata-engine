"""control-plane/storage/search/relevance — ML engineer's scope only.

Per architecture.md §8, this directory is the ranking/boost layer on top of
FE2's base OpenSearch index and query builder (`control-plane/storage/
search/`, everything outside `relevance/`, which this package never
imports from or edits). Two things live here:

  - `boost_profile.py` — field-weight boosting (name > description > tags).
  - `popularity.py` — a popularity signal computed from ClickHouse
    `usage_events`, via the *assumed* read interface of FE2's analytics
    client (referenced structurally through `AnalyticsClientProtocol`,
    never reimplemented).

`hook.py` composes both behind `apply_relevance_boost`, the single function
this module assumes FE2's query builder calls out to. See `INTERFACE.md`
for the exact assumed hook contract and how to reconcile it against FE2's
real implementation, and `ROADMAP.md` for what's explicitly deferred
post-MVP (embeddings-based semantic search / similar-table
recommendations).

Every symbol below is a pure function or frozen dataclass — no OpenSearch or
ClickHouse client, no network I/O, anywhere in this package. That's what
makes it testable without a live OpenSearch/ClickHouse instance (see
`tests/`) and what makes it safe to import even before FE2's or FE1's parts
of the system exist.
"""

from .boost_profile import BoostProfile, DEFAULT_BOOST_PROFILE, apply_field_boosts
from .hook import apply_popularity_boost, apply_relevance_boost, build_popularity_functions
from .popularity import (
    DEFAULT_ACTION_WEIGHTS,
    AnalyticsClientProtocol,
    UsageEvent,
    compute_popularity_scores,
    popularity_scores_from_analytics_client,
)

__all__ = [
    "BoostProfile",
    "DEFAULT_BOOST_PROFILE",
    "apply_field_boosts",
    "apply_popularity_boost",
    "apply_relevance_boost",
    "build_popularity_functions",
    "DEFAULT_ACTION_WEIGHTS",
    "AnalyticsClientProtocol",
    "UsageEvent",
    "compute_popularity_scores",
    "popularity_scores_from_analytics_client",
]
