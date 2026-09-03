from connectors.core.types import EntityType, NormalizedEntity, Operation
from agent.batcher import Batch
from agent.dead_letter import DeadLetterQueue


def make_batch(batch_id="b-1"):
    entities = [
        NormalizedEntity(
            urn="urn:postgres:h:d:s.t1",
            entity_type=EntityType.TABLE.value,
            operation=Operation.UPSERT.value,
            payload={"table_name": "t1"},
        )
    ]
    return Batch(batch_id=batch_id, connector_type="postgres", entities=entities)


def test_add_then_list_pending(tmp_path):
    dlq = DeadLetterQueue(str(tmp_path))
    assert dlq.list_pending() == []
    dlq.add(make_batch("b-1"))
    pending = dlq.list_pending()
    assert len(pending) == 1
    assert pending[0].name == "b-1.json"


def test_load_reconstructs_batch_with_same_batch_id_and_payload(tmp_path):
    dlq = DeadLetterQueue(str(tmp_path))
    original = make_batch("b-42")
    dlq.add(original)

    [path] = dlq.list_pending()
    loaded = dlq.load(path)
    assert loaded.batch_id == "b-42"
    assert loaded.connector_type == "postgres"
    assert len(loaded.entities) == 1
    assert loaded.entities[0].urn == original.entities[0].urn
    assert loaded.entities[0].content_hash == original.entities[0].content_hash
    assert loaded.entities[0].payload == original.entities[0].payload


def test_remove_deletes_file(tmp_path):
    dlq = DeadLetterQueue(str(tmp_path))
    dlq.add(make_batch("b-1"))
    [path] = dlq.list_pending()
    dlq.remove(path)
    assert dlq.list_pending() == []


def test_len_reflects_pending_count(tmp_path):
    dlq = DeadLetterQueue(str(tmp_path))
    dlq.add(make_batch("b-1"))
    dlq.add(make_batch("b-2"))
    assert len(dlq) == 2
