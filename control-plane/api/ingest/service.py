"""Orchestrates one call to POST /v1/ingest/batches, per architecture.md §2
and §7.3's sequence diagram:

    authenticate, resolve tenant_id from key
    -> validate batch vs shared/schema
    -> check batch_id (idempotency)
    -> enqueue accepted entities to fan-out worker
    -> respond with per-entity accept/reject

This is the piece that ties together auth.py, validation.py, idempotency.py
and workers/fanout/worker.py. router.py (the FastAPI layer) is a thin
adapter on top of this - keeping the orchestration logic testable without
spinning up FastAPI's TestClient for every case.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import List

from fastapi import HTTPException, status

from api.ingest.auth import AuthContext
from api.ingest.idempotency import IdempotencyStore
from api.ingest.models import EntityItem, IngestBatchEnvelope, IngestBatchResponse, RejectedEntity
from api.ingest.validation import validate_entity_payload, validate_envelope_shape
from shared.schema import CURRENT_SCHEMA_VERSION
from workers.fanout.interfaces import AnalyticsStore, CatalogEntity, GraphStore, RelationalStore, SearchIndex
from workers.fanout.worker import FanoutWorker


@dataclass(frozen=True)
class IngestDependencies:
    """Everything service.process_batch() needs beyond the request itself.
    Bundled so router.py has one FastAPI dependency to wire instead of
    five, and so tests can construct this directly with fakes."""

    idempotency_store: IdempotencyStore
    relational_store: RelationalStore
    graph_store: GraphStore
    search_index: SearchIndex
    analytics_store: AnalyticsStore


def _build_catalog_entity(item: EntityItem, auth: AuthContext) -> CatalogEntity:
    """Merge a validated push-payload entity with server-resolved common
    fields into the fully-resolved CatalogEntity the fan-out worker
    expects. See shared/schema/README.md and
    workers/fanout/interfaces.py's CatalogEntity docstring for exactly
    which fields are server-assigned vs. connector-supplied."""
    source_connection_id = item.payload.get("source_connection_id")
    return CatalogEntity(
        id=str(uuid.uuid4()),  # candidate id - RelationalStore keeps the existing one if urn already exists
        urn=item.urn,
        entity_type=item.entity_type,
        tenant_id=auth.tenant_id,
        data_plane_id=auth.data_plane_id,
        source_connection_id=source_connection_id,
        operation=item.operation,
        is_deleted=(item.operation == "delete"),
        content_hash=item.content_hash,
        extracted_at=item.extracted_at,
        first_seen_at=item.extracted_at,  # candidate - preserved by RelationalStore if urn already exists
        last_scraped_at=item.extracted_at,
        payload={k: v for k, v in item.payload.items()},
    )


def process_batch(
    raw_envelope: dict,
    auth: AuthContext,
    deps: IngestDependencies,
) -> IngestBatchResponse:
    # 1. Envelope shape validation against shared/schema (architecture.md §2:
    #    "Validation happens before the idempotency/fan-out step").
    #    Pydantic (models.py) already parsed raw_envelope into a
    #    well-typed object by the time router.py calls this function, but
    #    we additionally validate the raw dict against the canonical JSON
    #    Schema so shared/schema stays authoritative over the wire shape.
    envelope_errors = validate_envelope_shape(raw_envelope)
    if envelope_errors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "envelope_validation_failed", "errors": envelope_errors},
        )

    envelope = IngestBatchEnvelope.model_validate(raw_envelope)

    # 2. data_plane_id in the envelope must match the authenticated key's
    #    registration - never trust the client-supplied value on its own
    #    (architecture.md §2 spells this out for tenant_id; the same
    #    principle applies to data_plane_id, which is also bound to the key).
    if envelope.data_plane_id != auth.data_plane_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "data_plane_id_mismatch",
                "errors": [
                    "envelope.data_plane_id does not match the data_plane_id this API key is registered to"
                ],
            },
        )

    if envelope.schema_version != CURRENT_SCHEMA_VERSION:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "unsupported_schema_version",
                "errors": [f"expected schema_version={CURRENT_SCHEMA_VERSION!r}, got {envelope.schema_version!r}"],
            },
        )

    # 3. Idempotency: a replayed batch_id returns the cached response with
    #    no re-processing (architecture.md §2).
    cached = deps.idempotency_store.get(auth.tenant_id, envelope.batch_id)
    if cached is not None:
        return IngestBatchResponse.model_validate({**cached.response_body, "replayed": True})

    # 4. Per-entity validation -> accept/reject split.
    accepted_entities: List[CatalogEntity] = []
    accepted_urns: List[str] = []
    rejected: List[RejectedEntity] = []
    for item in envelope.entities:
        rejection = validate_entity_payload(item)
        if rejection is not None:
            rejected.append(RejectedEntity(urn=rejection.urn, error=rejection.error, detail=rejection.detail))
            continue
        accepted_entities.append(_build_catalog_entity(item, auth))
        accepted_urns.append(item.urn)

    # 5. Enqueue accepted entities to the fan-out worker. (Synchronous for
    #    MVP - see workers/fanout/worker.py's module docstring for why,
    #    and what a production queue-backed version would change.)
    if accepted_entities:
        worker = FanoutWorker(
            relational_store=deps.relational_store,
            graph_store=deps.graph_store,
            search_index=deps.search_index,
            analytics_store=deps.analytics_store,
            connector_type=envelope.connector_type,
        )
        worker.process_batch(envelope.batch_id, accepted_entities)

    response = IngestBatchResponse(
        batch_id=envelope.batch_id,
        replayed=False,
        accepted=accepted_urns,
        rejected=rejected,
    )

    # 6. Idempotency store records the response body so a retried batch_id
    #    replays it without re-running fan-out.
    deps.idempotency_store.put(auth.tenant_id, envelope.batch_id, response.model_dump())

    return response
