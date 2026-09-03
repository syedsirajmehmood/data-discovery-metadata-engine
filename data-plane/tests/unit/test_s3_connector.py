"""Unit tests for S3Connector's extraction/transform logic, using a fake
boto3-shaped client -- no real S3/MinIO needed. See
tests/integration/test_s3_integration.py for the real-MinIO path.
"""
import io
from datetime import datetime, timezone

from connectors.core.types import Cursor, EntityType, Operation, RawEntity
from connectors.s3 import s3_ops
from connectors.s3.connector import S3Config, S3Connector


class FakeS3Client:
    """objects_by_prefix: {prefix: [(key, size, last_modified), ...]}
    object_bytes: {key: bytes} for sniffing."""

    def __init__(self, objects_by_prefix=None, object_bytes=None):
        self._objects_by_prefix = objects_by_prefix or {}
        self._object_bytes = object_bytes or {}

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return self

    def paginate(self, Bucket, Prefix):
        objs = self._objects_by_prefix.get(Prefix, [])
        contents = [{"Key": k, "Size": s, "LastModified": lm} for k, s, lm in objs]
        return [{"Contents": contents}]

    def get_object(self, Bucket, Key, Range=None):
        data = self._object_bytes.get(Key, b"")
        return {"Body": io.BytesIO(data)}

    def head_bucket(self, Bucket):
        return {}


def make_connector(client=None, **overrides):
    connector = S3Connector()
    config = S3Config(
        source_connection_id="s3-1",
        bucket="demo-bucket",
        prefixes=overrides.pop("prefixes", ["events/"]),
        **overrides,
    )
    connector._config = config
    connector._client = client or FakeS3Client()
    connector._cursor_state = Cursor.empty(config.source_connection_id)
    return connector


LM = datetime(2026, 9, 1, tzinfo=timezone.utc)


# -- extract_metadata: dataset -----------------------------------------------


def test_extract_metadata_dataset_basic_fields_no_schema_inferred():
    connector = make_connector()
    list_result = s3_ops.ListResult(object_count=3, total_size_bytes=300, sample_keys=["events/a.bin"])
    raw = RawEntity(entity_type=EntityType.DATASET.value, key="events/", raw={"prefix": "events/", "list_result": list_result})

    normalized = connector.extract_metadata(raw)
    assert normalized.urn == "urn:s3:demo-bucket/events/"
    assert normalized.operation == "upsert"
    p = normalized.payload
    assert p["bucket"] == "demo-bucket"
    assert p["prefix"] == "events/"
    assert p["fully_qualified_name"] == "s3://demo-bucket/events/"
    assert p["object_count_estimate"] == 3
    assert p["total_size_bytes_estimate"] == 300
    assert p["schema_inferred"] is False
    assert "fields" not in p  # absent, per spec.md AC-2a, when not inferred
    assert p["file_format"] == "unknown"


def test_extract_metadata_dataset_infers_csv_schema():
    csv_bytes = b"id,name\n1,alice\n2,bob\n"
    client = FakeS3Client(object_bytes={"events/part-0.csv": csv_bytes})
    connector = make_connector(client=client)
    list_result = s3_ops.ListResult(
        object_count=2, total_size_bytes=len(csv_bytes) * 2, sample_keys=["events/part-0.csv", "events/part-1.csv"]
    )
    raw = RawEntity(entity_type=EntityType.DATASET.value, key="events/", raw={"prefix": "events/", "list_result": list_result})

    normalized = connector.extract_metadata(raw)
    p = normalized.payload
    assert p["file_format"] == "csv"
    assert p["schema_inferred"] is True
    assert [f["name"] for f in p["fields"]] == ["id", "name"]


def test_extract_metadata_dataset_infers_partitioning():
    connector = make_connector()
    list_result = s3_ops.ListResult(
        object_count=2,
        total_size_bytes=10,
        sample_keys=["events/year=2024/month=01/a.parquet", "events/year=2024/month=02/b.parquet"],
    )
    raw = RawEntity(entity_type=EntityType.DATASET.value, key="events/", raw={"prefix": "events/", "list_result": list_result})
    normalized = connector.extract_metadata(raw)
    assert normalized.payload["partition_keys"] == ["year", "month"]


def test_extract_metadata_dataset_captures_last_modified():
    connector = make_connector()
    list_result = s3_ops.ListResult(object_count=1, total_size_bytes=1, sample_keys=["events/a.csv"], last_modified_iso="2026-09-01T00:00:00+00:00")
    raw = RawEntity(entity_type=EntityType.DATASET.value, key="events/", raw={"prefix": "events/", "list_result": list_result})
    normalized = connector.extract_metadata(raw)
    assert normalized.payload["source_last_modified_at"] == "2026-09-01T00:00:00+00:00"


# -- tombstones ---------------------------------------------------------------


def test_extract_metadata_tombstone_is_delete():
    connector = make_connector()
    raw = RawEntity(entity_type=EntityType.DATASET.value, key="urn:s3:demo-bucket/gone/", raw={}, tombstone=True)
    normalized = connector.extract_metadata(raw)
    assert normalized.operation == Operation.DELETE.value
    assert normalized.urn == "urn:s3:demo-bucket/gone/"


# -- discover(): full orchestration with a fake client -----------------------


def test_discover_yields_datasets_with_objects_and_skips_empty_prefixes():
    client = FakeS3Client(
        objects_by_prefix={
            "events/": [("events/a.parquet", 10, LM), ("events/b.parquet", 20, LM)],
            "empty/": [],
        }
    )
    connector = make_connector(client=client, prefixes=["events/", "empty/"])
    raws = list(connector.discover())
    assert len(raws) == 1
    assert raws[0].entity_type == EntityType.DATASET.value
    assert raws[0].key == "events/"
    assert raws[0].tombstone is False


def test_discover_tombstones_dataset_that_became_empty():
    client = FakeS3Client(objects_by_prefix={"events/": []})
    connector = make_connector(client=client, prefixes=["events/"])
    connector.get_cursor().record("urn:s3:demo-bucket/events/", "dataset", "sha256:aaa")

    raws = list(connector.discover())
    assert len(raws) == 1
    assert raws[0].tombstone is True
    assert raws[0].key == "urn:s3:demo-bucket/events/"

    normalized = connector.extract_metadata(raws[0])
    assert normalized.operation == Operation.DELETE.value


def test_get_set_cursor_roundtrip():
    connector = make_connector()
    cursor = Cursor.empty("s3-1")
    cursor.record("urn:a", "dataset", "sha256:aaa")
    connector.set_cursor(cursor)
    assert connector.get_cursor() is cursor
