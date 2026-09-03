"""AgentRunner orchestration tests using an in-memory fake BaseConnector
(no real Postgres/S3/network). Exercises: discover -> extract_metadata ->
validate -> batch -> push, cursor persistence, dead-lettering on push
failure, dead-letter retry on the next cycle, and that an invalid entity is
dropped rather than pushed -- all without touching a real connector, which
is the whole point of the BaseConnector seam per architecture.md §3.
"""
from typing import Iterator, List

from connectors.core.base import BaseConnector
from connectors.core.types import Cursor, EntityType, HealthStatus, NormalizedEntity, Operation, RawEntity
from agent.config import AgentConfig, SourceConfig
from agent.cursor_store import CursorStore
from agent.dead_letter import DeadLetterQueue
from agent.push_client import PushClient
from agent.runner import AgentRunner


class FakeConnector(BaseConnector):
    connector_type = "fake"

    def __init__(self, raw_entities: List[RawEntity], invalid_urn_for=None):
        self._raw_entities = raw_entities
        self._cursor = Cursor.empty("unset")
        self.connected_with = None
        self.invalid_urn_for = invalid_urn_for  # if set, make this urn's entity invalid

    def connect(self, config: dict) -> None:
        self.connected_with = config

    def health_check(self) -> HealthStatus:
        return HealthStatus(ok=True)

    def discover(self) -> Iterator[RawEntity]:
        return iter(self._raw_entities)

    def extract_metadata(self, entity: RawEntity) -> NormalizedEntity:
        # Real connectors (Postgres/S3) record cursor state themselves
        # inside extract_metadata -- mirror that here so runner tests that
        # assert on persisted cursor state exercise the real contract.
        if entity.tombstone:
            normalized = NormalizedEntity(
                urn=entity.key,
                entity_type=entity.entity_type,
                operation=Operation.DELETE.value,
                payload={"source_connection_id": "src-1"},
            )
            self._cursor.forget(normalized.urn)
            return normalized
        payload = {
            "source_type": "fake",
            "source_connection_id": "src-1",
            "database_name": "d",
            "schema_name": "s",
            "table_name": entity.raw["name"],
            "fully_qualified_name": f"fake://{entity.raw['name']}",
            "object_type": "table",
        }
        urn = f"urn:fake:h:d:s.{entity.raw['name']}"
        if self.invalid_urn_for and urn == self.invalid_urn_for:
            del payload["fully_qualified_name"]  # make it fail validation
        normalized = NormalizedEntity(urn=urn, entity_type=EntityType.TABLE.value, operation=Operation.UPSERT.value, payload=payload)
        self._cursor.record(normalized.urn, normalized.entity_type, normalized.content_hash, when=normalized.extracted_at)
        return normalized

    def get_cursor(self) -> Cursor:
        return self._cursor

    def set_cursor(self, cursor: Cursor) -> None:
        self._cursor = cursor


class FakePushClient:
    """Drop-in replacement for PushClient that records what it was asked
    to push and lets tests script success/failure per call."""

    def __init__(self, script=None):
        self.calls = []
        self._script = list(script) if script else None

    def push(self, batch):
        self.calls.append(batch)
        if self._script is not None:
            return self._script.pop(0)
        # default: always succeed, accept everything
        from agent.push_client import PushResult

        return PushResult(success=True, batch_id=batch.batch_id, accepted=[e.urn for e in batch.entities])


def make_config(tmp_path, **overrides):
    defaults = dict(
        control_plane_url="https://cp.example.com",
        api_key="key",
        data_plane_id="dp-1",
        sources=[SourceConfig(connector_type="fake", source_connection_id="src-1", config={})],
        max_batch_entities=500,
        max_batch_interval_seconds=9999,
        cursor_dir=str(tmp_path / "cursors"),
        dead_letter_dir=str(tmp_path / "dead_letter"),
    )
    defaults.update(overrides)
    return AgentConfig(**defaults)


def test_full_cycle_pushes_discovered_entities_and_saves_cursor(tmp_path):
    raws = [RawEntity(entity_type=EntityType.TABLE.value, key="t1", raw={"name": "t1"})]
    connector = FakeConnector(raws)
    config = make_config(tmp_path)
    push_client = FakePushClient()
    runner = AgentRunner(
        config=config,
        cursor_store=CursorStore(config.cursor_dir),
        push_client=push_client,
        dead_letter=DeadLetterQueue(config.dead_letter_dir),
        connector_factory=lambda t: connector,
    )

    report = runner.run_cycle()

    assert report.sources_run == 1
    assert report.sources_failed == 0
    assert report.entities_discovered == 1
    assert report.entities_invalid == 0
    assert len(push_client.calls) == 1
    assert push_client.calls[0].entities[0].urn == "urn:fake:h:d:s.t1"

    # cursor persisted to disk for next cycle
    saved = CursorStore(config.cursor_dir).load("src-1")
    assert "urn:fake:h:d:s.t1" in saved.entries


