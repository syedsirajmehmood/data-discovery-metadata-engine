"""FastAPI router for the push contract endpoint, per architecture.md §2:

    POST https://{control-plane-host}/v1/ingest/batches

Thin adapter: parse the raw JSON body, authenticate (auth.py), delegate to
service.process_batch() for everything else, translate exceptions to the
right HTTP status codes. Business logic lives in service.py so it's
testable without going through FastAPI/HTTP at all.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError

from api.ingest.auth import AuthContext
from api.ingest.models import IngestBatchResponse
from api.ingest.service import IngestDependencies, process_batch

router = APIRouter(prefix="/v1/ingest", tags=["ingest"])


def get_auth_context() -> AuthContext:
    """Placeholder dependency - app.py MUST override this via
    `app.dependency_overrides[get_auth_context] = auth.make_auth_dependency(registry)`
    before serving requests. Kept as a real function (not inline
    Depends(lambda...)) so tests can target it precisely with
    dependency_overrides too."""
    raise HTTPException(status_code=500, detail="auth dependency not configured")


def get_ingest_dependencies() -> IngestDependencies:
    """Placeholder dependency - app.py MUST override this with a real
    IngestDependencies (idempotency store + the 4 storage-interface
    implementations)."""
    raise HTTPException(status_code=500, detail="ingest dependencies not configured")


@router.post("/batches", response_model=IngestBatchResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_batches(
    request: Request,
    auth: AuthContext = Depends(get_auth_context),
    deps: IngestDependencies = Depends(get_ingest_dependencies),
) -> IngestBatchResponse:
    body_bytes = await request.body()
    try:
        raw_envelope = json.loads(body_bytes)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "malformed_json", "errors": [str(exc)]},
        ) from exc

    if not isinstance(raw_envelope, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "malformed_envelope", "errors": ["request body must be a JSON object"]},
        )

    try:
        return process_batch(raw_envelope, auth, deps)
    except ValidationError as exc:
        # Should be rare (shared/schema validation runs first inside
        # process_batch and should already have caught malformed shape),
        # but Pydantic's own parse is a second line of defense.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "envelope_validation_failed", "errors": [str(exc)]},
        ) from exc
