"""ClickHouse table DDL — exact shape from architecture.md §4:

    scrape_events(tenant_id, data_plane_id, connector_type, urn, event_type, occurred_at, detail)
    usage_events(tenant_id, urn, actor, action, occurred_at)

both ``ORDER BY (tenant_id, occurred_at)`` and partitioned by month
(tenant-leading sort key so tenant-scoped range queries stay efficient at
MVP scale — architecture.md §6).
"""

from __future__ import annotations

SCRAPE_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS scrape_events (
    tenant_id String,
    data_plane_id String,
    connector_type String,
    urn String,
    event_type String,
    occurred_at DateTime,
    detail String
) ENGINE = MergeTree
PARTITION BY toYYYYMM(occurred_at)
ORDER BY (tenant_id, occurred_at)
"""

USAGE_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS usage_events (
    tenant_id String,
    urn String,
    actor String,
    action String,
    occurred_at DateTime
) ENGINE = MergeTree
PARTITION BY toYYYYMM(occurred_at)
ORDER BY (tenant_id, occurred_at)
"""
