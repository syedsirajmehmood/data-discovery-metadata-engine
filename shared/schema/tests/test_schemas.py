"""Direct tests of the canonical JSON Schema files in shared/schema/,
independent of the ingest API - proves each schema (and the cross-file
$refs between them) is valid and matches realistic entity payloads per
spec.md's field lists, for every entity type (not just the ones exercised
indirectly by control-plane/api/ingest's tests)."""
from __future__ import annotations

from shared.schema import (
    CURRENT_SCHEMA_VERSION,
    FORBIDDEN_PAYLOAD_FIELDS,
    ENTITY_SCHEMA_FILES,
    get_entity_schema,
    get_validator,
    known_entity_types,
)


def assert_valid(entity_type: str, payload: dict) -> None:
    validator = get_validator(entity_type)
    errors = list(validator.iter_errors(payload))
    assert errors == [], f"{entity_type} unexpectedly invalid: {[e.message for e in errors]}"


def assert_invalid(entity_type: str, payload: dict) -> None:
    validator = get_validator(entity_type)
    errors = list(validator.iter_errors(payload))
    assert errors != [], f"{entity_type} unexpectedly valid: {payload}"


def test_known_entity_types_matches_spec():
    assert known_entity_types() == sorted(
        {"table", "column", "dataset", "job", "lineage_edge", "scrape_run"}
    )


def test_current_schema_version_is_1_0():
    assert CURRENT_SCHEMA_VERSION == "1.0"


def test_get_entity_schema_unknown_type_returns_none():
    assert get_entity_schema("dashboard") is None  # not in MVP scope per spec.md


class TestTableSchema:
    def test_valid_minimal_table(self):
        assert_valid(
            "table",
            {
                "source_connection_id": "prod-postgres-1",
                "source_type": "postgres",
                "database_name": "analytics",
                "schema_name": "public",
                "table_name": "orders",
                "fully_qualified_name": "postgres://host/analytics.public.orders",
                "object_type": "table",
            },
        )

    def test_valid_full_table_with_optional_fields(self):
        assert_valid(
            "table",
            {
                "source_connection_id": "prod-postgres-1",
                "source_type": "postgres",
                "database_name": "analytics",
                "schema_name": "public",
                "table_name": "orders",
                "fully_qualified_name": "postgres://host/analytics.public.orders",
                "object_type": "view",
                "description": "Order facts",
                "description_source": "source_comment",
                "owner": "data-eng",
                "owner_source": "source",
                "tags": ["pii", "core"],
                "row_count_estimate": 1000000,
                "size_bytes_estimate": 500000000,
                "source_created_at": "2020-01-01T00:00:00Z",
                "source_last_modified_at": "2026-09-01T00:00:00Z",
            },
        )

    def test_missing_required_field_invalid(self):
        assert_invalid("table", {"source_connection_id": "x", "source_type": "postgres"})

    def test_wrong_source_type_invalid(self):
        payload = {
            "source_connection_id": "x",
            "source_type": "s3",  # must be 'postgres' for a Table
            "database_name": "a",
            "schema_name": "b",
            "table_name": "c",
            "fully_qualified_name": "postgres://h/a.b.c",
            "object_type": "table",
        }
        assert_invalid("table", payload)

    def test_bad_object_type_invalid(self):
        payload = {
            "source_connection_id": "x",
            "source_type": "postgres",
            "database_name": "a",
            "schema_name": "b",
            "table_name": "c",
            "fully_qualified_name": "postgres://h/a.b.c",
            "object_type": "not_a_type",
        }
        assert_invalid("table", payload)


