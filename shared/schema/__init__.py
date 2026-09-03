"""Canonical JSON Schema files for the push-contract envelope and every
catalog entity type, per architecture.md §2 and spec.md's metadata schema
section.

This package is the ONLY thing both `data-plane/` and `control-plane/` are
allowed to depend on (architecture.md §1). It is intentionally dependency-
light (stdlib `json` + `pathlib` only) so it imports cleanly from either
side without dragging in FastAPI/pydantic/etc.

Usage:
    from shared.schema import get_entity_schema, load_envelope_schema, SERVER_ASSIGNED_FIELDS

    schema = get_entity_schema("table")   # dict, ready for jsonschema.validate()
    envelope_schema = load_envelope_schema()

Versioning: the envelope's `schema_version` is "1.0" (architecture.md §2).
A backwards-incompatible schema change bumps `schema_version` and is
proposed via a new dated entry in `.claude/team/decisions.md`, not a silent
edit here (architecture.md §1/§8) - see README.md in this directory.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

SCHEMA_DIR = Path(__file__).resolve().parent

CURRENT_SCHEMA_VERSION = "1.0"

# entity_type (as used in the envelope's entities[].entity_type, and in the
# ingest response's per-entity accept/reject list) -> schema filename.
ENTITY_SCHEMA_FILES = {
    "table": "table.schema.json",
    "column": "column.schema.json",
    "dataset": "dataset.schema.json",
    "job": "job.schema.json",
    "lineage_edge": "lineage_edge.schema.json",
    "scrape_run": "scrape_run.schema.json",
}

# Fields that a data-plane push payload must NEVER supply, because the
# control plane owns them (architecture.md §2: "tenant_id is never accepted
# from the request body" - applied here to the full set of catalog-side /
# server-assigned common fields, plus data_plane_id which is supplied once
# at the envelope level rather than repeated per-entity). The ingest API
# rejects (not silently strips) any entity payload containing these keys.
SERVER_ASSIGNED_FIELDS = frozenset(
    {"id", "tenant_id", "first_seen_at", "last_scraped_at", "is_deleted"}
)
ENVELOPE_LEVEL_FIELDS = frozenset({"data_plane_id"})
FORBIDDEN_PAYLOAD_FIELDS = SERVER_ASSIGNED_FIELDS | ENVELOPE_LEVEL_FIELDS


@lru_cache(maxsize=None)
def _load_json(filename: str) -> dict:
    path = SCHEMA_DIR / filename
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_schema(filename: str) -> dict:
    """Load and parse a schema file by name (e.g. 'table.schema.json').

    Cached - callers get the same dict object back; treat it as read-only.
    """
    return _load_json(filename)


def load_envelope_schema() -> dict:
    return load_schema("envelope.schema.json")


def load_ingest_response_schema() -> dict:
    return load_schema("ingest_response.schema.json")


def get_entity_schema(entity_type: str) -> Optional[dict]:
    """Return the canonical schema dict for a given entity_type, or None if
    entity_type isn't one this schema_version knows about (the caller
    should treat that as a per-entity rejection, e.g. 'unsupported_entity_type'
    - not a hard failure of the whole batch, per architecture.md §2's
    per-entity accept/reject model)."""
    filename = ENTITY_SCHEMA_FILES.get(entity_type)
    if filename is None:
        return None
    return load_schema(filename)


def known_entity_types() -> list:
    return sorted(ENTITY_SCHEMA_FILES.keys())


# ---------------------------------------------------------------------------
# Validator construction. Several schemas here $ref each other by filename
# (e.g. table.schema.json refs common.schema.json; dataset.schema.json refs
# column.schema.json#/$defs/column_specific_fields), resolved via each
# file's declared "$id" (all under the same
# https://schemas.data-discovery.internal/1.0/ namespace). This helper
# builds a `referencing` Registry that resolves those $ids back to the
# local files on disk, so callers never need to know about that plumbing -
# both control-plane/api/ingest (this MVP) and, per architecture.md §8,
# the data-plane connectors' own pre-push validation are meant to import
# get_validator() from here rather than re-implementing $ref resolution.
# ---------------------------------------------------------------------------

try:
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012
    import jsonschema

    def _retrieve(uri: str) -> Resource:
        filename = uri.rsplit("/", 1)[-1]
        return Resource.from_contents(load_schema(filename), default_specification=DRAFT202012)

    @lru_cache(maxsize=None)
    def _registry() -> "Registry":
        return Registry(retrieve=_retrieve)

    def get_validator(filename_or_entity_type: str) -> "jsonschema.Draft202012Validator":
        """Return a ready-to-use jsonschema validator for a schema file (by
        filename, e.g. 'table.schema.json') or by entity_type (e.g.
        'table'). Raises KeyError-free ValueError for an unknown name so
        callers get a clear error rather than a bare FileNotFoundError."""
        filename = ENTITY_SCHEMA_FILES.get(filename_or_entity_type, filename_or_entity_type)
        try:
            schema = load_schema(filename)
        except FileNotFoundError as exc:
            raise ValueError(f"No such schema: {filename_or_entity_type!r}") from exc
        return jsonschema.Draft202012Validator(schema, registry=_registry())

except ImportError:  # pragma: no cover - jsonschema/referencing are optional
    # for pure schema-file consumers (e.g. a connector that only needs the
    # filenames/paths and does its own validation another way).
    pass
