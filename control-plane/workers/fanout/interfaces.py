"""Storage-client interfaces: the agreed seam between FE1's fan-out
orchestration (this package) and FE2's concrete storage clients
(`control-plane/storage/`), per architecture.md §8.

Reconciliation note (2026-09-03, orchestrator): FE1 and FE2 built in
parallel worktrees against the same *names* (`RelationalStore.upsert_entity()`
etc.) but different *types* - FE1 originally defined its own `CatalogEntity`/
`UpsertResult`/`AnalyticsEvent` here, while FE2's actual stores
(`control-plane/storage/*/store.py`) are built against
`control-plane/storage/types.py`'s `EntityRecord`/`UpsertResult`/
`ScrapeEvent`/`UsageEvent`. Since FE2's types are the ones with real
Postgres/Neo4j/OpenSearch/ClickHouse implementations behind them, this
module now imports and matches FE2's types exactly rather than defining
parallel ones. See `.claude/team/status.md` (2026-09-03 entry) for the full
story.

Only 4 methods are the fixed seam (per architecture.md §8) - one per store.
Each store is asked to do exactly one thing for the fan-out worker:

    RelationalStore.upsert_entity()  -> Postgres, the system of record
    GraphStore.upsert_entity()       -> Neo4j, lineage/relationship projection
    SearchIndex.index_entity()       -> OpenSearch, full-text projection
    AnalyticsStore.record_event()    -> ClickHouse, append-only audit/scrape trail
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Union

try:
    from typing import Protocol, runtime_checkable
except ImportError:  # pragma: no cover - py<3.8 fallback, not expected here
    from typing_extensions import Protocol, runtime_checkable  # type: ignore

from storage.types import EntityRecord, ScrapeEvent, UpsertResult, UsageEvent

__all__ = [
    "ValidatedEntity",
    "EntityRecord",
    "UpsertResult",
    "ScrapeEvent",
    "UsageEvent",
    "RelationalStore",
    "GraphStore",
    "SearchIndex",
    "AnalyticsStore",
]


@dataclass(frozen=True)
class ValidatedEntity:
    """One push-contract entity after auth + shared/schema validation +
    idempotency, and before storage fan-out. This is what
    `control-plane/api/ingest/service.py` hands to
    `FanoutWorker.process_batch()`.

    Deliberately raw/untyped (`entity_type`/`operation` as plain strings,
    `extracted_at` as an ISO 8601 string) - the worker, not the ingest
    layer, decides how each entity_type maps onto FE2's storage types
    (`storage.types.EntityRecord` for catalog entities,
    `storage.types.ScrapeEvent` for `scrape_run`, which isn't a member of
    `storage.types.EntityType` at all), since that mapping is inseparable
    from the routing table `worker.py` already owns.

    Notably does NOT carry `id`, `first_seen_at`, or `last_scraped_at` -
    unlike the original `CatalogEntity` this replaces, FE2's `EntityRecord`
    has no such fields. FE2's `RelationalStore` (the system of record)
    manages entity identity and first-seen tracking internally; the ingest
    layer has no way to know in advance whether a `urn` is new (architecture.md
    §8: FE1 never touches storage/), so it doesn't try to.
    """

    urn: str
    entity_type: str  # 'table' | 'column' | 'dataset' | 'job' | 'lineage_edge' | 'scrape_run' | ...
    tenant_id: str
    data_plane_id: str
    source_connection_id: Optional[str]
    operation: str  # 'upsert' | 'delete'
    content_hash: Optional[str]
    extracted_at: str  # ISO 8601 timestamp
    payload: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# The seam itself - 4 Protocols, structural typing (no inheritance required),
# matching control-plane/storage/*/store.py's actual signatures exactly.
# ---------------------------------------------------------------------------


@runtime_checkable
class RelationalStore(Protocol):
    """Postgres: system of record for entities (architecture.md §4)."""

    def upsert_entity(self, record: EntityRecord) -> UpsertResult: ...


@runtime_checkable
class GraphStore(Protocol):
    """Neo4j: lineage/entity-relationship projection (architecture.md §4).

    Implementations decide internally whether a given entity_type becomes
    a node, an edge, or both (e.g. a `lineage_edge` entity becomes a
    `[:DERIVES_FROM]`-style relationship between two existing nodes; a
    `column` entity becomes both a `(:Column)` node and a `[:HAS_COLUMN]`
    edge from its parent table) - that mapping is FE2's implementation
    detail, not something the fan-out worker needs to know. See worker.py
    for which entity_types the orchestration routes here at all.
    """

    def upsert_entity(self, record: EntityRecord) -> UpsertResult: ...


@runtime_checkable
class SearchIndex(Protocol):
    """OpenSearch: full-text catalog search projection (architecture.md §4)."""

    def index_entity(self, record: EntityRecord) -> UpsertResult: ...


@runtime_checkable
class AnalyticsStore(Protocol):
    """ClickHouse: append-only scrape/audit/usage event trail (architecture.md §4)."""

    def record_event(self, event: Union[ScrapeEvent, UsageEvent]) -> None: ...
