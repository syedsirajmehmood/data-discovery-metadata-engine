"""In-process scheduler: configurable interval, default 6h (spec.md NFR-1).

Deliberately minimal -- per architecture.md §5, the agent can equally be
driven by a k8s CronJob instead of this in-process loop (see `main.py`'s
`--once` flag), so this class stays a thin, swappable convenience rather
than load-bearing infrastructure.
"""
from __future__ import annotations

import threading
import time
from typing import Callable


class Scheduler:
    def __init__(
        self,
        interval_seconds: float,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.interval_seconds = interval_seconds
        self._sleep_fn = sleep_fn
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run_forever(self, callback: Callable[[], None]) -> None:
        """Runs `callback()` immediately, then again every
        `interval_seconds`, until `stop()` is called."""
        while not self._stop.is_set():
            callback()
            if self._stop.is_set():
                break
            self._sleep_fn(self.interval_seconds)