class TestColumnSchema:
    def test_valid_column(self):
        assert_valid(
            "column",
            {
                "source_connection_id": "prod-postgres-1",
                "table_urn": "urn:postgres:h:db:public.orders",
                "name": "id",
                "ordinal_position": 0,
                "native_data_type": "bigint",
                "normalized_data_type": "integer",
                "is_nullable": False,
                "is_primary_key": True,
                "is_foreign_key": False,
            },
        )

    def test_foreign_key_ref(self):
        assert_valid(
            "column",
            {
                "source_connection_id": "prod-postgres-1",
                "table_urn": "t1",
                "name": "customer_id",
                "ordinal_position": 1,
                "native_data_type": "bigint",
                "normalized_data_type": "integer",
                "is_nullable": True,
                "is_primary_key": False,
                "is_foreign_key": True,
                "foreign_key_ref": {"table_urn": "urn:postgres:h:db:public.customers", "column": "id"},
            },
        )

    def test_bad_normalized_type_invalid(self):
        assert_invalid(
            "column",
            {
                "table_urn": "t1",
                "name": "id",
                "ordinal_position": 0,
                "native_data_type": "bigint",
                "normalized_data_type": "not_a_bucket",
                "is_nullable": False,
                "is_primary_key": True,
                "is_foreign_key": False,
            },
        )


class TestDatasetSchema:
    def test_valid_dataset_no_schema_inferred(self):
        assert_valid(
            "dataset",
            {
                "source_connection_id": "prod-s3-1",
                "source_type": "s3",
                "bucket": "my-bucket",
                "prefix": "exports/orders/",
                "fully_qualified_name": "s3://my-bucket/exports/orders/",
                "schema_inferred": False,
            },
        )

    def test_valid_dataset_with_inferred_fields(self):
        assert_valid(
            "dataset",
            {
                "source_connection_id": "prod-s3-1",
                "source_type": "s3",
                "bucket": "my-bucket",
                "prefix": "exports/orders/",
                "fully_qualified_name": "s3://my-bucket/exports/orders/",
                "file_format": "parquet",
                "schema_inferred": True,
                "fields": [
                    {
                        "name": "id",
                        "ordinal_position": 0,
                        "native_data_type": "int64",
                        "normalized_data_type": "integer",
                        "is_nullable": False,
                        "is_primary_key": False,
                        "is_foreign_key": False,
                    }
                ],
            },
        )

    def test_bad_file_format_invalid(self):
        assert_invalid(
            "dataset",
            {
                "source_connection_id": "x",
                "source_type": "s3",
                "bucket": "b",
                "prefix": "p",
                "fully_qualified_name": "s3://b/p",
                "file_format": "excel",
                "schema_inferred": False,
            },
        )


class TestJobSchema:
    def test_valid_job(self):
        assert_valid(
            "job",
            {
                "source_connection_id": "prod-dbt-1",
                "job_type": "dbt_model",
                "name": "stg_orders",
                "source_system": "dbt",
            },
        )

    def test_bad_job_type_invalid(self):
        assert_invalid(
            "job",
            {
                "source_connection_id": "x",
                "job_type": "cron",
                "name": "n",
                "source_system": "s",
            },
        )


class TestLineageEdgeSchema:
    def test_valid_table_level_edge(self):
        assert_valid(
            "lineage_edge",
            {
                "source_connection_id": "prod-dbt-1",
                "upstream_entity_id": "urn:postgres:h:db:public.raw_orders",
                "upstream_entity_type": "table",
                "downstream_entity_id": "urn:postgres:h:db:public.orders",
                "downstream_entity_type": "table",
                "edge_granularity": "table_level",
                "confidence": "job_declared",
                "discovered_at": "2026-09-02T10:00:00Z",
            },
        )

    def test_dataset_as_edge_endpoint_is_valid(self):
        # Justifies workers/fanout/worker.py's decision to route Dataset
        # to GraphStore even though architecture.md §4's Neo4j node list
        # doesn't explicitly name it - a lineage edge can point at one.
        assert_valid(
            "lineage_edge",
            {
                "source_connection_id": "x",
                "upstream_entity_id": "urn:s3:bucket/prefix",
                "upstream_entity_type": "dataset",
                "downstream_entity_id": "urn:postgres:h:db:public.orders",
                "downstream_entity_type": "table",
                "edge_granularity": "table_level",
                "confidence": "inferred",
                "discovered_at": "2026-09-02T10:00:00Z",
            },
        )

    def test_bad_confidence_invalid(self):
        assert_invalid(
            "lineage_edge",
            {
                "source_connection_id": "x",
                "upstream_entity_id": "a",
                "upstream_entity_type": "table",
                "downstream_entity_id": "b",
                "downstream_entity_type": "table",
                "edge_granularity": "table_level",
                "confidence": "definitely_true",
                "discovered_at": "2026-09-02T10:00:00Z",
            },
        )


