"""Bearer API-key authentication for the ingest API.

architecture.md §2: "Each data-plane installation registers against the
control plane once (during setup) and receives a long-lived, revocable API
key, scoped to exactly one (tenant_id, data_plane_id) pair. Sent as
`Authorization: Bearer <key>` on every request. `tenant_id` is never
accepted from the request body - the ingest API resolves it server-side
from the API key."

This module owns exactly that resolution step. It deliberately does NOT
own where API keys are actually stored/looked up (that's Postgres -
`api_keys` table per architecture.md §4/§8, owned by FE2's
`control-plane/storage/relational/`) - FE1 owns ingest orchestration, not
storage clients. `APIKeyRegistry` below is a small Protocol seam (same
pattern as workers/fanout/interfaces.py) plus an in-memory implementation
so this module and its tests are runnable standalone; production wiring
swaps in a real lookup backed by FE2's relational store.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

try:
    from typing import Protocol
except ImportError:  # pragma: no cover
    from typing_extensions import Protocol  # type: ignore

from fastapi import Header, HTTPException, status


@dataclass(frozen=True)
class AuthContext:
    """The only thing route handlers ever get to know about "who is
    calling" - resolved server-side, never from the request body."""

    tenant_id: str
    data_plane_id: str
    api_key_id: str


class APIKeyRegistry(Protocol):
    """Looks up an API key's (tenant_id, data_plane_id) binding. Returns
    None for an unknown/revoked key - callers must not distinguish
    "unknown" from "revoked" in the HTTP response (both are a 401), to
    avoid leaking which keys ever existed."""

    def resolve(self, api_key: str) -> Optional[AuthContext]: ...


class InMemoryAPIKeyRegistry:
    """Test/dev-only registry. Production registers real keys against
    Postgres via FE2's relational store; this class exists so
    control-plane/api/ingest is independently testable per this task's
    scope (FE1 does not own control-plane/storage/)."""

    def __init__(self) -> None:
        self._keys: Dict[str, AuthContext] = {}

    def register(self, api_key: str, *, tenant_id: str, data_plane_id: str, api_key_id: str) -> None:
        self._keys[api_key] = AuthContext(
            tenant_id=tenant_id, data_plane_id=data_plane_id, api_key_id=api_key_id
        )

    def revoke(self, api_key: str) -> None:
        self._keys.pop(api_key, None)

    def resolve(self, api_key: str) -> Optional[AuthContext]:
        return self._keys.get(api_key)


def extract_bearer_token(authorization: Optional[str]) -> str:
    """Parse `Authorization: Bearer <token>`, raising 401 on anything else
    (missing header, wrong scheme, empty token)."""
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing_authorization_header")
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_authorization_scheme")
    return parts[1].strip()


def make_auth_dependency(registry: APIKeyRegistry):
    """Build a FastAPI dependency bound to a specific registry instance
    (so tests can inject an InMemoryAPIKeyRegistry pre-loaded with fixture
    keys, and production wiring can inject the real one) - see app.py."""

    def _dependency(authorization: Optional[str] = Header(default=None)) -> AuthContext:
        token = extract_bearer_token(authorization)
        ctx = registry.resolve(token)
        if ctx is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_or_revoked_api_key")
        return ctx

    return _dependency
