"""In-memory fake implementations of the storage interfaces
(interfaces.py), used ONLY by FE1's own tests so the ingest -> fan-out path
can be proven end-to-end without a real Postgres/Neo4j/OpenSearch/
ClickHouse running. These are NOT the production storage clients - FE2
owns those under `control-plane/storage/`. Keep these deliberately simple;
they exist to satisfy the Protocols in interfaces.py structurally so
worker.py's tests are self-contained.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Dict, List

from workers.fanout.interfaces import (
    AnalyticsEvent,
    CatalogEntity,
    UpsertResult,
)


class InMemoryRelationalStore:
    """Fake for RelationalStore. Tracks entities by urn, and is the one
    fake that actually implements the content_hash no-op check, mirroring
    the real Postgres store's role as system of record (see interfaces.py's
    UpsertResult docstring)."""

    def __init__(self) -> None:
        self.entities_by_urn: Dict[str, CatalogEntity] = {}
        self.upsert_calls: List[CatalogEntity] = []

    def upsert_entity(self, entity: CatalogEntity) -> UpsertResult:
        self.upsert_calls.append(entity)
        previous = self.entities_by_urn.get(entity.urn)
        changed = (
            previous is None
            or previous.content_hash != entity.content_hash
            or previous.is_deleted != entity.is_deleted
        )
        stored = entity
        if previous is not None:
            # `id` and `first_seen_at` are catalog-side/immutable once
            # assigned (spec.md: "first_seen_at (catalog-side, immutable
            # once set)"; "id (UUID, globally unique)"). The ingest layer
            # only ever sends a *candidate* id/first_seen_at for a urn it
            # hasn't necessarily seen before (see
            # control-plane/api/ingest/service.py) - the relational store
            # (system of record) is the authority on whether this urn
            # already exists, and if so keeps the original id/first_seen_at
            # rather than the incoming candidate values.
            stored = replace(entity, id=previous.id, first_seen_at=previous.first_seen_at)
        self.entities_by_urn[entity.urn] = stored
        return UpsertResult(changed=changed, stored_id=stored.id)

    def get(self, urn: str) -> CatalogEntity:
        return self.entities_by_urn[urn]


class InMemoryGraphStore:
    """Fake for GraphStore. Just records what it was asked to upsert -
    real node/edge modeling is FE2's job."""

    def __init__(self) -> None:
        self.upserted: List[CatalogEntity] = []

    def upsert_entity(self, entity: CatalogEntity) -> None:
        self.upserted.append(entity)

    def urns(self) -> List[str]:
        return [e.urn for e in self.upserted]


class InMemorySearchIndex:
    """Fake for SearchIndex. Keeps the latest indexed document per urn."""

    def __init__(self) -> None:
        self.documents_by_urn: Dict[str, CatalogEntity] = {}
        self.index_calls: List[CatalogEntity] = []

    def index_entity(self, entity: CatalogEntity) -> None:
        self.index_calls.append(entity)
        self.documents_by_urn[entity.urn] = entity


class InMemoryAnalyticsStore:
    """Fake for AnalyticsStore. Append-only, like the real ClickHouse
    table it stands in for."""

    def __init__(self) -> None:
        self.events: List[AnalyticsEvent] = []

    def record_event(self, event: AnalyticsEvent) -> None:
        self.events.append(event)
