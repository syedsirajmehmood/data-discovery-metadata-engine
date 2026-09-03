"""True end-to-end integration test: real Postgres + real MinIO -> real
AgentRunner (scheduler-free, one `run_cycle()`) -> real `PushClient` doing
an actual HTTP POST -> the local mock ingest server (see
`deploy/mock_ingest_server.py`), asserting on the exact request the mock
server received. This is the closest thing in this test suite to spec.md's
MVP Success Criteria #1 ("real connectors, real sources... pushes extracted
metadata to the control plane").

The mock server is started in-process (a background thread) rather than
via docker-compose so this test can also run standalone with just
Postgres+MinIO up.
"""
import importlib.util
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
import requests

from agent.config import AgentConfig, SourceConfig
from agent.cursor_store import CursorStore
from agent.dead_letter import DeadLetterQueue
from agent.push_client import PushClient
from agent.runner import AgentRunner

pytestmark = pytest.mark.integration


def _load_mock_ingest_module():
    path = Path(__file__).resolve().parents[2] / "deploy" / "mock_ingest_server.py"
    spec = importlib.util.spec_from_file_location("mock_ingest_server", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["mock_ingest_server"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


@pytest.fixture()
def mock_ingest_server(tmp_path):
    module = _load_mock_ingest_module()
    module.EXPECTED_API_KEY = "it-test-key"
    module.RECEIVED_DIR = tmp_path / "received"
    module._SEEN_BATCH_IDS.clear()

    server = ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    # wait for readiness
    for _ in range(50):
        try:
            requests.get(f"http://127.0.0.1:{port}/health", timeout=0.5)
            break
        except requests.RequestException:
            time.sleep(0.1)

    yield f"http://127.0.0.1:{port}", tmp_path / "received"
    server.shutdown()
    server.server_close()


def test_end_to_end_postgres_and_s3_push_to_mock_ingest(pg_config, s3_config, mock_ingest_server, tmp_path):
    base_url, received_dir = mock_ingest_server

    config = AgentConfig(
        control_plane_url=base_url,
        api_key="it-test-key",
        data_plane_id="dp-it-1",
        sources=[
            SourceConfig(connector_type="postgres", source_connection_id="it-postgres", config=pg_config),
            SourceConfig(connector_type="s3", source_connection_id="it-minio", config=s3_config),
        ],
        max_batch_entities=500,
        max_batch_interval_seconds=9999,
        cursor_dir=str(tmp_path / "cursors"),
        dead_letter_dir=str(tmp_path / "dead_letter"),
        retry_max_attempts=2,
    )
    runner = AgentRunner(
        config=config,
        cursor_store=CursorStore(config.cursor_dir),
        push_client=PushClient(config),
        dead_letter=DeadLetterQueue(config.dead_letter_dir),
    )

    report = runner.run_cycle()

    assert report.sources_failed == 0
    assert report.batches_dead_lettered == 0
    assert report.entities_pushed_accepted > 0

    received_files = list(received_dir.glob("*.json"))
    assert len(received_files) >= 2  # one batch per connector_type at minimum

    import json

    connector_types_seen = set()
    for f in received_files:
        envelope = json.loads(f.read_text())
        assert envelope["data_plane_id"] == "dp-it-1"
        assert envelope["schema_version"] == "1.0"
        assert "batch_id" in envelope
        assert "sent_at" in envelope
        connector_types_seen.add(envelope["connector_type"])
        for entity in envelope["entities"]:
            assert entity["urn"]
            assert entity["operation"] in ("upsert", "delete")
            assert entity["content_hash"].startswith("sha256:")
            assert "payload" in entity

    assert connector_types_seen == {"postgres", "s3"}

    # cursors were persisted for both source connections
    assert CursorStore(config.cursor_dir).load("it-postgres").entries
    assert CursorStore(config.cursor_dir).load("it-minio").entries
