"""Field-weight boosting for catalog search.

Pure, dependency-free functions that transform an OpenSearch query-body
``dict`` so that a match on ``name`` ranks above a match on ``description``,
which ranks above a match on ``tags`` only — per architecture.md §4/§8
("field-weight boosting (name > description > tags)").

Nothing here talks to OpenSearch, ClickHouse, or any network. Every function
takes plain dicts/dataclasses in and returns plain dicts out, so it is
testable as pure logic against fixture data (see ../tests/).

This module owns *field* weighting only. Popularity blending lives in
``popularity.py``; the two are composed in ``hook.py``, which is the single
assumed integration point for FE2's query builder (see ../INTERFACE.md).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Iterator

# The three fields architecture.md §4 says OpenSearch indexes and that this
# module is scoped to weight: "Indexes table/column/dashboard `name`,
# `description`, `tags`, `owner`, denormalized from Postgres by the fan-out
# worker." `owner` is deliberately not boosted here — it's an identity
# field, not free text worth ranking on.
_RANKABLE_FIELDS = ("name", "description", "tags")


@dataclass(frozen=True)
class BoostProfile:
    """Relative field weights + popularity-blend knobs.

    Field weights are OpenSearch ``multi_match`` boost multipliers (the
    ``field^weight`` syntax). The only hard constraint the spec imposes is
    the *ordering*: name > description > tags. Absolute magnitudes are a
    tuning knob, not a contract, so they're free to retune without touching
    calling code.

    ``popularity_weight`` and ``max_popularity_functions`` control how the
    ClickHouse-derived popularity signal (popularity.py) is blended in by
    ``apply_popularity_boost`` / ``hook.apply_relevance_boost``.
    """

    name_weight: float = 5.0
    description_weight: float = 2.0
    tags_weight: float = 1.0

    # Multiplicative headroom given to the single most popular result:
    # a doc with normalized popularity score 1.0 gets its function_score
    # multiplied by (1 + popularity_weight); a score of 0 is untouched.
    popularity_weight: float = 1.0

    # OpenSearch function_score functions are O(n) per query; cap how many
    # per-urn popularity boosts we ever attach to one query so a tenant with
    # a huge catalog can't blow up query cost. Only the top-N most popular
    # urns (by score) are boosted — everything else ranks on keyword match
    # alone, which is a safe, correct fallback, not a broken state.
    max_popularity_functions: int = 200

    def __post_init__(self) -> None:
        if not (self.name_weight > self.description_weight > self.tags_weight):
            raise ValueError(
                "BoostProfile must satisfy name_weight > description_weight > "
                f"tags_weight (per architecture.md §8); got "
                f"name={self.name_weight}, description={self.description_weight}, "
                f"tags={self.tags_weight}"
            )
        for field_name in ("name_weight", "description_weight", "tags_weight"):
            if getattr(self, field_name) <= 0:
                raise ValueError(f"{field_name} must be > 0")
        if self.popularity_weight < 0:
            raise ValueError("popularity_weight must be >= 0")
        if self.max_popularity_functions < 0:
            raise ValueError("max_popularity_functions must be >= 0")


# The profile used when no tenant/deployment-specific override is supplied.
# This is the profile that should ship at MVP.
DEFAULT_BOOST_PROFILE = BoostProfile()


def _field_weight(field: str, profile: BoostProfile) -> float | None:
    """Look up the configured weight for a raw field name/spec.

    Accepts plain names ("name"), dotted sub-fields ("tags.raw"), or
    already-boosted specs ("name^2") — only the base field name before any
    "." or "^" is used to decide the weight; unrecognized fields return
    None so callers can leave them untouched (additive, never destructive).
    """
    base = field.split("^", 1)[0].split(".", 1)[0]
    weights = {
        "name": profile.name_weight,
        "description": profile.description_weight,
        "tags": profile.tags_weight,
    }
    return weights.get(base)


def _reweight_field(field: str, profile: BoostProfile) -> str:
    weight = _field_weight(field, profile)
    if weight is None:
        return field
    base = field.split("^", 1)[0]
    # %g-style formatting keeps "5" instead of "5.0" for whole numbers,
    # cosmetic only but keeps generated queries readable in logs/tests.
    return f"{base}^{weight:g}"


def _iter_multi_match_clauses(node: Any) -> Iterator[dict]:
    """Recursively find every ``multi_match`` clause anywhere in a query dict.

    Deliberately structure-agnostic: FE2's base query builder hasn't landed
    in this worktree, so this walks whatever bool/must/should/filter nesting
    it's given rather than assuming one fixed shape. A query with no
    multi_match clause at all yields nothing, and callers treat that as a
    no-op passthrough (see apply_field_boosts) rather than an error — this
    is what keeps the module additive: baseline search must keep working
    even against query shapes this module doesn't recognize.
    """
    if isinstance(node, dict):
        multi_match = node.get("multi_match")
        if isinstance(multi_match, dict):
            yield multi_match
        for value in node.values():
            yield from _iter_multi_match_clauses(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_multi_match_clauses(item)


def apply_field_boosts(
    query: dict[str, Any], profile: BoostProfile = DEFAULT_BOOST_PROFILE
) -> dict[str, Any]:
    """Return a copy of ``query`` with name/description/tags field weights applied.

    - Never mutates the input ``query`` (deep-copies first) — safe to call
      with a dict the caller still holds a reference to / reuses.
    - If ``query`` contains no recognizable ``multi_match`` clause, it is
      returned unchanged (deep-copied). This is the "genuinely additive"
      property: a base query this module doesn't understand still executes
      correctly, just without field weighting.
    - Any field in a ``multi_match.fields`` list that isn't name/description
      /tags (e.g. "owner") is left exactly as-is.
    """
    result = copy.deepcopy(query)
    for clause in _iter_multi_match_clauses(result):
        fields = clause.get("fields")
        if not fields:
            continue
        clause["fields"] = [_reweight_field(f, profile) for f in fields]
    return result
