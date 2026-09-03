"""``AnalyticsStore`` — ClickHouse client for the append-only scrape/usage
event stream (architecture.md §4).

``record_event`` is the exact method name FE1's fan-out worker calls
(architecture.md §8) after every write to Postgres/Neo4j/OpenSearch —
dispatches on the event dataclass type (``ScrapeEvent`` vs ``UsageEvent``,
``storage/types.py``) to the matching ClickHouse table. Explicitly not used
for entity storage or lineage (architecture.md §4) — this store only ever
appends events, never upserts/mutates.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Union

from clickhouse_connect.driver.client import Client

from storage.analytics.client import build_client
from storage.analytics.schema import SCRAPE_EVENTS_DDL, USAGE_EVENTS_DDL
from storage.types import ScrapeEvent, UsageEvent


class UnsupportedEventTypeError(TypeError):
    pass


class AnalyticsStore:
    def __init__(self, client: Optional[Client] = None) -> None:
        self._client = client or build_client()

    def ensure_schema(self) -> None:
        self._client.command(SCRAPE_EVENTS_DDL)
        self._client.command(USAGE_EVENTS_DDL)

    # ------------------------------------------------------------------
    # The seam: record_event
    # ------------------------------------------------------------------

    def record_event(self, event: Union[ScrapeEvent, UsageEvent]) -> None:
        if isinstance(event, ScrapeEvent):
            self._client.insert(
                "scrape_events",
                [[
                    event.tenant_id,
                    event.data_plane_id,
                    event.connector_type,
                    event.urn,
                    event.event_type,
                    event.occurred_at,
                    event.detail,
                ]],
                column_names=[
                    "tenant_id",
                    "data_plane_id",
                    "connector_type",
                    "urn",
                    "event_type",
                    "occurred_at",
                    "detail",
                ],
            )
        elif isinstance(event, UsageEvent):
            self._client.insert(
                "usage_events",
                [[event.tenant_id, event.urn, event.actor, event.action, event.occurred_at]],
                column_names=["tenant_id", "urn", "actor", "action", "occurred_at"],
            )
        else:
            raise UnsupportedEventTypeError(f"AnalyticsStore.record_event: unsupported event type {type(event)!r}")

    # ------------------------------------------------------------------
    # Read paths — sources/status freshness rollups, and the read seam ML
    # uses for its popularity signal (architecture.md §8: "ML reads
    # usage_events written by FE1's fan-out worker via FE2's ClickHouse
    # client").
    # ------------------------------------------------------------------

    def recent_scrape_events(self, tenant_id: str, urn: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
        query = "SELECT * FROM scrape_events WHERE tenant_id = {tenant_id:String}"
        params: dict[str, Any] = {"tenant_id": tenant_id}
        if urn is not None:
            query += " AND urn = {urn:String}"
            params["urn"] = urn
        query += " ORDER BY occurred_at DESC LIMIT {limit:UInt32}"
        params["limit"] = limit
        result = self._client.query(query, parameters=params)
        return [dict(zip(result.column_names, row)) for row in result.result_rows]

    def usage_counts_by_urn(self, tenant_id: str, since: datetime, limit: int = 100) -> list[dict[str, Any]]:
        """Popularity signal input for ML's relevance/ boost profile."""
        query = (
            "SELECT urn, count() AS usage_count FROM usage_events "
            "WHERE tenant_id = {tenant_id:String} AND occurred_at >= {since:DateTime} "
            "GROUP BY urn ORDER BY usage_count DESC LIMIT {limit:UInt32}"
        )
        result = self._client.query(query, parameters={"tenant_id": tenant_id, "since": since, "limit": limit})
        return [dict(zip(result.column_names, row)) for row in result.result_rows]
