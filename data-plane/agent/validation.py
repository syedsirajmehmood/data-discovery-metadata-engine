"""Pre-push validation: never push malformed/partial metadata (per this
engineer's scope in architecture.md §8). This is deliberately conservative
and generic since it validates against the envelope shape + spec.md's
field lists directly (no `shared/schema/` landed in this worktree at
write-time -- see `connectors/core/types.py`'s module docstring). Once
FE1's `shared/schema/*.schema.json` lands, this is the place to swap in
real JSON Schema validation without changing any connector.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from connectors.core.types import EntityType, NormalizedEntity, Operation

_VALID_ENTITY_TYPES = {e.value for e in EntityType}
_VALID_OPERATIONS = {o.value for o in Operation}

# Minimum required (non-null, non-empty) payload fields per entity_type,
# checked only on upserts -- deletes carry a deliberately minimal payload.
REQUIRED_UPSERT_FIELDS: Dict[str, List[str]] = {
    EntityType.TABLE.value: [
        "source_type",
        "source_connection_id",
        "database_name",
        "schema_name",
        "table_name",
        "fully_qualified_name",
        "object_type",
    ],
    EntityType.COLUMN.value: [
        "source_type",
        "source_connection_id",
        "table_urn",
        "name",
        "ordinal_position",
        "native_data_type",
    ],
    EntityType.DATASET.value: [
        "source_type",
        "source_connection_id",
        "bucket",
        "prefix",
        "fully_qualified_name",
        "schema_inferred",
    ],
    EntityType.JOB.value: ["source_type", "source_connection_id", "name", "job_type"],
    EntityType.LINEAGE_EDGE.value: [
        "upstream_urn",
        "upstream_entity_type",
        "downstream_urn",
        "downstream_entity_type",
    ],
}


def validate_entity(entity: NormalizedEntity) -> List[str]:
    """Returns a list of human-readable errors; empty list == valid."""
    errors: List[str] = []

    if not entity.urn or not isinstance(entity.urn, str):
        errors.append("urn is missing or not a string")
    if entity.entity_type not in _VALID_ENTITY_TYPES:
        errors.append(f"entity_type={entity.entity_type!r} is not one of {sorted(_VALID_ENTITY_TYPES)}")
    if entity.operation not in _VALID_OPERATIONS:
        errors.append(f"operation={entity.operation!r} is not one of {sorted(_VALID_OPERATIONS)}")
    if not entity.content_hash.startswith("sha256:"):
        errors.append("content_hash is missing or not in 'sha256:<hex>' form")
    if entity.extracted_at is None:
        errors.append("extracted_at is missing")

    if not isinstance(entity.payload, dict):
        errors.append("payload is not a dict")
    else:
        try:
            json.dumps(entity.payload)
        except TypeError as exc:
            errors.append(f"payload is not JSON-serializable: {exc}")

        if entity.operation == Operation.UPSERT.value:
            required = REQUIRED_UPSERT_FIELDS.get(entity.entity_type, [])
            for field_name in required:
                value = entity.payload.get(field_name, None)
                if value is None or value == "":
                    errors.append(f"payload.{field_name} is required for entity_type={entity.entity_type!r}")

    return errors


def is_valid(entity: NormalizedEntity) -> bool:
    return not validate_entity(entity)
