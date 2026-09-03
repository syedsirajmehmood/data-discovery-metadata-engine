"""Control-plane storage layer.

Four storage engines, one per workload, per architecture.md §4:

- ``relational``  — Postgres, system of record for entities/tenants/API keys.
- ``graph``       — Neo4j, lineage/relationship graph projection.
- ``search``      — OpenSearch, full-text catalog search projection.
- ``analytics``   — ClickHouse, append-only scrape/usage event stream.

``storage.types`` defines the common ``EntityRecord`` shape that is the seam
between FE1's fan-out worker (``control-plane/workers/fanout/``) and the four
store classes here. Each store implements one upsert/index/record method
(``RelationalStore.upsert_entity``, ``GraphStore.upsert_entity``,
``SearchIndex.index_entity``, ``AnalyticsStore.record_event``) that accepts
an ``EntityRecord`` (or, for analytics, an event dataclass) and is otherwise
free to manage its own schema/connection internally.
"""
