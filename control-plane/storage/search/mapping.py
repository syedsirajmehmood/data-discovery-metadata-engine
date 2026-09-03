"""OpenSearch index mapping for catalog search.

Per architecture.md §4: "Indexes table/column/dashboard name, description,
tags, owner, denormalized from Postgres by the fan-out worker." One index
covers all searchable entity types (rather than one index per type) so a
single query returns cross-source results in one ranked list — this is the
structural requirement behind spec.md AC-1 (unified search) and AC-8
(cross-source result parity: Postgres tables and S3 datasets must not be
two disconnected result sets).

**Documented extension**: ``dataset`` (S3) is indexed alongside
table/column/dashboard even though architecture.md's sentence names only
three types — spec.md's AC-1/AC-8 require S3 datasets to be searchable as
first-class peers of Postgres tables, so omitting them would fail those
acceptance criteria. ``job`` and ``lineage_edge`` are intentionally not
indexed: no MVP connector populates Job, and lineage edges aren't a
search-result entity, they back the lineage endpoint instead.

``tenant_id`` is a mandatory ``keyword`` field so it can always be applied
as an exact-match filter (never full-text) — see ``query_builder.py``.
"""

from __future__ import annotations

INDEX_NAME = "catalog_entities"

SEARCHABLE_ENTITY_TYPES = frozenset({"table", "column", "dataset", "dashboard"})

INDEX_BODY = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
    },
    "mappings": {
        "properties": {
            "tenant_id": {"type": "keyword"},
            "urn": {"type": "keyword"},
            "entity_type": {"type": "keyword"},
            "source_type": {"type": "keyword"},
            "data_plane_id": {"type": "keyword"},
            "source_connection_id": {"type": "keyword"},
            "name": {
                "type": "text",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "description": {"type": "text"},
            "tags": {"type": "keyword"},
            "owner": {
                "type": "text",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
            },
            "fully_qualified_name": {"type": "keyword"},
            "first_seen_at": {"type": "date"},
            "last_scraped_at": {"type": "date"},
            "is_deleted": {"type": "boolean"},
        }
    },
}
