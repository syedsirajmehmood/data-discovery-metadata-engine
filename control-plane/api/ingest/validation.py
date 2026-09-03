"""Request envelope + per-entity payload validation against shared/schema,
per architecture.md §2 and this task's instructions. Two layers:

1. `validate_envelope_shape()` - validates the raw envelope dict against
   shared/schema/envelope.schema.json directly (independent of the
   Pydantic parse in models.py, so shared/schema stays the single source
   of truth for the wire shape rather than the Pydantic model silently
   drifting from it).
2. `validate_entity_payload()` - per-entity: rejects payloads that smuggle
   in server-assigned/envelope-level fields (shared.schema.FORBIDDEN_PAYLOAD_FIELDS),
   rejects unknown entity_type, then validates payload against
   shared/schema/<entity_type>.schema.json.

This module never talks to storage - it only classifies each entity as
accepted or rejected. See service.py for how these outcomes feed the
per-entity accept/reject response (architecture.md §2).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from shared.schema import FORBIDDEN_PAYLOAD_FIELDS, get_validator

from api.ingest.models import EntityItem

VALID_OPERATIONS = frozenset({"upsert", "delete"})


@dataclass(frozen=True)
class EntityRejection:
    urn: str
    error: str
    detail: str


def _format_jsonschema_errors(errors) -> str:
    formatted = []
    for e in sorted(errors, key=lambda e: list(e.path)):
        location = "/".join(str(p) for p in e.path) or "<root>"
        formatted.append(f"{location}: {e.message}")
    return "; ".join(formatted[:5])


def validate_envelope_shape(raw_envelope: dict) -> List[str]:
    """Validate the raw request body against shared/schema/envelope.schema.json.
    Returns a list of human-readable errors (empty list = valid). This is
    a whole-batch, all-or-nothing check (malformed envelope shape is a
    400 per architecture.md §2: "rejects return 400 with the same
    per-entity error shape if the entire batch is malformed"), distinct
    from per-entity payload validation below.
    """
    validator = get_validator("envelope.schema.json")
    errors = list(validator.iter_errors(raw_envelope))
    if not errors:
        return []
    return [
        f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}"
        for e in sorted(errors, key=lambda e: list(e.path))
    ]


def validate_entity_payload(entity: EntityItem) -> Optional[EntityRejection]:
    """Returns None if `entity` is acceptable, else an EntityRejection
    explaining why. Does not raise - malformed individual entities are a
    per-entity rejection, not a transport/request failure (architecture.md
    §2: "that's a data-quality bug in the connector, not a transport
    failure")."""
    # Defense in depth only: envelope.schema.json's entity_item.operation
    # is an enum{upsert,delete}, so an invalid operation is normally
    # already rejected at validate_envelope_shape() (whole-batch 400)
    # before this function ever runs. Kept here so validate_entity_payload()
    # is still correct if ever called directly (e.g. by a future
    # consumer that skips whole-envelope validation).
    if entity.operation not in VALID_OPERATIONS:
        return EntityRejection(
            urn=entity.urn,
            error="invalid_operation",
            detail=f"operation must be one of {sorted(VALID_OPERATIONS)}, got {entity.operation!r}",
        )

    forbidden_present = sorted(FORBIDDEN_PAYLOAD_FIELDS & entity.payload.keys())
    if forbidden_present:
        return EntityRejection(
            urn=entity.urn,
            error="forbidden_field_in_payload",
            detail=(
                "payload must not include server-assigned or envelope-level fields: "
                f"{forbidden_present} (see shared/schema/README.md)"
            ),
        )

    try:
        validator = get_validator(entity.entity_type)
    except ValueError:
        return EntityRejection(
            urn=entity.urn,
            error="unsupported_entity_type",
            detail=f"no shared/schema definition for entity_type={entity.entity_type!r}",
        )

    if entity.operation == "delete":
        # A delete tombstones by urn; payload isn't required to fully
        # validate against the entity schema (architecture.md doesn't
        # specify delete-payload contents, and spec.md's tombstone
        # semantics only need urn + entity_type).
        return None

    errors = list(validator.iter_errors(entity.payload))
    if errors:
        return EntityRejection(
            urn=entity.urn,
            error="schema_validation_failed",
            detail=_format_jsonschema_errors(errors),
        )
    return None
