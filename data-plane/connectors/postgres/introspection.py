"""Pure introspection helpers that operate on a DB-API cursor.

Deliberately decoupled from `psycopg2` at the type level (any object with
`.execute(sql, params)`, `.fetchall()` and `.description` works) so unit
tests can exercise this module with a lightweight fake cursor instead of a
real Postgres connection.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from . import queries


def _rows_as_dicts(cur: Any) -> List[Dict[str, Any]]:
    columns = [d[0] for d in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def list_schemas(
    cur: Any,
    include: Optional[List[str]] = None,
    exclude: Tuple[str, ...] = queries.DEFAULT_EXCLUDED_SCHEMAS,
) -> List[str]:
    cur.execute(queries.LIST_SCHEMAS, {"excluded": tuple(exclude)})
    schemas = [row[0] for row in cur.fetchall()]
    if include:
        include_set = set(include)
        schemas = [s for s in schemas if s in include_set]
    return schemas


def list_tables(cur: Any, schema: str) -> List[Dict[str, Any]]:
    cur.execute(queries.LIST_TABLES, {"schema": schema})
    return _rows_as_dicts(cur)


def list_columns(cur: Any, table_oid: int) -> List[Dict[str, Any]]:
    cur.execute(queries.LIST_COLUMNS, {"table_oid": table_oid})
    return _rows_as_dicts(cur)


def list_primary_and_foreign_keys(
    cur: Any, table_oid: int
) -> Tuple[Set[str], Dict[str, Dict[str, str]]]:
    """Returns (pk_column_names, {column_name: {schema, table, column}}) for
    foreign keys. Resolves attnum arrays (`conkey`/`confkey`) to column
    names via a lookup of this table's own attnums plus, for FKs, the
    referenced table's attnums.
    """
    cur.execute(queries.LIST_ATTNAME_BY_NUM, {"table_oid": table_oid})
    local_attnames = {row[0]: row[1] for row in cur.fetchall()}

    cur.execute(queries.LIST_CONSTRAINTS, {"table_oid": table_oid})
    constraints = _rows_as_dicts(cur)

    pk_columns: Set[str] = set()
    fk_map: Dict[str, Dict[str, str]] = {}

    for con in constraints:
        contype = con["contype"]
        conkey = con.get("conkey") or []
        if contype == "p":
            for attnum in conkey:
                name = local_attnames.get(attnum)
                if name:
                    pk_columns.add(name)
        elif contype == "f":
            confrelid = con.get("confrelid")
            confkey = con.get("confkey") or []
            ref_schema = con.get("ref_schema_name")
            ref_table = con.get("ref_table_name")
            ref_attnames: Dict[int, str] = {}
            if confrelid:
                cur.execute(queries.LIST_ATTNAME_BY_NUM, {"table_oid": confrelid})
                ref_attnames = {row[0]: row[1] for row in cur.fetchall()}
            for local_num, ref_num in zip(conkey, confkey):
                local_name = local_attnames.get(local_num)
                ref_name = ref_attnames.get(ref_num)
                if local_name:
                    fk_map[local_name] = {
                        "schema": ref_schema,
                        "table": ref_table,
                        "column": ref_name,
                    }

    return pk_columns, fk_map
