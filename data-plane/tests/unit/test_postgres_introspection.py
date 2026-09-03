"""Unit tests for connectors/postgres/introspection.py using a lightweight
fake DB-API cursor -- no real Postgres connection needed. See
tests/integration/test_postgres_integration.py for the real-database path.
"""
from connectors.postgres import introspection


class FakeCursor:
    """Each `execute()` call pops the next programmed (columns, rows) pair.
    Doesn't inspect the SQL text at all -- callers program responses in the
    exact order the function under test is expected to issue them."""

    def __init__(self, programmed):
        self._programmed = list(programmed)
        self.description = None
        self._current_rows = []

    def execute(self, sql, params=None):
        columns, rows = self._programmed.pop(0)
        self.description = [(c,) for c in columns]
        self._current_rows = rows

    def fetchall(self):
        return self._current_rows


def test_list_schemas_filters_excluded_and_include_list():
    cur = FakeCursor([(["schema_name"], [("public",), ("analytics",), ("staging",)])])
    schemas = introspection.list_schemas(cur, include=["public", "analytics"])
    assert schemas == ["public", "analytics"]


def test_list_schemas_no_include_returns_all_rows():
    cur = FakeCursor([(["schema_name"], [("public",), ("analytics",)])])
    schemas = introspection.list_schemas(cur)
    assert schemas == ["public", "analytics"]


def test_list_tables_returns_dicts():
    columns = [
        "schema_name", "table_name", "object_type", "row_count_estimate",
        "size_bytes_estimate", "description", "db_owner_role", "table_oid",
    ]
    rows = [("public", "orders", "table", 1000, 65536, "order records", "app_user", 12345)]
    cur = FakeCursor([(columns, rows)])
    tables = introspection.list_tables(cur, "public")
    assert tables == [
        {
            "schema_name": "public",
            "table_name": "orders",
            "object_type": "table",
            "row_count_estimate": 1000,
            "size_bytes_estimate": 65536,
            "description": "order records",
            "db_owner_role": "app_user",
            "table_oid": 12345,
        }
    ]


def test_list_columns_returns_dicts_in_order():
    columns = ["column_name", "ordinal_position", "native_data_type", "is_nullable", "description"]
    rows = [
        ("id", 1, "integer", False, None),
        ("name", 2, "character varying(255)", True, "display name"),
    ]
    cur = FakeCursor([(columns, rows)])
    result = introspection.list_columns(cur, table_oid=12345)
    assert [c["column_name"] for c in result] == ["id", "name"]
    assert result[1]["native_data_type"] == "character varying(255)"
    assert result[1]["description"] == "display name"


def test_list_primary_and_foreign_keys_resolves_pk_and_fk():
    own_attnames = (["attnum", "attname"], [(1, "id"), (2, "user_id"), (3, "name")])
    constraints = (
        ["conname", "contype", "conkey", "confrelid", "confkey", "ref_schema_name", "ref_table_name"],
        [
            ("orders_pkey", "p", [1], None, None, None, None),
            ("orders_user_id_fkey", "f", [2], 999, [10], "public", "users"),
        ],
    )
    ref_attnames = (["attnum", "attname"], [(10, "id")])
    cur = FakeCursor([own_attnames, constraints, ref_attnames])

    pk_columns, fk_map = introspection.list_primary_and_foreign_keys(cur, table_oid=12345)

    assert pk_columns == {"id"}
    assert fk_map == {"user_id": {"schema": "public", "table": "users", "column": "id"}}


def test_list_primary_and_foreign_keys_no_constraints():
    own_attnames = (["attnum", "attname"], [(1, "id")])
    constraints = (
        ["conname", "contype", "conkey", "confrelid", "confkey", "ref_schema_name", "ref_table_name"],
        [],
    )
    cur = FakeCursor([own_attnames, constraints])
    pk_columns, fk_map = introspection.list_primary_and_foreign_keys(cur, table_oid=1)
    assert pk_columns == set()
    assert fk_map == {}
