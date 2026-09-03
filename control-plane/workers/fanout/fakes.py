"""In-memory fake implementations of the storage interfaces
(interfaces.py), used ONLY by FE1's own tests so the ingest -> fan-out path
can be proven end-to-end without a real Postgres/Neo4j/OpenSearch/
ClickHouse running. These are NOT the production storage clients - FE2
owns those under `control-plane/storage/`. Keep these deliberately simple;
they exist to satisfy the Protocols in interfaces.py structurally so
worker.py's tests are self-contained.

Reconciliation note (2026-09-03, orchestrator): rewritten to match FE2's
actual `storage.types.EntityRecord`/`UpsertResult` shape - see
interfaces.py's module docstring.
"""
from __future__ import annotations

from typing import Dict, List, Union

from storage.types import EntityRecord, ScrapeEvent, UpsertResult, UsageEvent


class InMemoryRelationalStore:
    """Fake for RelationalStore. Tracks entities by urn, and is the one
    fake that actually implements the content_hash no-op check, mirroring
    the real Postgres store's role as system of record."""

    def __init__(self) -> None:
        self.records_by_urn: Dict[str, EntityRecord] = {}
        self.upsert_calls: List[EntityRecord] = []

    def upsert_entity(self, record: EntityRecord) -> UpsertResult:
        self.upsert_calls.append(record)
        previous = self.records_by_urn.get(record.urn)
        created = previous is None
        skipped = (
            previous is not None
            and not record.is_delete
            and previous.content_hash == record.content_hash
        )
        self.records_by_urn[record.urn] = record
        return UpsertResult(urn=record.urn, created=created, skipped=skipped, tombstoned=record.is_delete)

    def get(self, urn: str) -> EntityRecord:
        return self.records_by_urn[urn]


class InMemoryGraphStore:
    """Fake for GraphStore. Just records what it was asked to upsert -
    real node/edge modeling is FE2's job."""

    def __init__(self) -> None:
        self.upserted: List[EntityRecord] = []

    def upsert_entity(self, record: EntityRecord) -> UpsertResult:
        self.upserted.append(record)
        return UpsertResult(urn=record.urn, created=True)

    def urns(self) -> List[str]:
        return [r.urn for r in self.upserted]


class InMemorySearchIndex:
    """Fake for SearchIndex. Keeps the latest indexed document per urn."""

    def __init__(self) -> None:
        self.documents_by_urn: Dict[str, EntityRecord] = {}
        self.index_calls: List[EntityRecord] = []

    def index_entity(self, record: EntityRecord) -> UpsertResult:
        self.index_calls.append(record)
        self.documents_by_urn[record.urn] = record
        return UpsertResult(urn=record.urn, created=True)


class InMemoryAnalyticsStore:
    """Fake for AnalyticsStore. Append-only, like the real ClickHouse
    table it stands in for."""

    def __init__(self) -> None:
        self.events: List[Union[ScrapeEvent, UsageEvent]] = []

    def record_event(self, event: Union[ScrapeEvent, UsageEvent]) -> None:
        self.events.append(event)
