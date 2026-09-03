from datetime import datetime, timezone

from connectors.core.types import (
    Cursor,
    EntityType,
    LineageEdge,
    NormalizedEntity,
    Operation,
    content_hash,
    diff_deleted_urns,
)


def test_content_hash_is_deterministic_regardless_of_key_order():
    a = {"b": 1, "a": 2, "nested": {"y": 1, "x": 2}}
    b = {"a": 2, "nested": {"x": 2, "y": 1}, "b": 1}
    assert content_hash(a) == content_hash(b)


def test_content_hash_changes_when_payload_changes():
    a = content_hash({"x": 1})
    b = content_hash({"x": 2})
    assert a != b


def test_content_hash_format():
    h = content_hash({"x": 1})
    assert h.startswith("sha256:")
    assert len(h) == len("sha256:") + 64


def test_normalized_entity_auto_computes_content_hash():
    e = NormalizedEntity(
        urn="urn:postgres:host:db:public.t",
        entity_type=EntityType.TABLE.value,
        operation=Operation.UPSERT.value,
        payload={"table_name": "t"},
    )
    assert e.content_hash == content_hash({"table_name": "t"})


def test_normalized_entity_envelope_roundtrip():
    e = NormalizedEntity(
        urn="urn:postgres:host:db:public.t",
        entity_type=EntityType.TABLE.value,
        operation=Operation.UPSERT.value,
        payload={"table_name": "t"},
        extracted_at=datetime(2026, 9, 2, 10, 14, 50, tzinfo=timezone.utc),
    )
    envelope = e.to_envelope_dict()
    assert envelope["urn"] == e.urn
    assert envelope["entity_type"] == "table"
    assert envelope["operation"] == "upsert"
    assert envelope["extracted_at"] == "2026-09-02T10:14:50Z"
    assert envelope["content_hash"] == e.content_hash
    assert envelope["payload"] == {"table_name": "t"}

    restored = NormalizedEntity.from_envelope_dict(envelope)
    assert restored.urn == e.urn
    assert restored.entity_type == e.entity_type
    assert restored.operation == e.operation
    assert restored.content_hash == e.content_hash
    assert restored.payload == e.payload


def test_lineage_edge_to_normalized_entity_shape():
    edge = LineageEdge(
        upstream_urn="urn:postgres:h:d:s.a",
        upstream_entity_type="table",
        downstream_urn="urn:postgres:h:d:s.b",
        downstream_entity_type="table",
    )
    normalized = edge.to_normalized_entity()
    assert normalized.entity_type == EntityType.LINEAGE_EDGE.value
    assert normalized.operation == Operation.UPSERT.value
    assert normalized.urn == "urn:lineage:urn:postgres:h:d:s.a->urn:postgres:h:d:s.b"
    assert normalized.payload["upstream_urn"] == edge.upstream_urn
    assert normalized.payload["downstream_urn"] == edge.downstream_urn
    assert normalized.payload["confidence"] == "inferred"


def test_cursor_record_and_unchanged():
    cursor = Cursor.empty("src-1")
    cursor.record("urn:a", "table", "sha256:aaa")
    assert cursor.unchanged("urn:a", "sha256:aaa") is True
    assert cursor.unchanged("urn:a", "sha256:bbb") is False
    assert cursor.unchanged("urn:missing", "sha256:aaa") is False


def test_cursor_forget_removes_entry():
    cursor = Cursor.empty("src-1")
    cursor.record("urn:a", "table", "sha256:aaa")
    cursor.forget("urn:a")
    assert "urn:a" not in cursor.entries


def test_cursor_dict_roundtrip():
    cursor = Cursor.empty("src-1")
    cursor.record("urn:a", "table", "sha256:aaa")
    cursor.record("urn:b", "column", "sha256:bbb")
    restored = Cursor.from_dict(cursor.to_dict())
    assert restored.source_connection_id == "src-1"
    assert set(restored.entries.keys()) == {"urn:a", "urn:b"}
    assert restored.entries["urn:a"].content_hash == "sha256:aaa"


def test_diff_deleted_urns_detects_dropped_entities():
    cursor = Cursor.empty("src-1")
    cursor.record("urn:a", "table", "sha256:aaa")
    cursor.record("urn:b", "table", "sha256:bbb")
    cursor.record("urn:c", "column", "sha256:ccc")

    deleted = diff_deleted_urns(cursor, current_urns=["urn:a"], entity_type="table")
    assert deleted == ["urn:b"]

    # column-typed entries aren't considered when filtering by entity_type="table"
    deleted_all_tables_only = diff_deleted_urns(cursor, current_urns=[], entity_type="table")
    assert set(deleted_all_tables_only) == {"urn:a", "urn:b"}


def test_diff_deleted_urns_no_drift_when_nothing_missing():
    cursor = Cursor.empty("src-1")
    cursor.record("urn:a", "table", "sha256:aaa")
    deleted = diff_deleted_urns(cursor, current_urns=["urn:a"], entity_type="table")
    assert deleted == []
