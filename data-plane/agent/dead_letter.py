"""Local on-disk dead-letter queue.

Per architecture.md §2: after retries are exhausted for a batch, it's
written here and retried on the agent's next scheduled cycle -- because the
data plane can't get anything inbound from the control plane, it must
survive the control plane being unreachable for extended periods without
losing scraped metadata.

The original `batch_id` is preserved on disk and reused verbatim on retry,
since idempotency (architecture.md §2) depends on a retried batch reusing
the same `batch_id` as its original attempt-set, no matter how many agent
cycles pass in between.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

from connectors.core.types import NormalizedEntity, iso, utcnow
from .batcher import Batch


class DeadLetterQueue:
    def __init__(self, base_dir: str) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def add(self, batch: Batch) -> Path:
        path = self.base_dir / f"{batch.batch_id}.json"
        data = {
            "batch_id": batch.batch_id,
            "connector_type": batch.connector_type,
            "created_at": iso(batch.created_at),
            "dead_lettered_at": iso(utcnow()),
            "entities": [e.to_envelope_dict() for e in batch.entities],
        }
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp.replace(path)
        return path

    def list_pending(self) -> List[Path]:
        return sorted(self.base_dir.glob("*.json"))

    def load(self, path: Path) -> Batch:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        entities = [NormalizedEntity.from_envelope_dict(e) for e in data["entities"]]
        return Batch(batch_id=data["batch_id"], connector_type=data["connector_type"], entities=entities)

    def remove(self, path: Path) -> None:
        path.unlink(missing_ok=True)

    def __len__(self) -> int:
        return len(self.list_pending())
