from connectors.core.types import EntityType, NormalizedEntity, Operation
from agent.batcher import Batcher


def make_entity(i):
    return NormalizedEntity(
        urn=f"urn:postgres:h:d:s.t{i}",
        entity_type=EntityType.TABLE.value,
        operation=Operation.UPSERT.value,
        payload={"table_name": f"t{i}"},
    )


def test_flushes_on_max_entities():
    batcher = Batcher(max_entities=3, max_interval_seconds=9999)
    assert batcher.add("postgres", make_entity(1)) is None
    assert batcher.add("postgres", make_entity(2)) is None
    batch = batcher.add("postgres", make_entity(3))
    assert batch is not None
    assert len(batch.entities) == 3
    assert batch.connector_type == "postgres"
    assert len(batcher) == 0


def test_flushes_on_interval_whichever_first():
    clock = {"t": 0.0}
    batcher = Batcher(max_entities=500, max_interval_seconds=60, clock=lambda: clock["t"])
    batcher.add("postgres", make_entity(1))
    assert batcher.maybe_flush_on_interval() is None  # not due yet

    clock["t"] = 61.0
    batch = batcher.maybe_flush_on_interval()
    assert batch is not None
    assert len(batch.entities) == 1


def test_force_flush_returns_none_when_empty():
    batcher = Batcher()
    assert batcher.flush() is None


def test_force_flush_returns_remaining_entities():
    batcher = Batcher(max_entities=500, max_interval_seconds=9999)
    batcher.add("s3", make_entity(1))
    batcher.add("s3", make_entity(2))
    batch = batcher.flush()
    assert len(batch.entities) == 2
    assert len(batcher) == 0


def test_each_closed_batch_gets_a_fresh_unique_batch_id():
    batcher = Batcher(max_entities=1, max_interval_seconds=9999)
    b1 = batcher.add("postgres", make_entity(1))
    b2 = batcher.add("postgres", make_entity(2))
    assert b1.batch_id != b2.batch_id


def test_rejects_mixed_connector_types_in_one_batcher():
    batcher = Batcher(max_entities=500, max_interval_seconds=9999)
    batcher.add("postgres", make_entity(1))
    try:
        batcher.add("s3", make_entity(2))
        assert False, "expected ValueError"
    except ValueError:
        pass