class TestScrapeRunSchema:
    def test_valid_scrape_run(self):
        assert_valid(
            "scrape_run",
            {
                "source_connection_id": "prod-postgres-1",
                "started_at": "2026-09-02T10:00:00Z",
                "status": "success",
                "entities_seen_count": 42,
                "entities_created_count": 3,
                "entities_tombstoned_count": 0,
            },
        )

    def test_bad_status_invalid(self):
        assert_invalid(
            "scrape_run",
            {
                "source_connection_id": "x",
                "started_at": "2026-09-02T10:00:00Z",
                "status": "in_progress",  # not a valid enum value
                "entities_seen_count": 0,
                "entities_created_count": 0,
                "entities_tombstoned_count": 0,
            },
        )


class TestEnvelopeSchema:
    def test_valid_envelope(self):
        payload = {
            "batch_id": "b7e2b6b0-0000-0000-0000-000000000000",
            "data_plane_id": "dp_1",
            "connector_type": "postgres",
            "schema_version": "1.0",
            "sent_at": "2026-09-02T10:15:00Z",
            "entities": [
                {
                    "urn": "urn:postgres:h:db:public.orders",
                    "entity_type": "table",
                    "operation": "upsert",
                    "content_hash": "sha256:abc",
                    "extracted_at": "2026-09-02T10:14:50Z",
                    "payload": {"table_name": "orders"},
                }
            ],
        }
        errors = list(get_validator("envelope.schema.json").iter_errors(payload))
        assert errors == []

    def test_unknown_top_level_field_invalid(self):
        payload = {
            "batch_id": "b",
            "data_plane_id": "dp_1",
            "connector_type": "postgres",
            "schema_version": "1.0",
            "sent_at": "2026-09-02T10:15:00Z",
            "entities": [],
            "tenant_id": "should-not-be-allowed-here",
        }
        errors = list(get_validator("envelope.schema.json").iter_errors(payload))
        assert errors != []

    def test_novel_entity_type_string_is_schema_valid_extensibility(self):
        # envelope.schema.json intentionally does NOT enum-constrain
        # entity_type (architecture.md §2 extensibility) - a brand new
        # type is envelope-valid; the ingest API's dynamic dispatch is
        # what actually rejects unsupported ones (see
        # control-plane/api/ingest/validation.py + its tests).
        payload = {
            "batch_id": "b",
            "data_plane_id": "dp_1",
            "connector_type": "airflow",
            "schema_version": "1.0",
            "sent_at": "2026-09-02T10:15:00Z",
            "entities": [
                {
                    "urn": "urn:airflow:dag1",
                    "entity_type": "dashboard",  # not yet in ENTITY_SCHEMA_FILES
                    "operation": "upsert",
                    "extracted_at": "2026-09-02T10:14:50Z",
                    "payload": {},
                }
            ],
        }
        errors = list(get_validator("envelope.schema.json").iter_errors(payload))
        assert errors == []
        assert "dashboard" not in ENTITY_SCHEMA_FILES


class TestForbiddenPayloadFields:
    def test_forbidden_fields_are_exactly_server_and_envelope_assigned(self):
        assert FORBIDDEN_PAYLOAD_FIELDS == {
            "id",
            "tenant_id",
            "first_seen_at",
            "last_scraped_at",
            "is_deleted",
            "data_plane_id",
        }
