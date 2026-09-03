"""Integration tests against real MinIO, seeded by
`deploy/minio-init` (via the `minio-init` compose service running `mc cp`
of `deploy/minio-init/sample-data/`): a Hive-partitioned `events/` dataset
and a flat `exports/users.csv` dataset. Run via docker-compose -- see
README.
"""
import pytest

from connectors.core.types import EntityType, Operation
from connectors.s3.connector import S3Connector

pytestmark = pytest.mark.integration


def _discover_and_extract(connector):
    normalized = []
    for raw in connector.discover():
        normalized.append(connector.extract_metadata(raw))
    return normalized


def test_discovers_both_seeded_prefixes_as_datasets(s3_config):
    connector = S3Connector()
    connector.connect(s3_config)
    entities = _discover_and_extract(connector)

    by_prefix = {e.payload["prefix"]: e for e in entities}
    assert "events/" in by_prefix
    assert "exports/" in by_prefix


def test_events_dataset_infers_partitioning_and_csv_schema(s3_config):
    connector = S3Connector()
    connector.connect(s3_config)
    entities = _discover_and_extract(connector)
    events = next(e for e in entities if e.payload["prefix"] == "events/")

    assert events.payload["object_count_estimate"] == 2  # two seeded part files
    assert events.payload["file_format"] == "csv"
    assert events.payload["partition_keys"] == ["year", "month", "day"]
    assert events.payload["schema_inferred"] is True
    field_names = [f["name"] for f in events.payload["fields"]]
    assert field_names == ["event_id", "user_id", "event_type", "occurred_at"]
    assert events.payload["fully_qualified_name"] == f"s3://{s3_config['bucket']}/events/"


def test_exports_dataset_infers_csv_schema_with_type_sniffing(s3_config):
    connector = S3Connector()
    connector.connect(s3_config)
    entities = _discover_and_extract(connector)
    exports = next(e for e in entities if e.payload["prefix"] == "exports/")

    assert exports.payload["object_count_estimate"] == 1
    assert exports.payload["schema_inferred"] is True
    by_name = {f["name"]: f for f in exports.payload["fields"]}
    assert by_name["id"]["normalized_data_type"] == "integer"
    assert by_name["is_active"]["normalized_data_type"] == "boolean"
    assert exports.payload["partition_keys"] == []


def test_extract_lineage_is_empty(s3_config):
    connector = S3Connector()
    connector.connect(s3_config)
    assert list(connector.extract_lineage()) == []


def test_urn_scheme_matches_architecture_example(s3_config):
    connector = S3Connector()
    connector.connect(s3_config)
    entities = _discover_and_extract(connector)
    exports = next(e for e in entities if e.payload["prefix"] == "exports/")
    assert exports.urn == f"urn:s3:{s3_config['bucket']}/exports/"


def test_configured_prefix_with_no_objects_is_skipped(s3_config):
    config = dict(s3_config)
    config["prefixes"] = ["does-not-exist/"]
    connector = S3Connector()
    connector.connect(config)
    entities = _discover_and_extract(connector)
    assert entities == []
