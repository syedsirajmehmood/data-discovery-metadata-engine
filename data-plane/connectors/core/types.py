"""Core in-process types shared by every connector and the agent runner.

These types serialize directly into the push-contract `entities[]` payload
shape defined in `.claude/team/architecture.md` §2. They do NOT talk to the
ingest API themselves — that's the agent's `push_client`'s job.

ASSUMPTION / NOTE FOR FE1 (flagged because `shared/schema/` had not landed
in this worktree at the time this was written): the exact per-entity-type
field lists live in `.claude/team/spec.md`'s "Metadata schema requirements"
section. That section lists a few "common fields" on every entity
(`id`, `tenant_id`, `data_plane_id`, `source_connection_id`,
`first_seen_at`, `last_scraped_at`, `is_deleted`). Per architecture.md §2,
three of those are catalog-side / server-resolved and therefore are
DELIBERATELY NOT included in the payload emitted here:
  - `tenant_id`  — resolved server-side from the API key, never accepted
    from the request body (architecture.md §2 "Auth").
  - `id`         — the catalog assigns its own global UUID on first upsert;
    the data plane's stable identity for an entity is `urn`, not `id`.
  - `first_seen_at` — "catalog-side, immutable once set" per spec.md;
    nothing the data plane knows determines this.
  - `last_scraped_at` — also catalog-side; the envelope already carries
    `extracted_at` per entity (architecture.md §2 example), which the
    ingest API can use to set/update `last_scraped_at` server-side. We do
    not duplicate it inside `payload`.
  - `is_deleted` — represented structurally via the envelope's
    `operation: "delete"` rather than as a payload boolean, per
    architecture.md §2 ("connectors emit `delete` when discovery no longer
    finds a previously-seen entity").
`data_plane_id` is already a top-level envelope field (once per batch, not
per entity) per architecture.md §2's example, so it is not repeated inside
each entity's `payload`. `source_connection_id` has no envelope-level home,
so each connector includes it inside `payload` (every entity type below).
If FE1's landed `shared/schema/` disagrees with any of this, that schema
wins — this module is written to be easy to adjust at the field-list level
without touching the envelope/transport plumbing.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Iterator, List, Optional


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class EntityType(str, Enum):
    TABLE = "table"
    COLUMN = "column"
    DATASET = "dataset"
    JOB = "job"
    LINEAGE_EDGE = "lineage_edge"


class Operation(str, Enum):
    UPSERT = "upsert"
    DELETE = "delete"


def canonical_json(payload: Dict[str, Any]) -> str:
    """Deterministic JSON serialization used as input to content_hash.

    Sorted keys, no whitespace padding, so the same logical payload always
    hashes the same way regardless of dict insertion order.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(payload: Dict[str, Any]) -> str:
    """`sha256:<hex>` of the canonical payload, per architecture.md §2.

    Lets the control-plane fan-out worker skip re-writing to Neo4j/
    OpenSearch when a re-scrape found no actual change.
    """
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


@dataclass
class HealthStatus:
    ok: bool
    detail: str = ""
    checked_at: datetime = field(default_factory=utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "detail": self.detail, "checked_at": iso(self.checked_at)}


@dataclass
class RawEntity:
    """Connector-internal intermediate representation returned by discover().

    Deliberately loose / source-shaped — this is *not* pushed anywhere.
    `extract_metadata()` turns this into a `NormalizedEntity`.
    """

    entity_type: str
    key: str  # stable within-source identity (connector builds urn from this)
    raw: Dict[str, Any] = field(default_factory=dict)
    # When True, this RawEntity represents an entity discover() previously
    # saw (per the cursor) but did NOT find this cycle — i.e. it was
    # dropped at the source. extract_metadata() must turn this into an
    # operation="delete" NormalizedEntity, not raise.
    tombstone: bool = False


@dataclass
class NormalizedEntity:
    """The in-process type that serializes directly into one element of the
    push-contract's `entities[]` array (architecture.md §2)."""

    urn: str
    entity_type: str
    operation: str
    payload: Dict[str, Any]
    extracted_at: datetime = field(default_factory=utcnow)
    content_hash: str = ""

    def __post_init__(self) -> None:
        if not self.content_hash:
            # Deletes still get a stable hash of their (minimal) payload so
            # the field is never empty on the wire.
            self.content_hash = content_hash(self.payload)

    def to_envelope_dict(self) -> Dict[str, Any]:
        return {
            "urn": self.urn,
            "entity_type": self.entity_type,
            "operation": self.operation,
            "content_hash": self.content_hash,
            "extracted_at": iso(self.extracted_at),
            "payload": self.payload,
        }

    @classmethod
    def from_envelope_dict(cls, d: Dict[str, Any]) -> "NormalizedEntity":
        """Inverse of `to_envelope_dict()`. Used only by the agent's
        dead-letter queue to reconstruct a `NormalizedEntity` (and thus a
        `Batch`) from what was persisted to local disk, so a retried push
        reuses the exact same `content_hash`/`extracted_at` rather than
        recomputing them."""
        extracted_at = d.get("extracted_at")
        parsed_at = (
            datetime.fromisoformat(extracted_at.replace("Z", "+00:00"))
            if isinstance(extracted_at, str)
            else utcnow()
        )
        return cls(
            urn=d["urn"],
            entity_type=d["entity_type"],
            operation=d["operation"],
            payload=d.get("payload", {}),
            extracted_at=parsed_at,
            content_hash=d.get("content_hash", ""),
        )


