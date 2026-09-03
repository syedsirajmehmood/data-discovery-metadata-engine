"""Storage-client interfaces: the agreed seam between FE1's fan-out
orchestration (this package) and FE2's concrete storage clients
(`control-plane/storage/`), per architecture.md §8:

    "FE2's storage-client interfaces (`GraphStore.upsert_entity()`,
    `SearchIndex.index_entity()`, `AnalyticsStore.record_event()`,
    `RelationalStore.upsert_entity()`) are the seam the fan-out worker
    calls - FE1 codes against those method signatures (agreed upfront,
    stubbed by FE2 on day one) so both can build in parallel without
    waiting on each other's full implementation."

IMPORTANT — location note for FE2: this module lives at
`control-plane/workers/fanout/interfaces.py`, inside FE1's owned tree, NOT
under `control-plane/storage/` — FE1's task explicitly excludes touching
`control-plane/storage/` (that's FE2's directory). FE2's concrete classes
(e.g. `control-plane/storage/relational/postgres_store.py`) should live
under `control-plane/storage/` as usual and simply implement (structurally
satisfy - these are `typing.Protocol`s, so no inheritance is required, just
matching method signatures) the Protocols defined here. Import them from
`workers.fanout.interfaces` rather than duplicating the shape.

Only 4 methods are the fixed seam (per architecture.md §8) - one per store.
Each store is asked to do exactly one thing for the fan-out worker:

    RelationalStore.upsert_entity()  -> Postgres, the system of record
    GraphStore.upsert_entity()       -> Neo4j, lineage/relationship projection
    SearchIndex.index_entity()       -> OpenSearch, full-text projection
    AnalyticsStore.record_event()    -> ClickHouse, append-only audit/scrape trail

Everything else in this module (CatalogEntity, UpsertResult, AnalyticsEvent)
is data-shape scaffolding around those 4 calls, owned by FE1 since it's
part of the orchestration contract, not the storage clients themselves.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

try:
    from typing import Protocol, runtime_checkable
except ImportError:  # pragma: no cover - py<3.8 fallback, not expected here
    from typing_extensions import Protocol, runtime_checkable  # type: ignore


# ---------------------------------------------------------------------------
# Data shapes passed across the seam
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CatalogEntity:
    """The fully-resolved representation of one push-contract entity, after
    auth + shared/schema validation + idempotency, and before storage
    fan-out. This is what every storage-interface method below receives.

    Built by merging (see control-plane/api/ingest/service.py):
      - the envelope's per-entity fields: urn, entity_type, operation,
        content_hash, extracted_at (architecture.md §2)
      - server-resolved common fields: id, tenant_id, data_plane_id,
        first_seen_at, last_scraped_at, is_deleted (never trusted from the
        push payload - see shared/schema/README.md)
      - the connector-supplied payload: entity-type-specific fields plus
        source_connection_id, already validated against
        shared/schema/<entity_type>.schema.json

    Note: `scrape_run` entities are the one exception that never reaches
    RelationalStore/GraphStore/SearchIndex - see worker.py's routing table.
    They carry `tenant_id`/`data_plane_id` inside `payload` itself (per
    scrape_run.schema.json, which is not wrapped by common.schema.json), so
    for that entity_type this dataclass's top-level tenant_id/data_plane_id
    are still populated the same server-resolved way for consistency, and
    `payload` additionally carries the scrape_run-specific fields.
    """

    id: str
    """A CANDIDATE id (freshly generated per push by
    control-plane/api/ingest/service.py). RelationalStore is the system of
    record and the sole authority on whether `urn` already exists; if it
    does, RelationalStore.upsert_entity() must keep the pre-existing id
    (and first_seen_at) rather than this candidate, and return the
    authoritative value as UpsertResult.stored_id. The ingest layer has no
    way to know in advance whether a urn is new, since it doesn't query
    storage directly (architecture.md §8: FE1 never touches storage/)."""
    urn: str
    entity_type: str  # 'table' | 'column' | 'dataset' | 'job' | 'lineage_edge' | 'scrape_run'
    tenant_id: str
    data_plane_id: str
    source_connection_id: Optional[str]
    operation: str  # 'upsert' | 'delete'
    is_deleted: bool
    content_hash: Optional[str]
    extracted_at: str  # ISO 8601 timestamp
    first_seen_at: str  # ISO 8601 timestamp
    last_scraped_at: str  # ISO 8601 timestamp
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class UpsertResult:
    """Returned by RelationalStore.upsert_entity() (and reused as the
    return shape for GraphStore.upsert_entity() where a caller cares).

    `changed` is what makes the content_hash no-op optimization in
    architecture.md §2 possible without a 5th method: RelationalStore is
    the system of record, so it's the one store positioned to know whether
    this write actually changed anything (new entity, or content_hash
    differs from what's stored) versus a re-scrape that observed no
    change. The fan-out worker uses `changed` to decide whether to bother
    calling GraphStore/SearchIndex at all for this entity.
    """

    changed: bool
    stored_id: str


@dataclass(frozen=True)
class AnalyticsEvent:
    """One row for ClickHouse's append-only `scrape_events`-shaped table
    (architecture.md §4: `scrape_events(tenant_id, data_plane_id,
    connector_type, urn, event_type, occurred_at, detail)`)."""

    tenant_id: str
    data_plane_id: str
    connector_type: str
    urn: str
    event_type: str  # e.g. 'entity_upserted', 'entity_deleted', 'entity_unchanged', 'scrape_run'
    occurred_at: str  # ISO 8601 timestamp
    detail: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# The seam itself - 4 Protocols, structural typing (no inheritance required)
# ---------------------------------------------------------------------------


@runtime_checkable
class RelationalStore(Protocol):
    """Postgres: system of record for entities (architecture.md §4)."""

    def upsert_entity(self, entity: CatalogEntity) -> UpsertResult: ...


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

    def upsert_entity(self, entity: CatalogEntity) -> None: ...


@runtime_checkable
class SearchIndex(Protocol):
    """OpenSearch: full-text catalog search projection (architecture.md §4)."""

    def index_entity(self, entity: CatalogEntity) -> None: ...


@runtime_checkable
class AnalyticsStore(Protocol):
    """ClickHouse: append-only scrape/audit/usage event trail (architecture.md §4)."""

    def record_event(self, event: AnalyticsEvent) -> None: ...
