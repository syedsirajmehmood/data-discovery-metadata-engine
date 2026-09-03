"""BaseConnector ABC — exactly the shape frozen in architecture.md §3.

A new source connector = a new class implementing this interface,
registered in agent config. Zero changes to `data-plane/agent/` required.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator

from .types import Cursor, HealthStatus, LineageEdge, NormalizedEntity, RawEntity


class BaseConnector(ABC):
    #: short machine-readable identifier, e.g. "postgres" / "s3". Used to
    #: build urns and as the envelope's `connector_type` field.
    connector_type: str = "base"

    @abstractmethod
    def connect(self, config: dict) -> None:
        """Establish connectivity using `config`. Raises on bad creds/
        connectivity — the agent runner treats a raised exception here as a
        fatal setup error for this source connection's cycle, not a batch
        failure."""
        raise NotImplementedError

    @abstractmethod
    def health_check(self) -> HealthStatus:
        raise NotImplementedError

    @abstractmethod
    def discover(self) -> Iterator[RawEntity]:
        """Enumerate what exists at the source right now, INCLUDING
        synthetic tombstone `RawEntity`s (see `RawEntity.tombstone`) for
        anything the cursor previously saw but that vanished this cycle.
        This is what makes schema-drift-as-delete a discovery-time concern,
        not an error path."""
        raise NotImplementedError

    @abstractmethod
    def extract_metadata(self, entity: RawEntity) -> NormalizedEntity:
        """Turn one RawEntity into a NormalizedEntity ready for the
        batcher. Must handle `entity.tombstone is True` by returning a
        `NormalizedEntity` with `operation="delete"`."""
        raise NotImplementedError

    def extract_lineage(self) -> Iterator[LineageEdge]:
        """Default: empty. Not all sources have a native lineage signal
        (e.g. Postgres in the MVP). Sources that do (dbt, Airflow, later)
        override this."""
        return iter(())

    @abstractmethod
    def get_cursor(self) -> Cursor:
        """Return the connector's current cursor state (for incremental
        scrape). The agent persists this to local disk after a cycle."""
        raise NotImplementedError

    @abstractmethod
    def set_cursor(self, cursor: Cursor) -> None:
        """Load a previously-persisted cursor before a scrape cycle
        begins."""
        raise NotImplementedError
