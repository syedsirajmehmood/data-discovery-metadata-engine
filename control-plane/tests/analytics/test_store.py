"""Integration tests for AnalyticsStore against a real ClickHouse (started
by `docker compose -f infra/docker-compose.yml up -d`). Skips if unreachable.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from storage.analytics.client import build_client
from storage.analytics.store import AnalyticsStore, UnsupportedEventTypeError
from storage.types import ScrapeEvent, UsageEvent


@pytest.fixture(scope="module")
def client():
    try:
        c = build_client()
        c.command("SELECT 1")
    except Exception as exc:  # noqa: BLE001 - clickhouse-connect raises several distinct exception types on connect
        pytest.skip(f"ClickHouse not reachable — run `docker compose -f infra/docker-compose.yml up -d` ({exc})")
    return c


@pytest.fixture
def store(client):
    s = AnalyticsStore(client=client)
    s.ensure_schema()
    return s


@pytest.fixture
def tenant_id():
    return str(uuid.uuid4())


def test_record_scrape_event(store, tenant_id):
    event = ScrapeEvent(
        tenant_id=tenant_id,
        data_plane_id="dp-1",
        connector_type="postgres",
        urn="urn:postgres:prod-db-1:analytics:public.orders",
        event_type="entity_upserted",
        occurred_at=datetime.now(timezone.utc).replace(microsecond=0),
        detail="",
    )
    store.record_event(event)

    rows = store.recent_scrape_events(tenant_id, urn=event.urn, limit=10)
    assert len(rows) == 1
    assert rows[0]["event_type"] == "entity_upserted"


def test_record_usage_event_and_popularity_query(store, tenant_id):
    urn = "urn:postgres:prod-db-1:analytics:public.popular_table"
    for _ in range(3):
        store.record_event(
            UsageEvent(
                tenant_id=tenant_id,
                urn=urn,
                actor="dana",
                action="view",
                occurred_at=datetime.now(timezone.utc).replace(microsecond=0),
            )
        )

    since = datetime.now(timezone.utc) - timedelta(days=1)
    counts = store.usage_counts_by_urn(tenant_id, since=since)
    matching = [row for row in counts if row["urn"] == urn]
    assert matching and matching[0]["usage_count"] == 3


def test_record_event_rejects_unsupported_type(store):
    with pytest.raises(UnsupportedEventTypeError):
        store.record_event(object())  # not a ScrapeEvent or UsageEvent


def test_usage_counts_are_tenant_scoped(store):
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    urn = "urn:postgres:prod-db-1:analytics:public.iso_table"
    store.record_event(UsageEvent(tenant_id=tenant_a, urn=urn, actor="dana", action="view", occurred_at=datetime.now(timezone.utc)))

    since = datetime.now(timezone.utc) - timedelta(days=1)
    counts_a = store.usage_counts_by_urn(tenant_a, since=since)
    counts_b = store.usage_counts_by_urn(tenant_b, since=since)
    assert any(row["urn"] == urn for row in counts_a)
    assert not any(row["urn"] == urn for row in counts_b)
