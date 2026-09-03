"""Local on-disk persistence for connector cursors, keyed by
`source_connection_id`. Purely data-plane-local state -- never sent to the
control plane."""
from __future__ import annotations

import json
import re
from pathlib import Path

from connectors.core.types import Cursor, iso, utcnow

_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")


def _safe_name(source_connection_id: str) -> str:
    return _UNSAFE.sub("_", source_connection_id)


class CursorStore:
    def __init__(self, base_dir: str) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, source_connection_id: str) -> Path:
        return self.base_dir / f"{_safe_name(source_connection_id)}.json"

    def load(self, source_connection_id: str) -> Cursor:
        path = self._path(source_connection_id)
        if not path.exists():
            return Cursor.empty(source_connection_id)
        with open(path, "r", encoding="utf-8") as f:
            return Cursor.from_dict(json.load(f))

    def save(self, cursor: Cursor) -> None:
        cursor.updated_at = iso(utcnow())
        path = self._path(cursor.source_connection_id)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cursor.to_dict(), f, indent=2)
        tmp.replace(path)  # atomic on POSIX -- avoids a torn cursor file on crash
