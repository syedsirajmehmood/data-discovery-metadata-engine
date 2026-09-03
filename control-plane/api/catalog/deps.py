"""FastAPI dependencies for the catalog read API.

The single most important thing in this file: ``get_tenant_id`` is the ONLY
way any catalog endpoint learns a tenant_id, and it is always resolved
server-side from the caller's API key — never from a path/query parameter
or request body (architecture.md §6 / spec.md NFR-2). Every route in
``router.py`` takes ``tenant_id: str = Depends(get_tenant_id)`` and passes
that (and only that) into the store layer.

Store singletons (``RelationalStore``/``GraphStore``/``SearchIndex``) are
provided via dependency-overridable factory functions so ``app.py`` wires
real clients at startup and tests wire fakes/mocks — see
``control-plane/tests/catalog/test_router.py``.
"""

from __future__ import annotations

import hashlib
from typing import Optional

from fastapi import Depends, Header, HTTPException, status

from storage.graph.store import GraphStore
from storage.relational.store import RelationalStore
from storage.search.store import SearchIndex


def hash_api_key(raw_key: str) -> str:
    """Same hash the (not-FE2-owned) key-issuance flow must use when storing
    ``api_keys.key_hash`` — plain SHA-256 is sufficient here because these
    are high-entropy generated tokens, not user passwords (no need for a
    slow KDF)."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def get_relational_store() -> RelationalStore:  # pragma: no cover - overridden by app wiring
    raise RuntimeError("get_relational_store has no default — override it in app.py or tests")


def get_graph_store() -> GraphStore:  # pragma: no cover - overridden by app wiring
    raise RuntimeError("get_graph_store has no default — override it in app.py or tests")


def get_search_index() -> SearchIndex:  # pragma: no cover - overridden by app wiring
    raise RuntimeError("get_search_index has no default — override it in app.py or tests")


async def get_tenant_id(
    authorization: Optional[str] = Header(default=None),
    store: RelationalStore = Depends(get_relational_store),
) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header (expected 'Bearer <api-key>')",
        )
    raw_key = authorization.split(" ", 1)[1].strip()
    if not raw_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Empty API key")

    tenant_id = store.resolve_tenant_id_for_api_key_hash(hash_api_key(raw_key))
    if tenant_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked API key")
    return tenant_id
