"""Tests for FanoutWorker's routing logic, using the in-memory fakes
(fakes.py) so this runs with no real Postgres/Neo4j/OpenSearch/ClickHouse."""
from __future__ import annotations

import pytest

from workers.fanout.fakes import (
    InMemoryAnalyticsStore,
    InMemoryGraphStore,
    InMemoryRelationalStore,
    InMemorySearchIndex,
)
from workers.fanout.interfaces import CatalogEntity
from workers.fanout.worker import FanoutWorker


def make_entity(
    urn: str,
    entity_type: str = "table",
    operation: str = "upsert",
    content_hash: str = "sha256:abc",
    is_deleted: bool = False,
    payload: dict = None,
) -> CatalogEntity:
    return CatalogEntity(
        id="11111111-1111-1111-1111-111111111111",
        urn=urn,
        entity_type=entity_type,
        tenant_id="22222222-2222-2222-2222-222222222222",
        data_plane_id="dp_1",
        source_connection_id="prod-postgres-1",
        operation=operation,
        is_deleted=is_deleted,
        content_hash=content_hash,
        extracted_at="2026-09-02T10:14:50Z",
        first_seen_at="2026-09-02T10:14:50Z",
        last_scraped_at="2026-09-02T10:14:50Z",
        payload=payload or {"table_name": "orders"},
    )


@pytest.fixture
def stores():
    return {
        "relational": InMemoryRelationalStore(),
        "graph": InMemoryGraphStore(),
        "search": InMemorySearchIndex(),
        "analytics": InMemoryAnalyticsStore(),
    }


@pytest.fixture
def worker(stores):
    return FanoutWorker(
        relational_store=stores["relational"],
        graph_store=stores["graph"],
        search_index=stores["search"],
        analytics_store=stores["analytics"],
        connector_type="postgres",
    )


class TestTableRouting:
    def test_new_table_fans_out_to_relational_graph_and_search(self, worker, stores):
        entity = make_entity("urn:postgres:h:db:public.orders", entity_type="table")
        result = worker.process_batch("batch-1", [entity])

        assert result.processed_count == 1
        outcome = result.outcomes[0]
        assert outcome.wrote_relational is True
        assert outcome.wrote_graph is True
        assert outcome.wrote_search is True
        assert outcome.wrote_analytics is True
        assert outcome.skipped_as_unchanged is False

        assert stores["relational"].get(entity.urn) is not None
        assert entity.urn in stores["graph"].urns()
        assert entity.urn in stores["search"].documents_by_urn
        assert len(stores["analytics"].events) == 1
        assert stores["analytics"].events[0].event_type == "entity_upserted"


class TestContentHashNoOp:
    def test_unchanged_content_hash_skips_graph_and_search(self, worker, stores):
        e1 = make_entity("urn:postgres:h:db:public.orders", content_hash="sha256:same")
        e2 = make_entity("urn:postgres:h:db:public.orders", content_hash="sha256:same")

        worker.process_batch("batch-1", [e1])
        result = worker.process_batch("batch-2", [e2])

        outcome = result.outcomes[0]
        assert outcome.wrote_relational is True  # always upserted (bumps last_scraped_at)
        assert outcome.wrote_graph is False
        assert outcome.wrote_search is False
        assert outcome.skipped_as_unchanged is True

        # graph/search only got the first write
        assert stores["graph"].urns() == [e1.urn]
        assert len(stores["search"].index_calls) == 1
        assert stores["analytics"].events[-1].event_type == "entity_unchanged"

    def test_changed_content_hash_writes_again(self, worker, stores):
        e1 = make_entity("urn:postgres:h:db:public.orders", content_hash="sha256:v1")
        e2 = make_entity("urn:postgres:h:db:public.orders", content_hash="sha256:v2")

        worker.process_batch("batch-1", [e1])
        result = worker.process_batch("batch-2", [e2])

        outcome = result.outcomes[0]
        assert outcome.wrote_graph is True
        assert outcome.wrote_search is True
        assert stores["graph"].urns() == [e1.urn, e2.urn]


