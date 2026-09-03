# Assumed integration interface (ML → FE2)

Status: **assumption, not a confirmed contract.** FE2 owns
`control-plane/storage/search/` (everything outside this `relevance/`
subdirectory — base OpenSearch client, index mapping, query builder) per
architecture.md §8, and FE2's branch has not landed in this worktree at the
time this was written. architecture.md §8 says FE2 "leaves a call-out hook
in the search query builder for ML's `relevance/` boost profile (additive —
baseline keyword search must work with no boost profile present)" but does
not pin the exact function signature. This document is that signature,
written from the ML side, so it can be reconciled against FE2's actual hook
once it exists — either FE2 conforms to this, or this file gets updated to
match FE2's real one (whichever lands first should treat the other as the
diff to review, not silently ignore it).

## 1. The hook this module exposes

```python
# control-plane/storage/search/relevance/hook.py

def apply_relevance_boost(
    base_query: dict,
    *,
    tenant_id: str,
    popularity_scores: Mapping[str, float] | None = None,
    profile: BoostProfile = DEFAULT_BOOST_PROFILE,
) -> dict:
    ...
```

- **Input**: `base_query` — FE2's fully-built OpenSearch query body (the
  `dict` that would be passed as-is to `opensearch_client.search(body=...)`
  with zero boost profile applied). Must already include tenant scoping
  (a `term` filter on `tenant_id`) — this module checks for that
  defensively (see §3) but does not add it.
- **Output**: a new query `dict`, safe to send to OpenSearch directly. The
  input is never mutated.
- **No exceptions on well-formed input.** Field boosting degrades to a
  no-op passthrough if it doesn't recognize the query shape (e.g. no
  `multi_match` clause anywhere); popularity blending is skipped entirely
  if `popularity_scores` is `None` or empty. This is what makes the
  integration "additive": FE2's query builder can call this
  unconditionally and never get a worse-than-baseline result, and can also
  simply *not* call it (module not wired yet, feature-flagged off, import
  guarded) with zero effect on baseline search.

## 2. Assumed call site inside FE2's query builder

```python
# control-plane/storage/search/query_builder.py  (FE2's file — illustrative, not present in this worktree)

def build_search_query(search_term: str, tenant_id: str) -> dict:
    base_query = {
        "query": {
            "bool": {
                "must": [
                    {"multi_match": {"query": search_term, "fields": ["name", "description", "tags"]}}
                ],
                "filter": [{"term": {"tenant_id": tenant_id}}],
            }
        },
    }

    try:
        from control_plane.storage.search.relevance import apply_relevance_boost
    except ImportError:
        return base_query  # relevance/ not present/landed yet -> baseline search still works

    popularity_scores = get_current_popularity_scores(tenant_id)  # see §4 — refresh model TBD/FE1's
    return apply_relevance_boost(base_query, tenant_id=tenant_id, popularity_scores=popularity_scores)
```

Two structural assumptions baked into that call site that matter for
reconciliation:

1. **Field weighting is applied by rewriting an existing `multi_match`
   clause's `fields` list**, not by FE2 handing this module a raw search
   term and letting it build the whole query from scratch. If FE2's query
   builder does not use `multi_match` (e.g. uses separate `match` clauses
   per field, or `simple_query_string`), `apply_field_boosts`
   (`boost_profile.py`) will not find anything to reweight and will return
   the query unchanged — safe, but silently a no-op. **Action for whoever
   wires this for real:** either adapt FE2's query builder to use
   `multi_match` over `["name", "description", "tags"]`, or extend
   `boost_profile._iter_multi_match_clauses` to also recognize FE2's actual
   clause shape.
2. **Popularity scores are passed in as an already-computed
   `{urn: score}` mapping**, not fetched by this hook itself. This module
   deliberately does not decide *when*/*how often* popularity is
   recomputed (per-request from ClickHouse would be too slow for a search
   API's latency budget; a periodic background refresh is the intended
   model) — see `popularity.py`'s `popularity_scores_from_analytics_client`
   for the compute step, and §4 below for what's unresolved about wiring
   that into a request path.

## 3. Tenant-filter sanity check

`apply_relevance_boost` walks `base_query` looking for a
`{"term": {"tenant_id": tenant_id}}` clause anywhere in the tree and emits a
`RuntimeWarning` (not an exception — this module must not be able to break
a request FE2's code would otherwise have served) if it can't find one. Per
spec.md NFR-2, every catalog read path must be tenant-scoped; this check
exists because a boost-profile bug (e.g. cloning only part of a query) is a
plausible way to accidentally *drop* an existing filter, and this module
touches the query body last before it goes to OpenSearch. It does not add a
tenant filter itself — that responsibility structurally belongs to FE2's
query builder, and duplicating it here risks the two drifting apart if
FE2's filter shape ever changes.

## 4. Assumed analytics-client read interface

architecture.md §8 says this module reads `usage_events` "via FE2's
analytics client" and architecture.md §4 documents `AnalyticsStore
.record_event()` as FE2's **write** method (used by the fan-out worker).
No read method is documented anywhere in architecture.md at the time of
writing. `popularity.py` assumes:

```python
class AnalyticsClientProtocol(Protocol):
    def query_usage_events(self, *, tenant_id: str, since: datetime) -> Iterable[UsageEvent]:
        ...
```

where `UsageEvent` mirrors the ClickHouse row shape from architecture.md §4
(`tenant_id, urn, actor, action, occurred_at`). This is expressed as a
`typing.Protocol` — structural typing, so this module never imports FE2's
actual `AnalyticsStore` class — and consumed only by
`popularity_scores_from_analytics_client`, which is a thin wrapper around
the pure, fully-tested `compute_popularity_scores`.

**Open question this file flags rather than silently resolves:** *who*
calls `popularity_scores_from_analytics_client` and *how often* (every
request? a periodic job populating a cache FE2's query builder reads from?)
is unspecified in architecture.md and not decided by this module — a
per-request ClickHouse round-trip inside the search request path is
probably wrong for AC-1's "p95 under 2 seconds" requirement (spec.md), so
the likely correct answer is a periodic background refresh (e.g. every few
minutes) writing into whatever cache/store FE2's query builder reads
synchronously from. That scheduling piece is out of this module's scope
(`relevance/` per §8 is the scoring/boosting logic only) and belongs to
whoever owns request-path wiring — flagging it here so it isn't assumed
free when reconciling.

## 5. Reconciliation checklist

When FE2's actual query builder and analytics client land, check:

- [ ] Does FE2's base query use a `multi_match` clause over
      `name`/`description`/`tags`? If not, update
      `boost_profile._iter_multi_match_clauses` (or FE2's query shape) to
      match.
- [ ] Does FE2's base query include `{"term": {"tenant_id": ...}}`? If it
      uses a different tenant-scoping mechanism (e.g. index-per-tenant,
      routing key), update `hook._contains_tenant_term_filter` — right now
      it will emit a spurious warning against a not-actually-wrong query.
- [ ] Does FE2's `AnalyticsStore` expose a read method matching
      `AnalyticsClientProtocol.query_usage_events`? If it has a different
      name/signature, either adapt the protocol here or add a thin adapter
      — do not reimplement the ClickHouse query in this module.
- [ ] Is there an agreed place that periodically calls
      `popularity_scores_from_analytics_client` and hands the result to
      `apply_relevance_boost`'s `popularity_scores` argument? (§4's open
      question.)
