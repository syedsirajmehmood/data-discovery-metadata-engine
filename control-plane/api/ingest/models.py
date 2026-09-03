"""Pydantic models for the ingest API, matching shared/schema/envelope.schema.json
and shared/schema/ingest_response.schema.json (task instruction: "Use FastAPI
with Pydantic models generated from or matching the JSON schemas").

These models validate the envelope's OWN shape (batch_id, data_plane_id,
connector_type, schema_version, sent_at, entities[] with urn/entity_type/
operation/content_hash/extracted_at/payload) - i.e. everything that's fixed
regardless of entity_type. `payload`'s CONTENTS are deliberately left as a
plain `dict` here (`EntityItem.payload: Dict[str, Any]`) and validated
separately, dynamically, against shared/schema/<entity_type>.schema.json
via validation.py - that's what keeps entity_type extensible (architecture.md
§2: "new types don't require an envelope change, only a new schema file")
without a Pydantic discriminated-union per entity type that would need a
code change for every new type.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class EntityItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    urn: str = Field(min_length=1)
    entity_type: str
    operation: str
    content_hash: Optional[str] = None
    extracted_at: str
    payload: Dict[str, Any] = Field(default_factory=dict)


class IngestBatchEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: str
    data_plane_id: str = Field(min_length=1)
    connector_type: str = Field(min_length=1)
    schema_version: str
    sent_at: str
    entities: List[EntityItem] = Field(min_length=1)


class RejectedEntity(BaseModel):
    urn: str
    error: str
    detail: str


class IngestBatchResponse(BaseModel):
    batch_id: str
    replayed: bool = False
    accepted: List[str] = Field(default_factory=list)
    rejected: List[RejectedEntity] = Field(default_factory=list)