class TestDeleteAlwaysPropagates:
    def test_delete_operation_always_fans_out_even_with_same_hash(self, worker, stores):
        e1 = make_entity("urn:postgres:h:db:public.orders", content_hash="sha256:v1", operation="upsert")
        e2 = make_entity(
            "urn:postgres:h:db:public.orders",
            content_hash="sha256:v1",
            operation="delete",
            is_deleted=True,
        )

        worker.process_batch("batch-1", [e1])
        result = worker.process_batch("batch-2", [e2])

        outcome = result.outcomes[0]
        assert outcome.skipped_as_unchanged is False
        assert outcome.wrote_graph is True
        assert outcome.wrote_search is True
        assert stores["analytics"].events[-1].event_type == "entity_deleted"
        assert stores["relational"].get(e1.urn).is_deleted is True


class TestFirstSeenAtPreserved:
    def test_first_seen_at_immutable_across_rescrapes(self, worker, stores):
        e1 = make_entity("urn:postgres:h:db:public.orders", content_hash="sha256:v1")
        object.__setattr__(e1, "first_seen_at", "2020-01-01T00:00:00Z")
        e2 = make_entity("urn:postgres:h:db:public.orders", content_hash="sha256:v2")
        object.__setattr__(e2, "first_seen_at", "2026-09-02T10:14:50Z")

        worker.process_batch("batch-1", [e1])
        worker.process_batch("batch-2", [e2])

        stored = stores["relational"].get(e1.urn)
        assert stored.first_seen_at == "2020-01-01T00:00:00Z"


class TestLineageEdgeRouting:
    def test_lineage_edge_goes_to_relational_and_graph_not_search(self, worker, stores):
        entity = make_entity(
            "urn:lineage:orders->revenue",
            entity_type="lineage_edge",
            payload={"upstream_entity_id": "a", "downstream_entity_id": "b"},
        )
        result = worker.process_batch("batch-1", [entity])

        outcome = result.outcomes[0]
        assert outcome.wrote_relational is True
        assert outcome.wrote_graph is True
        assert outcome.wrote_search is False


class TestScrapeRunRouting:
    def test_scrape_run_goes_only_to_analytics(self, worker, stores):
        entity = make_entity(
            "urn:scrape_run:prod-postgres-1:2026-09-02T10:14:50Z",
            entity_type="scrape_run",
            payload={"status": "success"},
        )
        result = worker.process_batch("batch-1", [entity])

        outcome = result.outcomes[0]
        assert outcome.wrote_relational is False
        assert outcome.wrote_graph is False
        assert outcome.wrote_search is False
        assert outcome.wrote_analytics is True

        assert stores["relational"].entities_by_urn == {}
        assert stores["graph"].upserted == []
        assert stores["search"].index_calls == []
        assert stores["analytics"].events[0].event_type == "scrape_run"


class TestDatasetRouting:
    def test_dataset_goes_to_all_three_projections(self, worker, stores):
        entity = make_entity(
            "urn:s3:my-bucket/exports/orders/",
            entity_type="dataset",
            payload={"bucket": "my-bucket", "prefix": "exports/orders/"},
        )
        result = worker.process_batch("batch-1", [entity])

        outcome = result.outcomes[0]
        assert outcome.wrote_relational is True
        assert outcome.wrote_graph is True
        assert outcome.wrote_search is True


def test_batch_with_multiple_entity_types(worker, stores):
    entities = [
        make_entity("urn:t1", entity_type="table"),
        make_entity("urn:c1", entity_type="column", payload={"name": "id"}),
        make_entity("urn:d1", entity_type="dataset", payload={"bucket": "b"}),
        make_entity("urn:j1", entity_type="job", payload={"name": "etl"}),
        make_entity("urn:l1", entity_type="lineage_edge", payload={}),
        make_entity("urn:sr1", entity_type="scrape_run", payload={"status": "success"}),
    ]
    result = worker.process_batch("batch-1", entities)

    assert result.processed_count == 6
    assert len(stores["relational"].upsert_calls) == 5  # all but scrape_run
    assert len(stores["search"].index_calls) == 4  # table, column, dataset, job
    assert len(stores["graph"].upserted) == 5  # all but scrape_run
    assert len(stores["analytics"].events) == 6  # every entity gets an audit event
