from connectors.core.types import EntityType, NormalizedEntity, Operation
from agent.validation import is_valid, validate_entity


def valid_table_entity():
    return NormalizedEntity(
        urn="urn:postgres:h:d:public.orders",
        entity_type=EntityType.TABLE.value,
        operation=Operation.UPSERT.value,
        payload={
            "source_type": "postgres",
            "source_connection_id": "pg-1",
            "database_name": "d",
            "schema_name": "public",
            "table_name": "orders",
            "fully_qualified_name": "postgres://h/d.public.orders",
            "object_type": "table",
        },
    )


def test_valid_table_entity_passes():
    entity = valid_table_entity()
    assert is_valid(entity)
    assert validate_entity(entity) == []


def test_missing_required_payload_field_fails():
    entity = valid_table_entity()
    del entity.payload["fully_qualified_name"]
    errors = validate_entity(entity)
    assert any("fully_qualified_name" in e for e in errors)
    assert not is_valid(entity)


def test_empty_string_required_field_fails():
    entity = valid_table_entity()
    entity.payload["table_name"] = ""
    errors = validate_entity(entity)
    assert any("table_name" in e for e in errors)


def test_missing_urn_fails():
    entity = valid_table_entity()
    entity.urn = ""
    assert not is_valid(entity)


def test_invalid_entity_type_fails():
    entity = valid_table_entity()
    entity.entity_type = "not_a_real_type"
    errors = validate_entity(entity)
    assert any("entity_type" in e for e in errors)


def test_invalid_operation_fails():
    entity = valid_table_entity()
    entity.operation = "patch"
    errors = validate_entity(entity)
    assert any("operation" in e for e in errors)


def test_delete_operation_does_not_require_full_payload():
    entity = NormalizedEntity(
        urn="urn:postgres:h:d:public.dropped",
        entity_type=EntityType.TABLE.value,
        operation=Operation.DELETE.value,
        payload={"source_connection_id": "pg-1"},
    )
    assert is_valid(entity)


def test_non_serializable_payload_fails():
    entity = valid_table_entity()
    entity.payload["bad"] = object()
    errors = validate_entity(entity)
    assert any("JSON-serializable" in e for e in errors)


def test_dataset_entity_required_fields():
    entity = NormalizedEntity(
        urn="urn:s3:bucket/prefix/",
        entity_type=EntityType.DATASET.value,
        operation=Operation.UPSERT.value,
        payload={
            "source_type": "s3",
            "source_connection_id": "s3-1",
            "bucket": "bucket",
            "prefix": "prefix/",
            "fully_qualified_name": "s3://bucket/prefix/",
            "schema_inferred": False,
        },
    )
    assert is_valid(entity)


def test_lineage_edge_required_fields():
    entity = NormalizedEntity(
        urn="urn:lineage:a->b",
        entity_type=EntityType.LINEAGE_EDGE.value,
        operation=Operation.UPSERT.value,
        payload={
            "upstream_urn": "a",
            "upstream_entity_type": "table",
            "downstream_urn": "b",
            "downstream_entity_type": "table",
        },
    )
    assert is_valid(entity)
