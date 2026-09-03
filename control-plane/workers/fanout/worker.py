"""Fan-out orchestration: takes a batch of already-validated
`ValidatedEntity` objects and calls out to the storage-client interfaces
(interfaces.py). This module owns ORCHESTRATION ONLY - it never talks to
Postgres/Neo4j/OpenSearch/ClickHouse directly (architecture.md §8: FE1
owns `control-plane/workers/fanout/` "orchestration logic only, not
storage clients"; FE1 never edits files under `storage/`).

Routing table (architecture.md §4 + spec.md's entity list):

  entity_type    RelationalStore   GraphStore   SearchIndex   AnalyticsStore
  -----------    ---------------   ----------   -----------   --------------
  table          yes               yes          yes           audit event
  column         yes               yes          yes           audit event
  dataset        yes               yes*         yes           audit event
  job            yes               yes          yes           audit event
  lineage_edge   yes               yes          no            audit event
  scrape_run     no                no           no            record_event()

  * Dataset -> GraphStore is a deliberate small extension beyond
    architecture.md §4's literal Neo4j node list (`(:Table)`, `(:Column)`,
    `(:Job)`, `(:Dashboard)` - Dataset isn't named there). It's included
    because spec.md's Lineage Edge schema allows `upstream_entity_type`/
    `downstream_entity_type` = 'dataset', so an S3 dataset must be able to
    exist as a graph node to be an edge endpoint - otherwise a lineage
    edge referencing a dataset would point at nothing. FE2 independently
    made the same call (storage/graph/store.py adds a `(:Dataset)` label).

`scrape_run` is routed only to AnalyticsStore, per spec.md: "Scrape Run...
not itself catalog content" - it doesn't go through the entity system of
record at all, matching architecture.md §4's ClickHouse `scrape_events`
table being where scrape history lives. It also isn't a member of
`storage.types.EntityType`, so it's handled before any `EntityRecord` is
constructed, not as a 7th enum value.

Content-hash no-op optimization (architecture.md §2): RelationalStore is
always called first (it's the system of record and the only store that can
tell us whether anything actually changed - see storage.types.UpsertResult).
If it reports `skipped=True`, GraphStore/SearchIndex are skipped for that
entity - "cheap no-op detection", per architecture.md §2. Deletes always
count as changed regardless of what the store reports (tombstones must
always propagate), enforced defensively here rather than trusted entirely
to the store's `skipped` flag.

Synchronous-call simplification (documented, not silent): architecture.md
§7.3's sequence diagram shows the ingest API returning "202 Accepted" while
fan-out (Postgres/Neo4j/OpenSearch/ClickHouse writes) proceeds - in a real
deployment this is decoupled via a task queue so the HTTP response doesn't
block on 4 downstream writes. Standing up that queue infrastructure is out
of scope for this task (no queue library was assigned to FE1, and
architecture.md §8 doesn't call for one). `FanoutWorker.process_batch()` is
therefore synchronous: the ingest API in this repo calls it in-process
after responding 202 is prepared. This keeps the orchestration logic itself
correct and fully testable now; swapping in an actual queue later is a
call-site change in `control-plane/api/ingest/service.py`, not a change to
this module's routing logic.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import List

from storage.types import EntityRecord, EntityType, Operation, ScrapeEvent
from workers.fanout.interfaces import (
    AnalyticsStore,
    GraphStore,
    RelationalStore,
    SearchIndex,
    ValidatedEntity,
)

GRAPH_ENTITY_TYPES = frozenset({"table", "column", "dataset", "job", "lineage_edge"})
SEARCH_ENTITY_TYPES = frozenset({"table", "column", "dataset", "job"})
RELATIONAL_ENTITY_TYPES = frozenset({"table", "column", "dataset", "job", "lineage_edge"})
ANALYTICS_ONLY_ENTITY_TYPES = frozenset({"scrape_run"})


def _parse_iso8601(value: str) -> datetime:
    # storage.types uses stdlib datetime; the push envelope (architecture.md
    # §2) uses "Z"-suffixed ISO 8601, which datetime.fromisoformat only
    # accepts as "+00:00" on this project's minimum Python version (3.9).
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True)
class EntityFanoutOutcome:
    urn: str
    entity_type: str
    wrote_relational: bool
    wrote_graph: bool
    wrote_search: bool
    wrote_analytics: bool
    skipped_as_unchanged: bool


@dataclass(frozen=True)
class FanoutResult:
    batch_id: str
    outcomes: List[EntityFanoutOutcome]

    @property
    def processed_count(self) -> int:
        return len(self.outcomes)


class FanoutWorker:
    """Orchestrates one validated, accepted batch of entities across the
    four storage interfaces. Holds no storage-specific logic itself -
    every store it talks to is injected, so tests can pass the in-memory
    fakes (fakes.py) and production wiring can pass FE2's real clients
    without this class changing."""

    def __init__(
        self,
        relational_store: RelationalStore,
        graph_store: GraphStore,
        search_index: SearchIndex,
        analytics_store: AnalyticsStore,
        *,
        connector_type: str,
    ) -> None:
        self._relational = relational_store
        self._graph = graph_store
        self._search = search_index
        self._analytics = analytics_store
        self._connector_type = connector_type

    def process_batch(self, batch_id: str, entities: List[ValidatedEntity]) -> FanoutResult:
        outcomes = [self._process_one(entity) for entity in entities]
        return FanoutResult(batch_id=batch_id, outcomes=outcomes)

    def _to_entity_record(self, entity: ValidatedEntity) -> EntityRecord:
        return EntityRecord(
            tenant_id=entity.tenant_id,
            urn=entity.urn,
            entity_type=EntityType(entity.entity_type),
            data_plane_id=entity.data_plane_id,
            source_connection_id=entity.source_connection_id or "",
            payload=entity.payload,
            operation=Operation(entity.operation),
            content_hash=entity.content_hash,
            extracted_at=_parse_iso8601(entity.extracted_at),
        )

    def _process_one(self, entity: ValidatedEntity) -> EntityFanoutOutcome:
        if entity.entity_type in ANALYTICS_ONLY_ENTITY_TYPES:
            self._record_scrape_event(entity, event_type="scrape_run")
            return EntityFanoutOutcome(
                urn=entity.urn,
                entity_type=entity.entity_type,
                wrote_relational=False,
                wrote_graph=False,
                wrote_search=False,
                wrote_analytics=True,
                skipped_as_unchanged=False,
            )

        record = self._to_entity_record(entity)

        wrote_relational = False
        changed = True
        if entity.entity_type in RELATIONAL_ENTITY_TYPES:
            result = self._relational.upsert_entity(record)
            wrote_relational = True
            changed = (not result.skipped) or entity.operation == "delete"

        wrote_graph = False
        wrote_search = False
        if changed:
            if entity.entity_type in GRAPH_ENTITY_TYPES:
                self._graph.upsert_entity(record)
                wrote_graph = True
            if entity.entity_type in SEARCH_ENTITY_TYPES:
                self._search.index_entity(record)
                wrote_search = True

        event_type = "entity_deleted" if entity.operation == "delete" else (
            "entity_upserted" if changed else "entity_unchanged"
        )
        self._record_scrape_event(entity, event_type=event_type)

        return EntityFanoutOutcome(
            urn=entity.urn,
            entity_type=entity.entity_type,
            wrote_relational=wrote_relational,
            wrote_graph=wrote_graph,
            wrote_search=wrote_search,
            wrote_analytics=True,
            skipped_as_unchanged=not changed,
        )

    def _record_scrape_event(self, entity: ValidatedEntity, *, event_type: str) -> None:
        self._analytics.record_event(
            ScrapeEvent(
                tenant_id=entity.tenant_id,
                data_plane_id=entity.data_plane_id,
                connector_type=self._connector_type,
                urn=entity.urn,
                event_type=event_type,
                occurred_at=_parse_iso8601(entity.extracted_at),
                detail=json.dumps({"entity_type": entity.entity_type, "operation": entity.operation}),
            )
        )
