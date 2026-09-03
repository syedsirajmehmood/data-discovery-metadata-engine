"""Push client: `POST /v1/ingest/batches`, exactly per architecture.md §2's
request envelope. Bearer API-key auth, `batch_id` UUID per attempt-set
reused on retry for idempotency, exponential backoff + jitter on transport
failures (5xx / timeout / connection error), no blind retry on a
per-entity/batch validation rejection (400 with per-entity errors is a
data-quality bug in the connector, not a transport failure -- per
architecture.md §2).
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import requests

from connectors.core.types import iso, utcnow
from .batcher import Batch
from .config import AgentConfig


@dataclass
class PushResult:
    success: bool
    batch_id: str
    accepted: List[str] = field(default_factory=list)
    rejected: List[Dict[str, Any]] = field(default_factory=list)
    status_code: Optional[int] = None
    error: Optional[str] = None
    attempts: int = 0


class PushClient:
    def __init__(
        self,
        config: AgentConfig,
        session: Optional[requests.Session] = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        random_fn: Callable[[], float] = random.random,
    ) -> None:
        self.config = config
        self.session = session or requests.Session()
        self._sleep_fn = sleep_fn
        self._random_fn = random_fn

    def build_envelope(self, batch: Batch) -> Dict[str, Any]:
        return {
            "batch_id": batch.batch_id,
            "data_plane_id": self.config.data_plane_id,
            "connector_type": batch.connector_type,
            "schema_version": self.config.schema_version,
            "sent_at": iso(utcnow()),
            "entities": [e.to_envelope_dict() for e in batch.entities],
        }

    def push(self, batch: Batch) -> PushResult:
        if not batch.entities:
            return PushResult(success=True, batch_id=batch.batch_id, attempts=0)

        url = f"{self.config.control_plane_url.rstrip('/')}/v1/ingest/batches"
        envelope = self.build_envelope(batch)
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

        last_error: Optional[str] = None
        attempts = 0
        while attempts < self.config.retry_max_attempts:
            attempts += 1
            try:
                resp = self.session.post(
                    url, json=envelope, headers=headers, timeout=self.config.request_timeout_seconds
                )
            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempts < self.config.retry_max_attempts:
                    self._backoff_sleep(attempts)
                continue

            if resp.status_code in (200, 202):
                body = self._safe_json(resp)
                return PushResult(
                    success=True,
                    batch_id=body.get("batch_id", batch.batch_id),
                    accepted=body.get("accepted", []),
                    rejected=body.get("rejected", []),
                    status_code=resp.status_code,
                    attempts=attempts,
                )

            if 400 <= resp.status_code < 500:
                # Auth failure or malformed-batch rejection: the API
                # processed (or definitively refused) the request. Per
                # architecture.md §2 this is a data-quality/config bug, not
                # a transport failure -- do not blind-retry.
                body = self._safe_json(resp)
                return PushResult(
                    success=False,
                    batch_id=batch.batch_id,
                    rejected=body.get("rejected", []),
                    status_code=resp.status_code,
                    error=body.get("error") or resp.text[:1000],
                    attempts=attempts,
                )

            # 5xx -> transport failure, retry with backoff.
            last_error = f"HTTP {resp.status_code}: {resp.text[:500]}"
            if attempts < self.config.retry_max_attempts:
                self._backoff_sleep(attempts)

        return PushResult(
            success=False,
            batch_id=batch.batch_id,
            status_code=None,
            error=f"exhausted {attempts} attempts; last_error={last_error}",
            attempts=attempts,
        )

    @staticmethod
    def _safe_json(resp: "requests.Response") -> Dict[str, Any]:
        try:
            return resp.json()
        except ValueError:
            return {}

    def _backoff_sleep(self, attempt: int) -> None:
        # base 5s, cap ~5min, exponential with jitter (architecture.md §2)
        base_delay = min(self.config.retry_cap_seconds, self.config.retry_base_seconds * (2 ** (attempt - 1)))
        jitter = base_delay * 0.2 * self._random_fn()
        self._sleep_fn(base_delay + jitter)
