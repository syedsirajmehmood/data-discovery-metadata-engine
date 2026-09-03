import requests

from connectors.core.types import EntityType, NormalizedEntity, Operation
from agent.batcher import Batch
from agent.config import AgentConfig
from agent.push_client import PushClient


class FakeResponse:
    def __init__(self, status_code, json_body=None, text=""):
        self.status_code = status_code
        self._json_body = json_body
        self.text = text

    def json(self):
        if self._json_body is None:
            raise ValueError("no json body")
        return self._json_body


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def make_config(**overrides):
    defaults = dict(
        control_plane_url="https://cp.example.com",
        api_key="secret-key-123",
        data_plane_id="dp-1",
        retry_max_attempts=4,
        retry_base_seconds=1,
        retry_cap_seconds=10,
        schema_version="1.0",
    )
    defaults.update(overrides)
    return AgentConfig(**defaults)


def make_batch(n=1, connector_type="postgres"):
    entities = [
        NormalizedEntity(
            urn=f"urn:postgres:h:d:s.t{i}",
            entity_type=EntityType.TABLE.value,
            operation=Operation.UPSERT.value,
            payload={"table_name": f"t{i}"},
        )
        for i in range(n)
    ]
    return Batch(batch_id="batch-uuid-1", connector_type=connector_type, entities=entities)


def make_client(config, responses):
    sleeps = []
    session = FakeSession(responses)
    client = PushClient(config, session=session, sleep_fn=lambda d: sleeps.append(d), random_fn=lambda: 0.0)
    return client, session, sleeps


def test_push_success_first_attempt_no_sleep():
    config = make_config()
    client, session, sleeps = make_client(
        config, [FakeResponse(200, {"batch_id": "batch-uuid-1", "accepted": ["urn:1"], "rejected": []})]
    )
    result = client.push(make_batch())
    assert result.success is True
    assert result.accepted == ["urn:1"]
    assert result.attempts == 1
    assert sleeps == []


def test_envelope_and_auth_header_shape_matches_architecture_contract():
    config = make_config()
    client, session, _ = make_client(config, [FakeResponse(200, {"batch_id": "batch-uuid-1", "accepted": [], "rejected": []})])
    batch = make_batch(n=2)
    client.push(batch)

    call = session.calls[0]
    assert call["url"] == "https://cp.example.com/v1/ingest/batches"
    assert call["headers"]["Authorization"] == "Bearer secret-key-123"
    envelope = call["json"]
    assert envelope["batch_id"] == "batch-uuid-1"
    assert envelope["data_plane_id"] == "dp-1"
    assert envelope["connector_type"] == "postgres"
    assert envelope["schema_version"] == "1.0"
    assert "sent_at" in envelope
    assert len(envelope["entities"]) == 2
    entity0 = envelope["entities"][0]
    assert set(entity0.keys()) == {"urn", "entity_type", "operation", "content_hash", "extracted_at", "payload"}


def test_retries_transport_failures_with_same_batch_id():
    config = make_config()
    client, session, sleeps = make_client(
        config,
        [
            FakeResponse(503, text="server error"),
            FakeResponse(502, text="bad gateway"),
            FakeResponse(200, {"batch_id": "batch-uuid-1", "accepted": ["urn:1"], "rejected": []}),
        ],
    )
    result = client.push(make_batch())
    assert result.success is True
    assert result.attempts == 3
    assert len(sleeps) == 2  # backoff before attempt 2 and attempt 3
    # every retried POST reused the exact same batch_id (idempotency)
    assert all(call["json"]["batch_id"] == "batch-uuid-1" for call in session.calls)


def test_backoff_is_exponential_and_capped():
    config = make_config(retry_base_seconds=5, retry_cap_seconds=12, retry_max_attempts=5)
    client, session, sleeps = make_client(
        config,
        [FakeResponse(503), FakeResponse(503), FakeResponse(503), FakeResponse(200, {"accepted": [], "rejected": []})],
    )
    client.push(make_batch())
    # base * 2^(attempt-1): 5, 10, capped at 12 (would be 20 uncapped)
    assert sleeps == [5, 10, 12]


def test_exhausts_retries_and_reports_failure():
    config = make_config(retry_max_attempts=3)
    client, session, sleeps = make_client(config, [FakeResponse(503)] * 3)
    result = client.push(make_batch())
    assert result.success is False
    assert result.attempts == 3
    assert "exhausted 3 attempts" in result.error
    assert len(sleeps) == 2  # no sleep after the final attempt


def test_connection_error_is_treated_as_transport_failure_and_retried():
    config = make_config(retry_max_attempts=3)
    client, session, sleeps = make_client(
        config,
        [
            requests.exceptions.ConnectionError("refused"),
            FakeResponse(200, {"accepted": ["urn:1"], "rejected": []}),
        ],
    )
    result = client.push(make_batch())
    assert result.success is True
    assert result.attempts == 2


def test_4xx_is_not_retried_treated_as_data_quality_bug():
    config = make_config(retry_max_attempts=5)
    client, session, sleeps = make_client(
        config,
        [FakeResponse(400, {"batch_id": "batch-uuid-1", "rejected": [{"urn": "urn:1", "error": "schema_validation_failed"}]})],
    )
    result = client.push(make_batch())
    assert result.success is False
    assert result.status_code == 400
    assert result.rejected[0]["urn"] == "urn:1"
    assert len(session.calls) == 1  # no retry
    assert sleeps == []


def test_401_auth_failure_is_not_retried():
    config = make_config(retry_max_attempts=5)
    client, session, sleeps = make_client(config, [FakeResponse(401, text="invalid api key")])
    result = client.push(make_batch())
    assert result.success is False
    assert result.status_code == 401
    assert len(session.calls) == 1


def test_empty_batch_is_a_noop_and_never_hits_network():
    config = make_config()
    client, session, sleeps = make_client(config, [])
    batch = Batch(batch_id="b1", connector_type="postgres", entities=[])
    result = client.push(batch)
    assert result.success is True
    assert session.calls == []