@dataclass
class LineageEdge:
    """Connector-produced lineage fact. `extract_lineage()` yields these;
    the agent turns each into a `NormalizedEntity` with
    `entity_type="lineage_edge"` via `to_normalized_entity()` before handing
    it to the batcher — connectors never build the envelope shape by hand.
    """

    upstream_urn: str
    upstream_entity_type: str
    downstream_urn: str
    downstream_entity_type: str
    edge_granularity: str = "table_level"  # "table_level" | "column_level"
    producer_job_urn: Optional[str] = None
    confidence: str = "inferred"  # "inferred" | "manually_asserted" | "job_declared"
    discovered_at: datetime = field(default_factory=utcnow)
    source_connection_id: Optional[str] = None
    operation: str = Operation.UPSERT.value

    def urn(self) -> str:
        return f"urn:lineage:{self.upstream_urn}->{self.downstream_urn}"

    def to_normalized_entity(self) -> NormalizedEntity:
        payload = {
            "upstream_urn": self.upstream_urn,
            "upstream_entity_type": self.upstream_entity_type,
            "downstream_urn": self.downstream_urn,
            "downstream_entity_type": self.downstream_entity_type,
            "edge_granularity": self.edge_granularity,
            "producer_job_urn": self.producer_job_urn,
            "confidence": self.confidence,
            "discovered_at": iso(self.discovered_at),
            "source_connection_id": self.source_connection_id,
        }
        return NormalizedEntity(
            urn=self.urn(),
            entity_type=EntityType.LINEAGE_EDGE.value,
            operation=self.operation,
            payload=payload,
            extracted_at=self.discovered_at,
        )


@dataclass
class CursorEntry:
    """Per-entity bookkeeping the connector keeps between scrape cycles."""

    urn: str
    entity_type: str
    last_scraped_at: str  # ISO timestamp, string for trivial JSON round-trip
    content_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "urn": self.urn,
            "entity_type": self.entity_type,
            "last_scraped_at": self.last_scraped_at,
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CursorEntry":
        return cls(
            urn=d["urn"],
            entity_type=d["entity_type"],
            last_scraped_at=d["last_scraped_at"],
            content_hash=d.get("content_hash", ""),
        )


@dataclass
class Cursor:
    """Incremental-scrape state for one source connection.

    Persisted to local disk between agent scrape cycles (see
    `agent/cursor_store.py`) — this is data-plane-local state, never sent
    to the control plane.
    """

    source_connection_id: str
    entries: Dict[str, CursorEntry] = field(default_factory=dict)  # urn -> entry
    updated_at: Optional[str] = None

    def known_urns(self) -> Iterator[str]:
        return iter(self.entries.keys())

    def record(self, urn: str, entity_type: str, content_hash_: str, when: Optional[datetime] = None) -> None:
        self.entries[urn] = CursorEntry(
            urn=urn,
            entity_type=entity_type,
            last_scraped_at=iso(when or utcnow()) or "",
            content_hash=content_hash_,
        )

    def forget(self, urn: str) -> None:
        self.entries.pop(urn, None)

    def unchanged(self, urn: str, content_hash_: str) -> bool:
        entry = self.entries.get(urn)
        return entry is not None and entry.content_hash == content_hash_

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_connection_id": self.source_connection_id,
            "updated_at": self.updated_at,
            "entries": {urn: e.to_dict() for urn, e in self.entries.items()},
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Cursor":
        return cls(
            source_connection_id=d["source_connection_id"],
            updated_at=d.get("updated_at"),
            entries={urn: CursorEntry.from_dict(e) for urn, e in d.get("entries", {}).items()},
        )

    @classmethod
    def empty(cls, source_connection_id: str) -> "Cursor":
        return cls(source_connection_id=source_connection_id)


def diff_deleted_urns(cursor: Cursor, current_urns: List[str], entity_type: Optional[str] = None) -> List[str]:
    """Shared schema-drift helper used by every connector.

    Given the previous cursor and the set of urns seen in *this* discovery
    cycle, returns urns the cursor previously knew about but that vanished
    this cycle — i.e. dropped tables/columns/objects. If `entity_type` is
    given, only considers cursor entries of that type (so a Postgres
    connector can diff tables and columns independently).
    """
    current = set(current_urns)
    deleted: List[str] = []
    for urn, entry in cursor.entries.items():
        if entity_type is not None and entry.entity_type != entity_type:
            continue
        if urn not in current:
            deleted.append(urn)
    return deleted
