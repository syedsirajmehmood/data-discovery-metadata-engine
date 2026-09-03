"""Shared pytest fixtures.

Integration tests (relational/graph/search/analytics) talk to the real
services started by ``infra/docker-compose.yml``. Each integration fixture
tries a real connection first and calls ``pytest.skip`` if the service isn't
reachable, so `pytest` is still runnable (skipping only the integration
tests) on a machine without Docker — see control-plane/README.md.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pytest

from storage.types import EntityRecord, EntityType, Operation


@pytest.fixture
def make_entity_record():
    def _make(
        tenant_id: str,
        urn: str,
        entity_type: EntityType,
        payload: dict,
        *,
        data_plane_id: str = "dp-test",
        source_connection_id: str = "src-test",
        operation: Operation = Operation.UPSERT,
        content_hash: Optional[str] = None,
        extracted_at: Optional[datetime] = None,
    ) -> EntityRecord:
        return EntityRecord(
            tenant_id=tenant_id,
            urn=urn,
            entity_type=entity_type,
            data_plane_id=data_plane_id,
            source_connection_id=source_connection_id,
            payload=payload,
            operation=operation,
            content_hash=content_hash,
            extracted_at=extracted_at or datetime.now(timezone.utc),
        )

    return _make
