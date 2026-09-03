from connectors.core.types import Cursor
from agent.cursor_store import CursorStore


def test_load_missing_returns_empty_cursor(tmp_path):
    store = CursorStore(str(tmp_path))
    cursor = store.load("src-1")
    assert cursor.source_connection_id == "src-1"
    assert cursor.entries == {}


def test_save_then_load_roundtrip(tmp_path):
    store = CursorStore(str(tmp_path))
    cursor = Cursor.empty("src-1")
    cursor.record("urn:a", "table", "sha256:aaa")
    cursor.record("urn:b", "column", "sha256:bbb")
    store.save(cursor)

    reloaded = store.load("src-1")
    assert reloaded.source_connection_id == "src-1"
    assert set(reloaded.entries.keys()) == {"urn:a", "urn:b"}
    assert reloaded.entries["urn:a"].content_hash == "sha256:aaa"
    assert reloaded.updated_at is not None


def test_source_connection_ids_with_unsafe_characters_are_sanitized(tmp_path):
    store = CursorStore(str(tmp_path))
    cursor = Cursor.empty("prod/postgres:1")
    store.save(cursor)
    # must not have created a nested directory or failed
    reloaded = store.load("prod/postgres:1")
    assert reloaded.source_connection_id == "prod/postgres:1"


def test_two_source_connections_do_not_clobber_each_other(tmp_path):
    store = CursorStore(str(tmp_path))
    c1 = Cursor.empty("src-1")
    c1.record("urn:a", "table", "sha256:aaa")
    c2 = Cursor.empty("src-2")
    c2.record("urn:b", "table", "sha256:bbb")
    store.save(c1)
    store.save(c2)

    assert set(store.load("src-1").entries.keys()) == {"urn:a"}
    assert set(store.load("src-2").entries.keys()) == {"urn:b"}
