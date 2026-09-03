"""``GraphStore`` — Neo4j 5.x client for the lineage/relationship graph.

Model, per architecture.md §4: ``(:Table)``, ``(:Column)``, ``(:Job)``,
``(:Dashboard)`` nodes; ``[:HAS_COLUMN]``, ``[:PRODUCES]``, ``[:CONSUMES]``,
``[:DERIVES_FROM]``, ``[:OWNED_BY]`` edges, every node/edge carrying
``tenant_id``.

**Documented extension beyond architecture.md's literal node list**: a
``(:Dataset)`` label is added for S3-sourced entities. spec.md's metadata
schema treats Table and Dataset as peer entity types (AC-8: "cross-source
result parity" — Postgres tables and S3 datasets must be interchangeable
catalog citizens), and lineage edges can reference either
(``upstream_entity_type``/``downstream_entity_type`` include ``dataset``).
Modeling Dataset as its own label keeps that parity in the graph instead of
forcing S3 datasets into ``:Table``, and needed zero changes to the edge
types architecture.md already defined.

**Field-naming resolution**: spec.md's Lineage Edge fields are named
``upstream_entity_id`` / ``downstream_entity_id``. This store's
``lineage_edge`` payload expects ``upstream_urn`` / ``downstream_urn``
instead (see ``EntityRecord`` docstring in ``storage/types.py``) — URN is
the only identity that's stable and known *before* control-plane ingest
(internal Postgres UUIDs don't exist yet when a connector emits a lineage
edge), and every other identity concept in architecture.md (push-contract
idempotency §2, upsert keys) is already URN-based. Treat "entity_id" in
spec.md as "the entity's URN" for this field.

Identity key for every node: ``(tenant_id, urn)`` (mirrors the Postgres
``UNIQUE (tenant_id, urn)`` constraint in ``storage/relational/models.py``),
so `GraphStore` and `RelationalStore` agree on what "the same entity" means.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Optional

from neo4j import Driver, GraphDatabase, Transaction

from storage.types import EntityRecord, EntityType, UpsertResult

_NODE_LABELS = {
    "table": "Table",
    "column": "Column",
    "dataset": "Dataset",
    "job": "Job",
    "dashboard": "Dashboard",
}
_ENTITY_TYPE_BY_LABEL = {v: k for k, v in _NODE_LABELS.items()}

_MAX_HOPS_CEILING = 15  # defense in depth; API layer clamps its own default lower


class UnknownEntityTypeError(ValueError):
    pass


def build_uri() -> str:
    return os.environ.get("NEO4J_URI", "bolt://localhost:7687")


class GraphStore:
    def __init__(
        self,
        driver: Optional[Driver] = None,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: str = "neo4j",
    ) -> None:
        self._owns_driver = driver is None
        if driver is not None:
            self._driver = driver
        else:
            self._driver = GraphDatabase.driver(
                uri or build_uri(),
                auth=(
                    user or os.environ.get("NEO4J_USER", "neo4j"),
                    password or os.environ.get("NEO4J_PASSWORD", "neo4jpassword"),
                ),
            )
        self._database = database

    def close(self) -> None:
        if self._owns_driver:
            self._driver.close()

    def ensure_constraints(self) -> None:
        """Idempotent uniqueness constraints — safe to call on every startup."""
        with self._driver.session(database=self._database) as session:
            for label in _NODE_LABELS.values():
                session.run(
                    f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) "
                    "REQUIRE (n.tenant_id, n.urn) IS UNIQUE"
                )
            session.run(
                "CREATE CONSTRAINT IF NOT EXISTS FOR (o:Owner) "
                "REQUIRE (o.tenant_id, o.name) IS UNIQUE"
            )

    # ------------------------------------------------------------------
    # The seam: upsert_entity
    # ------------------------------------------------------------------

    def upsert_entity(self, record: EntityRecord) -> UpsertResult:
        entity_type = record.entity_type.value if isinstance(record.entity_type, EntityType) else record.entity_type

        if entity_type == "lineage_edge":
            return self._upsert_lineage_edge(record)

        label = _NODE_LABELS.get(entity_type)
        if label is None:
            raise UnknownEntityTypeError(f"GraphStore has no node label for entity_type={entity_type!r}")

        with self._driver.session(database=self._database) as session:
            created = session.execute_write(self._merge_node_tx, label, record)

            if not record.is_delete:
                if entity_type == "column":
                    table_urn = record.payload.get("table_urn")
                    if table_urn:
                        session.execute_write(
                            self._link_tx, "Table", table_urn, "Column", record.urn, record.tenant_id, "HAS_COLUMN"
                        )
                owner = record.payload.get("owner")
                if owner:
                    session.execute_write(self._link_owner_tx, label, record.urn, record.tenant_id, owner)

        return UpsertResult(urn=record.urn, created=created, tombstoned=record.is_delete)

    @staticmethod
    def _merge_node_tx(tx: Transaction, label: str, record: EntityRecord) -> bool:
        props = _sanitize_props(record.payload)
        query = (
            f"MERGE (n:{label} {{tenant_id: $tenant_id, urn: $urn}}) "
            "ON CREATE SET n.first_seen_at = $extracted_at "
            "SET n += $props, n.last_scraped_at = $extracted_at, n.is_deleted = $is_deleted, "
            "n.data_plane_id = $data_plane_id, n.source_connection_id = $source_connection_id"
        )
        summary = tx.run(
            query,
            tenant_id=record.tenant_id,
            urn=record.urn,
            extracted_at=record.extracted_at.isoformat(),
            props=props,
            is_deleted=record.is_delete,
            data_plane_id=record.data_plane_id,
            source_connection_id=record.source_connection_id,
        ).consume()
        return summary.counters.nodes_created > 0

    @staticmethod
    def _link_tx(tx: Transaction, parent_label: str, parent_urn: str, child_label: str, child_urn: str, tenant_id: str, rel_type: str) -> None:
        query = (
            f"MERGE (p:{parent_label} {{tenant_id: $tenant_id, urn: $parent_urn}}) "
            f"MERGE (c:{child_label} {{tenant_id: $tenant_id, urn: $child_urn}}) "
            f"MERGE (p)-[r:{rel_type}]->(c) SET r.tenant_id = $tenant_id"
        )
        tx.run(query, tenant_id=tenant_id, parent_urn=parent_urn, child_urn=child_urn)

    @staticmethod
    def _link_owner_tx(tx: Transaction, label: str, urn: str, tenant_id: str, owner_name: str) -> None:
        query = (
            f"MERGE (n:{label} {{tenant_id: $tenant_id, urn: $urn}}) "
            "MERGE (o:Owner {tenant_id: $tenant_id, name: $owner_name}) "
            "MERGE (n)-[r:OWNED_BY]->(o) SET r.tenant_id = $tenant_id"
        )
        tx.run(query, tenant_id=tenant_id, urn=urn, owner_name=owner_name)

    # ------------------------------------------------------------------
    # Lineage edges
    # ------------------------------------------------------------------

    def _upsert_lineage_edge(self, record: EntityRecord) -> UpsertResult:
        payload = record.payload
        try:
            upstream_urn = payload["upstream_urn"]
            upstream_label = _NODE_LABELS[payload["upstream_entity_type"]]
            downstream_urn = payload["downstream_urn"]
            downstream_label = _NODE_LABELS[payload["downstream_entity_type"]]
        except KeyError as exc:
            raise UnknownEntityTypeError(f"lineage_edge payload missing/invalid field: {exc}") from exc

        with self._driver.session(database=self._database) as session:
            if record.is_delete:
                session.execute_write(self._tombstone_lineage_edge_tx, record.tenant_id, record.urn)
                return UpsertResult(urn=record.urn, created=False, tombstoned=True)

            created = session.execute_write(
                self._merge_derives_from_tx,
                upstream_label,
                upstream_urn,
                downstream_label,
                downstream_urn,
                record.tenant_id,
                record.urn,
                payload.get("confidence", "inferred"),
                payload.get("edge_granularity", "table_level"),
                record.extracted_at,
            )
            producer_job_urn = payload.get("producer_job_urn")
            if producer_job_urn:
                session.execute_write(
                    self._merge_job_edges_tx,
                    producer_job_urn,
                    downstream_label,
                    downstream_urn,
                    upstream_label,
                    upstream_urn,
                    record.tenant_id,
                )

        return UpsertResult(urn=record.urn, created=created)

    @staticmethod
    def _merge_derives_from_tx(
        tx: Transaction,
        upstream_label: str,
        upstream_urn: str,
        downstream_label: str,
        downstream_urn: str,
        tenant_id: str,
        edge_urn: str,
        confidence: str,
        edge_granularity: str,
        extracted_at: datetime,
    ) -> bool:
        query = (
            f"MERGE (up:{upstream_label} {{tenant_id: $tenant_id, urn: $upstream_urn}}) "
            f"MERGE (down:{downstream_label} {{tenant_id: $tenant_id, urn: $downstream_urn}}) "
            "MERGE (down)-[r:DERIVES_FROM {tenant_id: $tenant_id, urn: $edge_urn}]->(up) "
            "ON CREATE SET r.discovered_at = $extracted_at "
            "SET r.confidence = $confidence, r.edge_granularity = $edge_granularity, "
            "r.last_confirmed_at = $extracted_at, r.is_deleted = false"
        )
        summary = tx.run(
            query,
            tenant_id=tenant_id,
            upstream_urn=upstream_urn,
            downstream_urn=downstream_urn,
            edge_urn=edge_urn,
            confidence=confidence,
            edge_granularity=edge_granularity,
            extracted_at=extracted_at.isoformat(),
        ).consume()
        return summary.counters.relationships_created > 0

    @staticmethod
    def _merge_job_edges_tx(
        tx: Transaction,
        job_urn: str,
        produces_label: str,
        produces_urn: str,
        consumes_label: str,
        consumes_urn: str,
        tenant_id: str,
    ) -> None:
        query = (
            "MERGE (j:Job {tenant_id: $tenant_id, urn: $job_urn}) "
            f"MERGE (p:{produces_label} {{tenant_id: $tenant_id, urn: $produces_urn}}) "
            f"MERGE (c:{consumes_label} {{tenant_id: $tenant_id, urn: $consumes_urn}}) "
            "MERGE (j)-[rp:PRODUCES]->(p) SET rp.tenant_id = $tenant_id "
            "MERGE (j)-[rc:CONSUMES]->(c) SET rc.tenant_id = $tenant_id"
        )
        tx.run(query, tenant_id=tenant_id, job_urn=job_urn, produces_urn=produces_urn, consumes_urn=consumes_urn)

    @staticmethod
    def _tombstone_lineage_edge_tx(tx: Transaction, tenant_id: str, edge_urn: str) -> None:
        query = "MATCH ()-[r:DERIVES_FROM {tenant_id: $tenant_id, urn: $edge_urn}]->() SET r.is_deleted = true"
        tx.run(query, tenant_id=tenant_id, edge_urn=edge_urn)

    # ------------------------------------------------------------------
    # Read path for control-plane/api/catalog/tables/{urn}/lineage
    # ------------------------------------------------------------------

    def get_lineage(self, tenant_id: str, urn: str, direction: str = "both", max_hops: int = 5) -> dict:
        """Tenant-scoped multi-hop traversal per architecture.md §4's
        justification (`(t:Table {urn:$urn})<-[:DERIVES_FROM*1..N]-(downstream)`
        and its upstream mirror). `tenant_id` must come from the
        server-resolved auth context (§6), never a client-supplied param."""
        max_hops = max(1, min(max_hops, _MAX_HOPS_CEILING))
        result = {"urn": urn, "upstream": [], "downstream": []}
        with self._driver.session(database=self._database) as session:
            if direction in ("upstream", "both"):
                result["upstream"] = session.execute_read(self._traverse_tx, tenant_id, urn, max_hops, "upstream")
            if direction in ("downstream", "both"):
                result["downstream"] = session.execute_read(self._traverse_tx, tenant_id, urn, max_hops, "downstream")
        return result

    @staticmethod
    def _traverse_tx(tx: Transaction, tenant_id: str, urn: str, max_hops: int, direction: str) -> list[dict]:
        if direction == "downstream":
            # nodes that derive FROM this node: (n)-[:DERIVES_FROM*]->(t)
            pattern = f"(n)-[:DERIVES_FROM*1..{max_hops}]->(t)"
        else:
            pattern = f"(t)-[:DERIVES_FROM*1..{max_hops}]->(n)"
        query = (
            "MATCH (t {tenant_id: $tenant_id, urn: $urn}) "
            f"MATCH p = {pattern} "
            "WHERE n.tenant_id = $tenant_id AND n.is_deleted = false "
            "AND ALL(x IN nodes(p) WHERE x.tenant_id = $tenant_id) "
            "RETURN DISTINCT n.urn AS urn, labels(n) AS labels, min(length(p)) AS hops "
            "ORDER BY hops"
        )
        result = tx.run(query, tenant_id=tenant_id, urn=urn)
        return [
            {
                "urn": r["urn"],
                "entity_type": _label_to_entity_type(r["labels"]),
                "hops": r["hops"],
            }
            for r in result
        ]


def _sanitize_props(payload: dict[str, Any]) -> dict[str, Any]:
    """Neo4j properties must be primitives or homogeneous arrays of
    primitives — nested dicts (e.g. `foreign_key_ref`, `fields`) get
    JSON-serialized rather than dropped, since the graph store isn't the
    source of truth for those (Postgres is) but should still record enough
    for a UI/debugging to inspect the node directly."""
    sanitized: dict[str, Any] = {}
    for key, value in payload.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            sanitized[key] = value
        elif isinstance(value, list) and all(isinstance(v, (str, int, float, bool)) for v in value):
            sanitized[key] = value
        else:
            sanitized[key] = json.dumps(value, default=str)
    return sanitized


def _label_to_entity_type(labels: list[str]) -> str:
    for label in labels:
        if label in _ENTITY_TYPE_BY_LABEL:
            return _ENTITY_TYPE_BY_LABEL[label]
    return "unknown"
