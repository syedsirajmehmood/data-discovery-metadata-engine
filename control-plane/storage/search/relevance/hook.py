"""The assumed call-out hook FE2's search query builder plugs into.

architecture.md §8: "FE2 ... Leaves a call-out hook in the search query
builder for ML's `relevance/` boost profile (additive — baseline keyword
search must work with no boost profile present)." and "ML ... Plugs into
FE2's query builder via the hook FE2 exposes — additive, so baseline
search ships even if `relevance/` lags."

FE2's actual query-builder module (`control-plane/storage/search/` outside
`relevance/`) has not landed in this worktree, so the exact call site and
hook signature are this module's own assumption, not a confirmed contract.
`apply_relevance_boost` below is that assumption made concrete and testable.
The full write-up of the assumed call site, and how to reconcile this
against FE2's real hook once it exists, is in ../INTERFACE.md — read that
alongside this docstring.

Contract this function commits to, regardless of how FE2 actually calls it:
  - Pure function: `dict in -> dict out`, no I/O, no mutation of the input.
  - Never raises on a well-formed OpenSearch query body, even one this
    module doesn't fully recognize (see boost_profile._iter_multi_match_clauses)
    — at worst it degrades to returning `base_query` deep-copied, unboosted.
  - Never required: if FE2's query builder simply never calls this (module
    not yet wired, import guarded by try/except, feature-flagged off, etc.)
    baseline keyword search is entirely unaffected. Nothing in this module
    reaches into FE2's code or state.
"""

from __future__ import annotations

import copy
import warnings
from typing import Any, Mapping

from .boost_profile import BoostProfile, DEFAULT_BOOST_PROFILE, apply_field_boosts


def _contains_tenant_term_filter(node: Any, tenant_id: str) -> bool:
    """Best-effort check that `node` filters on `tenant_id` somewhere.

    Advisory only (see the warning below) — this module does not enforce
    tenant scoping itself (that responsibility belongs to FE2's query
    builder per spec.md NFR-2: "tenant_id must be enforced at the
    query/API layer as a mandatory filter"). It checks defensively because
    NFR-2 flags cross-tenant leaks via the search path as a specific risk,
    and a boost-profile bug is a more likely place to accidentally drop a
    filter clause (e.g. by cloning only part of a query) than to add one.
    """
    if isinstance(node, dict):
        term = node.get("term")
        if isinstance(term, dict) and term.get("tenant_id") == tenant_id:
            return True
        return any(_contains_tenant_term_filter(v, tenant_id) for v in node.values())
    if isinstance(node, list):
        return any(_contains_tenant_term_filter(item, tenant_id) for item in node)
    return False


def apply_relevance_boost(
    base_query: dict[str, Any],
    *,
    tenant_id: str,
    popularity_scores: Mapping[str, float] | None = None,
    profile: BoostProfile = DEFAULT_BOOST_PROFILE,
) -> dict[str, Any]:
    """Assumed hook signature. See ../INTERFACE.md for the full contract.

    Args:
        base_query: FE2's fully-built OpenSearch query body (query + any
            tenant filter, pagination, etc.) exactly as it would be sent to
            OpenSearch with no boost profile applied. Not mutated.
        tenant_id: the resolved tenant for this request (server-side
            resolved per NFR-2 — never accept this from client input).
            Used only for the advisory tenant-filter sanity check above;
            not injected into the query itself, since that's FE2's job and
            duplicating it here risks the two filters drifting apart.
        popularity_scores: optional `{urn: normalized_score in [0, 1]}`,
            typically the output of
            `popularity.popularity_scores_from_analytics_client(...)`
            computed by whatever caller/scheduler owns refreshing it
            (out of this module's scope — see ../INTERFACE.md for the
            assumed refresh model). If omitted or empty, popularity
            blending is skipped entirely and only field-weight boosting is
            applied — this is what keeps "no popularity data yet" a
            degrade-gracefully case rather than a broken one.
        profile: the field-weight / popularity-blend tuning to use.
            Defaults to `DEFAULT_BOOST_PROFILE`.

    Returns:
        A new query body: `base_query` with field weights applied, and
        (if `popularity_scores` is non-empty) wrapped in a `function_score`
        that boosts the top `profile.max_popularity_functions` most popular
        urns. Safe to pass directly to an OpenSearch `search()` call.
    """
    if not _contains_tenant_term_filter(base_query, tenant_id):
        warnings.warn(
            "relevance.apply_relevance_boost: base_query does not appear to "
            f"contain a term filter on tenant_id={tenant_id!r}. Per spec.md "
            "NFR-2, every catalog read path must be tenant-scoped; this "
            "module assumes FE2's query builder already applies that filter "
            "before this hook runs and does not add one itself. If this "
            "warning fires in real usage, verify the base_query passed in "
            "actually carries the tenant filter.",
            RuntimeWarning,
            stacklevel=2,
        )

    query = apply_field_boosts(base_query, profile)
    if popularity_scores:
        query = apply_popularity_boost(query, popularity_scores, profile)
    else:
        query = copy.deepcopy(query)
    return query


def build_popularity_functions(
    scores: Mapping[str, float], profile: BoostProfile = DEFAULT_BOOST_PROFILE
) -> list[dict[str, Any]]:
    """Build the OpenSearch `function_score.functions` list for a popularity map.

    Only the top `profile.max_popularity_functions` urns by score are
    included (see BoostProfile.max_popularity_functions docstring for why),
    and zero/negative scores are dropped since they'd be no-op weights of
    1.0 anyway (`1 + popularity_weight * 0 == 1`).
    """
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top = ranked[: profile.max_popularity_functions]
    return [
        {"filter": {"term": {"urn": urn}}, "weight": 1.0 + profile.popularity_weight * score}
        for urn, score in top
        if score > 0
    ]


def apply_popularity_boost(
    query: dict[str, Any],
    scores: Mapping[str, float],
    profile: BoostProfile = DEFAULT_BOOST_PROFILE,
) -> dict[str, Any]:
    """Wrap `query` in a function_score that boosts popular urns.

    Uses per-urn `term` filter functions rather than a precomputed
    "popularity" field on each document, so this works against FE2's index
    mapping as-is (any document with a `urn` field, which every entity type
    has) with no dependency on FE2 denormalizing a popularity field onto
    documents. See ../ROADMAP.md for the field_value_factor alternative
    once/if that denormalization exists.

    `score_mode: sum` + `boost_mode: multiply`: at most one filter matches
    any given document (each urn appears once), so `sum` is equivalent to
    "the one matching weight, or 1.0 if none match" — multiply means a
    document's base keyword-relevance score is scaled up, never overridden,
    so a poor keyword match on a popular table still doesn't outrank a
    strong keyword match on an unpopular one.

    Returns `query` (deep-copied) unwrapped/unchanged if `scores` yields no
    functions (e.g. all-zero scores, or empty) — additive, never a no-op
    that silently degrades an otherwise-fine query into an empty
    function_score.
    """
    functions = build_popularity_functions(scores, profile)
    if not functions:
        return copy.deepcopy(query)
    return {
        "function_score": {
            "query": copy.deepcopy(query),
            "functions": functions,
            "score_mode": "sum",
            "boost_mode": "multiply",
        }
    }
