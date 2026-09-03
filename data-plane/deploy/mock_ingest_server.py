#!/usr/bin/env python3
"""THROWAWAY local-dev stub of the control-plane ingest API
(`POST /v1/ingest/batches`), for exercising the agent's push client against
*something* without needing the real control plane running.

This is NOT the real ingest API -- that's FE1's `control-plane/api/ingest/`
(out of this engineer's scope, not touched here). It implements just enough
of the architecture.md §2 contract (Bearer auth, batch_id echo, per-entity
accept/reject response shape) for local docker-compose testing and the demo
script in the README. Stdlib-only (`http.server`) so it adds zero
dependencies to the agent's own requirements.

Every accepted batch is written to disk under `/data/received/<batch_id>.json`
so you can inspect exactly what the agent pushed.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

EXPECTED_API_KEY = os.environ.get("MOCK_API_KEY", "local-dev-key")
RECEIVED_DIR = Path(os.environ.get("MOCK_RECEIVED_DIR", "/data/received"))
_SEEN_BATCH_IDS: dict = {}

_URN_RE = re.compile(r"^urn:")


class Handler(BaseHTTPRequestHandler):
    server_version = "MockIngestAPI/0.1"

    def _send_json(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self._send_json(200, {"ok": True})
            return
        self._send_json(404, {"error": "not_found"})

    def do_POST(self):  # noqa: N802
        if self.path != "/v1/ingest/batches":
            self._send_json(404, {"error": "not_found"})
            return

        auth = self.headers.get("Authorization", "")
        if auth != f"Bearer {EXPECTED_API_KEY}":
            self._send_json(401, {"error": "unauthorized", "detail": "bad or missing bearer token"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""
        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError as exc:
            self._send_json(400, {"error": "malformed_json", "detail": str(exc)})
            return

        for required in ("batch_id", "data_plane_id", "connector_type", "schema_version", "entities"):
            if required not in envelope:
                self._send_json(400, {"error": "schema_validation_failed", "detail": f"missing {required!r}"})
                return

        batch_id = envelope["batch_id"]

        # Idempotency replay, per architecture.md §2.
        if batch_id in _SEEN_BATCH_IDS:
            self._send_json(200, _SEEN_BATCH_IDS[batch_id])
            return

        accepted, rejected = [], []
        for entity in envelope["entities"]:
            urn = entity.get("urn", "")
            if not _URN_RE.match(urn) or "payload" not in entity:
                rejected.append({"urn": urn, "error": "schema_validation_failed", "detail": "missing urn/payload"})
            else:
                accepted.append(urn)

        response = {"batch_id": batch_id, "accepted": accepted, "rejected": rejected}
        _SEEN_BATCH_IDS[batch_id] = response

        RECEIVED_DIR.mkdir(parents=True, exist_ok=True)
        out_path = RECEIVED_DIR / f"{batch_id}-{uuid.uuid4().hex[:8]}.json"
        out_path.write_text(json.dumps(envelope, indent=2))

        print(
            f"[mock-ingest] batch={batch_id} connector={envelope['connector_type']} "
            f"entities={len(envelope['entities'])} accepted={len(accepted)} rejected={len(rejected)} "
            f"-> {out_path}"
        )
        self._send_json(202, response)

    def log_message(self, fmt, *args):  # quieter default access log
        pass


def main() -> None:
    port = int(os.environ.get("MOCK_PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"[mock-ingest] listening on :{port}, expecting Bearer {EXPECTED_API_KEY!r}")
    server.serve_forever()


if __name__ == "__main__":
    main()
