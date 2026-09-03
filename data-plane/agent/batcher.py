"""Batching: the agent (not each connector) owns this, per architecture.md
§2. Flush on whichever comes first: `max_batch_entities` (default 500) or
`max_batch_interval` (default 60s).

`batch_id` is minted exactly once, when a `Batch` is closed off here --
this is the "attempt-set" id a retried push must reuse (architecture.md §2
idempotency).
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, List, Optional

from connectors.core.types import NormalizedEntity, utcnow


@dataclass
class Batch:
    batch_id: str
    connector_type: str
    entities: List[NormalizedEntity]
    created_at: datetime = field(default_factory=utcnow)


class Batcher:
    """Single-connector-cycle batcher. One instance is used per source
    connection's scrape cycle (see `agent/runner.py`)."""

    def __init__(
        self,
        max_entities: int = 500,
        max_interval_seconds: float = 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_entities = max_entities
        self.max_interval_seconds = max_interval_seconds
        self._clock = clock
        self._buffer: List[NormalizedEntity] = []
        self._connector_type: Optional[str] = None
        self._batch_started_at: Optional[float] = None

    def add(self, connector_type: str, entity: NormalizedEntity) -> Optional[Batch]:
        """Add one entity. Returns a closed `Batch` if adding this entity
        crossed the size threshold, else None (caller should also poll
        `maybe_flush_on_interval()` periodically for the time-based
        trigger, since that isn't driven by `add()` calls alone)."""
        if self._connector_type is None:
            self._connector_type = connector_type
            self._batch_started_at = self._clock()
        elif self._connector_type != connector_type:
            raise ValueError(
                f"Batcher instance received entities from two connector_types "
                f"({self._connector_type!r} and {connector_type!r}) -- use one "
                f"Batcher per connector/source-connection cycle."
            )
        self._buffer.append(entity)
        if len(self._buffer) >= self.max_entities:
            return self._close()
        return None

    def maybe_flush_on_interval(self) -> Optional[Batch]:
        if (
            self._buffer
            and self._batch_started_at is not None
            and (self._clock() - self._batch_started_at) >= self.max_interval_seconds
        ):
            return self._close()
        return None

    def flush(self) -> Optional[Batch]:
        """Force-close whatever's buffered (end of a discovery cycle)."""
        if not self._buffer:
            return None
        return self._close()

    def __len__(self) -> int:
        return len(self._buffer)

    def _close(self) -> Batch:
        batch = Batch(
            batch_id=str(uuid.uuid4()),
            connector_type=self._connector_type,  # type: ignore[arg-type]
            entities=self._buffer,
        )
        self._buffer = []
        self._connector_type = None
        self._batch_started_at = None
        return batch