def test_invalid_entity_is_dropped_not_pushed(tmp_path):
    raws = [
        RawEntity(entity_type=EntityType.TABLE.value, key="t1", raw={"name": "t1"}),
        RawEntity(entity_type=EntityType.TABLE.value, key="bad", raw={"name": "bad"}),
    ]
    connector = FakeConnector(raws, invalid_urn_for="urn:fake:h:d:s.bad")
    config = make_config(tmp_path)
    push_client = FakePushClient()
    runner = AgentRunner(
        config=config,
        cursor_store=CursorStore(config.cursor_dir),
        push_client=push_client,
        dead_letter=DeadLetterQueue(config.dead_letter_dir),
        connector_factory=lambda t: connector,
    )

    report = runner.run_cycle()

    assert report.entities_discovered == 2
    assert report.entities_invalid == 1
    pushed_urns = {e.urn for b in push_client.calls for e in b.entities}
    assert pushed_urns == {"urn:fake:h:d:s.t1"}


def test_push_failure_dead_letters_batch(tmp_path):
    from agent.push_client import PushResult

    raws = [RawEntity(entity_type=EntityType.TABLE.value, key="t1", raw={"name": "t1"})]
    connector = FakeConnector(raws)
    config = make_config(tmp_path)
    push_client = FakePushClient(script=[PushResult(success=False, batch_id="x", error="server on fire")])
    dead_letter = DeadLetterQueue(config.dead_letter_dir)
    runner = AgentRunner(
        config=config,
        cursor_store=CursorStore(config.cursor_dir),
        push_client=push_client,
        dead_letter=dead_letter,
        connector_factory=lambda t: connector,
    )

    report = runner.run_cycle()

    assert report.batches_dead_lettered == 1
    assert len(dead_letter.list_pending()) == 1
    # cursor is still saved -- the connector's own extraction succeeded,
    # only the push failed, and the batch is safe on disk for next cycle.
    saved = CursorStore(config.cursor_dir).load("src-1")
    assert "urn:fake:h:d:s.t1" in saved.entries


def test_dead_lettered_batch_is_retried_next_cycle_and_removed_on_success(tmp_path):
    from agent.push_client import PushResult

    raws = [RawEntity(entity_type=EntityType.TABLE.value, key="t1", raw={"name": "t1"})]
    connector = FakeConnector(raws)
    config = make_config(tmp_path)
    dead_letter = DeadLetterQueue(config.dead_letter_dir)

    # Cycle 1: push fails -> dead-lettered.
    failing_client = FakePushClient(script=[PushResult(success=False, batch_id="x", error="down")])
    runner1 = AgentRunner(
        config=config,
        cursor_store=CursorStore(config.cursor_dir),
        push_client=failing_client,
        dead_letter=dead_letter,
        connector_factory=lambda t: connector,
    )
    runner1.run_cycle()
    assert len(dead_letter.list_pending()) == 1

    # Cycle 2: control plane recovers -- dead letter retried first, then
    # the (empty this time) new discovery cycle runs.
    connector2 = FakeConnector([])  # nothing new to discover this cycle
    recovering_client = FakePushClient()  # default: succeeds
    runner2 = AgentRunner(
        config=config,
        cursor_store=CursorStore(config.cursor_dir),
        push_client=recovering_client,
        dead_letter=dead_letter,
        connector_factory=lambda t: connector2,
    )
    report2 = runner2.run_cycle()

    assert report2.dead_letters_retried_ok == 1
    assert len(dead_letter.list_pending()) == 0


def test_source_failure_does_not_abort_whole_cycle(tmp_path):
    class ExplodingConnector(FakeConnector):
        def discover(self):
            raise RuntimeError("boom")

    config = make_config(
        tmp_path,
        sources=[
            SourceConfig(connector_type="fake", source_connection_id="src-1", config={}),
            SourceConfig(connector_type="fake2", source_connection_id="src-2", config={}),
        ],
    )
    connectors_by_type = {
        "fake": ExplodingConnector([]),
        "fake2": FakeConnector([RawEntity(entity_type=EntityType.TABLE.value, key="t1", raw={"name": "t1"})]),
    }
    push_client = FakePushClient()
    runner = AgentRunner(
        config=config,
        cursor_store=CursorStore(config.cursor_dir),
        push_client=push_client,
        dead_letter=DeadLetterQueue(config.dead_letter_dir),
        connector_factory=lambda t: connectors_by_type[t],
    )

    report = runner.run_cycle()

    assert report.sources_run == 2
    assert report.sources_failed == 1
    assert len(report.errors) == 1
    # the second, healthy source still got pushed despite the first exploding
    assert len(push_client.calls) == 1


def test_batcher_flushes_across_max_entities_within_one_source(tmp_path):
    raws = [RawEntity(entity_type=EntityType.TABLE.value, key=f"t{i}", raw={"name": f"t{i}"}) for i in range(5)]
    connector = FakeConnector(raws)
    config = make_config(tmp_path, max_batch_entities=2, max_batch_interval_seconds=9999)
    push_client = FakePushClient()
    runner = AgentRunner(
        config=config,
        cursor_store=CursorStore(config.cursor_dir),
        push_client=push_client,
        dead_letter=DeadLetterQueue(config.dead_letter_dir),
        connector_factory=lambda t: connector,
    )
    runner.run_cycle()
    # 5 entities, max 2 per batch -> batches of [2, 2, 1]
    sizes = sorted(len(b.entities) for b in push_client.calls)
    assert sizes == [1, 2, 2]
