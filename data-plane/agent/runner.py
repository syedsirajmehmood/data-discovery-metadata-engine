"""The agent runner: the only thing that knows about scheduling, batching,
the push client, retries, and the dead-letter queue (architecture.md §3).
Drives any `BaseConnector` the same way:
`discover -> extract_metadata (+ extract_lineage) -> hand to batcher`.
A new connector = a new registry entry, zero changes to this file.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from connectors.core.base import BaseConnector
from connectors.core.types import NormalizedEntity

from .batcher import Batch, Batcher
from .config import AgentConfig, SourceConfig
from .cursor_store import CursorStore
from .dead_letter import DeadLetterQueue
from .push_client import PushClient
from .registry import build_connector
from .validation import validate_entity

logger = logging.getLogger("data_plane.agent")


@dataclass
class CycleReport:
    sources_run: int = 0
    sources_failed: int = 0
    entities_discovered: int = 0
    entities_invalid: int = 0
    entities_pushed_accepted: int = 0
    entities_pushed_rejected: int = 0
    batches_pushed: int = 0
    batches_dead_lettered: int = 0
    dead_letters_retried_ok: int = 0
    dead_letters_still_failing: int = 0
    errors: List[str] = field(default_factory=list)


class AgentRunner:
    def __init__(
        self,
        config: AgentConfig,
        cursor_store: CursorStore,
        push_client: PushClient,
        dead_letter: DeadLetterQueue,
        connector_factory: Callable[[str], BaseConnector] = build_connector,
    ) -> None:
        self.config = config
        self.cursor_store = cursor_store
        self.push_client = push_client
        self.dead_letter = dead_letter
        self.connector_factory = connector_factory

    def run_cycle(self) -> CycleReport:
        report = CycleReport()
        self._retry_dead_letters(report)
        for source in self.config.sources:
            report.sources_run += 1
            try:
                self._run_source(source, report)
            except Exception as exc:  # noqa: BLE001 - one source failing must not sink the cycle
                report.sources_failed += 1
                msg = f"source={source.source_connection_id} ({source.connector_type}) failed: {exc}"
                report.errors.append(msg)
                logger.exception(msg)
        return report

    # -- internal ----------------------------------------------------------

    def _retry_dead_letters(self, report: CycleReport) -> None:
        for path in self.dead_letter.list_pending():
            try:
                batch = self.dead_letter.load(path)
            except Exception as exc:  # noqa: BLE001
                logger.exception("dead-letter file %s is unreadable, leaving in place: %s", path, exc)
                continue
            result = self.push_client.push(batch)
            if result.success:
                self.dead_letter.remove(path)
                report.dead_letters_retried_ok += 1
                logger.info("dead-lettered batch %s retried successfully", batch.batch_id)
            else:
                report.dead_letters_still_failing += 1
                logger.warning("dead-lettered batch %s still failing: %s", batch.batch_id, result.error)

    def _run_source(self, source: SourceConfig, report: CycleReport) -> None:
        connector = self.connector_factory(source.connector_type)
        connector.connect(source.config)

        cursor = self.cursor_store.load(source.source_connection_id)
        connector.set_cursor(cursor)

        batcher = Batcher(
            max_entities=self.config.max_batch_entities,
            max_interval_seconds=self.config.max_batch_interval_seconds,
        )

        def handle_full_batch(batch: Optional[Batch]) -> None:
            if batch is None:
                return
            self._push_or_dead_letter(batch, report)

        for raw_entity in connector.discover():
            normalized = connector.extract_metadata(raw_entity)
            report.entities_discovered += 1
            self._validate_and_batch(source.connector_type, normalized, batcher, report, handle_full_batch)

        for edge in connector.extract_lineage():
            normalized = edge.to_normalized_entity()
            report.entities_discovered += 1
            self._validate_and_batch(source.connector_type, normalized, batcher, report, handle_full_batch)

        handle_full_batch(batcher.flush())

        self.cursor_store.save(connector.get_cursor())

    def _validate_and_batch(
        self,
        connector_type: str,
        normalized: NormalizedEntity,
        batcher: Batcher,
        report: CycleReport,
        handle_full_batch: Callable[[Optional[Batch]], None],
    ) -> None:
        errors = validate_entity(normalized)
        if errors:
            report.entities_invalid += 1
            logger.warning("dropping invalid entity urn=%s: %s", normalized.urn, "; ".join(errors))
            return
        full = batcher.add(connector_type, normalized)
        handle_full_batch(full)
        handle_full_batch(batcher.maybe_flush_on_interval())

    def _push_or_dead_letter(self, batch: Batch, report: CycleReport) -> None:
        result = self.push_client.push(batch)
        report.batches_pushed += 1
        if result.success:
            report.entities_pushed_accepted += len(result.accepted)
            report.entities_pushed_rejected += len(result.rejected)
            if result.rejected:
                logger.warning(
                    "batch %s: %d entities rejected by ingest API: %s",
                    batch.batch_id,
                    len(result.rejected),
                    result.rejected,
                )
        else:
            report.batches_dead_lettered += 1
            path = self.dead_letter.add(batch)
            logger.error(
                "batch %s failed to push after retries (%s); dead-lettered to %s",
                batch.batch_id,
                result.error,
                path,
            )
