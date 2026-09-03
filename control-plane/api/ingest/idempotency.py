"""Idempotency store for the ingest API, per architecture.md §2:

    "The ingest API checks `batch_id` against a short-TTL idempotency
    store (Postgres table, TTL a few days) before processing. A replayed
    `batch_id` returns the cached response with no re-processing - safe
    to retry blindly."

architecture.md names Postgres as the eventual backing store, but that's
FE2's `control-plane/storage/relational/` - FE1 owns the ingest API's
idempotency *logic* (check-before-process, cache-after-process, TTL
expiry), not the storage client. `IdempotencyStore` below is a small
Protocol seam (same pattern as auth.py's APIKeyRegistry and
workers/fanout/interfaces.py) with an in-memory TTL implementation so
this module's behavior is fully testable now; swapping in a real
Postgres-backed table later is a one-class change at the wiring site
(app.py), not a change to service.py's logic.

Keyed by `(tenant_id, batch_id)`, not `batch_id` alone: batch_id is
client-generated per data-plane install, so scoping by tenant closes the
(astronomically unlikely, but free to close) hole where two different
tenants' agents independently generate the same UUID.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

try:
    from typing import Protocol
except ImportError:  # pragma: no cover
    from typing_extensions import Protocol  # type: ignore

DEFAULT_TTL = timedelta(days=3)  # "a few days" per architecture.md §2


def _key(tenant_id: str, batch_id: str) -> str:
    return f"{tenant_id}:{batch_id}"


@dataclass(frozen=True)
class IdempotencyRecord:
    response_body: dict


class IdempotencyStore(Protocol):
    def get(self, tenant_id: str, batch_id: str) -> Optional[IdempotencyRecord]: ...

    def put(self, tenant_id: str, batch_id: str, response_body: dict) -> None: ...


class InMemoryIdempotencyStore:
    """Dev/test implementation. Not shared across processes - fine for
    this task's scope (proving the ingest path end-to-end); a real
    deployment needs the Postgres-backed table architecture.md specifies,
    shared across all ingest API replicas."""

    def __init__(self, ttl: timedelta = DEFAULT_TTL) -> None:
        self._ttl = ttl
        self._records: Dict[str, Tuple[IdempotencyRecord, datetime]] = {}

    def get(self, tenant_id: str, batch_id: str) -> Optional[IdempotencyRecord]:
        key = _key(tenant_id, batch_id)
        entry = self._records.get(key)
        if entry is None:
            return None
        record, stored_at = entry
        if datetime.now(timezone.utc) - stored_at > self._ttl:
            del self._records[key]
            return None
        return record

    def put(self, tenant_id: str, batch_id: str, response_body: dict) -> None:
        key = _key(tenant_id, batch_id)
        self._records[key] = (IdempotencyRecord(response_body=response_body), datetime.now(timezone.utc))
