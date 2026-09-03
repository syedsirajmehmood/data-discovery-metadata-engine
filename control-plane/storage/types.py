"""Common types shared by all four storage clients.

This module is the seam FE1's fan-out worker (``control-plane/workers/fanout/``)
codes against. It mirrors the push-contract envelope defined in
architecture.md §2 (one ``EntityRecord`` per entity in a batch's
``entities[]`` array, after the ingest API has authenticated the request and
resolved ``tenant_id`` server-side from the API key — see architecture.md §6.
No field here is ever populated from a client-supplied tenant id).

Entity-type-specific field lists live in ``payload`` as a plain dict, per
spec.md's "Metadata schema requirements" section (Table, Column, Dataset,
Job/DAG, Lineage Edge). FE1 owns the canonical JSON Schema definitions under
``shared/schema/`` once that lands; until then, each store's ``store.py``
documents exactly which ``payload`` keys it reads for each ``entity_type``,
taken directly from spec.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class EntityType(str, Enum):
    TABLE = "table"
    COLUMN = "column"
    DATASET = "dataset"
    JOB = "job"
    DASHBOARD = "dashboard"
    LINEAGE_EDGE = "lineage_edge"


class Operation(str, Enum):
    UPSERT = "upsert"
    DELETE = "delete"


@dataclass(frozen=True)
class EntityRecord:
    """One normalized entity, tenant-scoped, ready to be written to a store.

    Fields map 1:1 onto architecture.md §2's per-entity push shape
    (``urn``, ``entity_type``, ``operation``, ``content_hash``,
    ``extracted_at``, ``payload``) plus the containment hierarchy from
    spec.md's NFR-2 (``tenant → data_plane → source_connection → entity``),
    which the ingest API/fan-out worker resolves server-side before calling
    into any store here — no store ever trusts a client-supplied tenant_id.
    """

    tenant_id: str
    urn: str
    entity_type: EntityType
    data_plane_id: str
    source_connection_id: str
    payload: dict[str, Any]
    operation: Operation = Operation.UPSERT
    content_hash: Optional[str] = None
    extracted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_delete(self) -> bool:
        return self.operation == Operation.DELETE


@dataclass(frozen=True)
class UpsertResult:
    """Return shape for every store's write method — lets the fan-out worker
    do cheap no-op detection / metrics without each store re-implementing it.
    """

    urn: str
    created: bool  # True if this was the first time this urn was seen
    skipped: bool = False  # True if content_hash matched and no write happened
    tombstoned: bool = False


@dataclass(frozen=True)
class ScrapeEvent:
    """Maps to ClickHouse ``scrape_events`` (architecture.md §4)."""

    tenant_id: str
    data_plane_id: str
    connector_type: str
    urn: str
    event_type: str  # e.g. "entity_upserted", "entity_tombstoned", "scrape_run_completed"
    occurred_at: datetime
    detail: str = ""


@dataclass(frozen=True)
class UsageEvent:
    """Maps to ClickHouse ``usage_events`` (architecture.md §4)."""

    tenant_id: str
    urn: str
    actor: str
    action: str  # e.g. "view", "search_click"
    occurred_at: datetime
