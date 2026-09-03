"""PostgresConnector — MVP connector per architecture.md §3.

`discover()` walks `information_schema`/`pg_catalog` (schemas -> tables ->
columns). `extract_metadata()` populates Table/Column fields per spec.md.
`extract_lineage()` is intentionally NOT overridden: Postgres has no native
lineage source for MVP (architecture.md §3), so `BaseConnector`'s default
(empty iterator) applies as-is.

Cursor-based incremental scrape: `get_cursor()`/`set_cursor()` track a
per-entity `last_scraped_at` + `content_hash`. Schema drift (a table or
column that existed in the previous cursor but is absent from this cycle's
`discover()`) is surfaced as a `RawEntity(tombstone=True)` from `discover()`
itself and turned into an `operation="delete"` NormalizedEntity by
`extract_metadata()` — never raised as an error.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, TYPE_CHECKING

from connectors.core.types import (
    Cursor,
    EntityType,
    HealthStatus,
    NormalizedEntity,
    Operation,
    RawEntity,
    diff_deleted_urns,
    utcnow,
)
from connectors.core.base import BaseConnector

from . import introspection
from .type_mapping import normalize_type

if TYPE_CHECKING:  # pragma: no cover
    import psycopg2  # noqa: F401


@dataclass
class PostgresConfig:
    source_connection_id: str
    host: str
    database: str
    user: str
    password: str
    port: int = 5432
    sslmode: str = "prefer"
    connect_timeout: int = 10
    include_schemas: Optional[List[str]] = None
    exclude_schemas: List[str] = field(
        default_factory=lambda: ["pg_catalog", "information_schema"]
    )
    # Optional friendly alias used in urns instead of the raw host, e.g.
    # "prod-db-1" (matches the example in architecture.md §2). Defaults to
    # `host` when not set.
    host_alias: Optional[str] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PostgresConfig":
        required = ["source_connection_id", "host", "database", "user", "password"]
        missing = [k for k in required if not d.get(k)]
        if missing:
            raise ValueError(f"PostgresConfig missing required fields: {missing}")
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})

    @property
    def alias(self) -> str:
        return self.host_alias or self.host


class PostgresConnector(BaseConnector):
    connector_type = "postgres"

    def __init__(self) -> None:
        self._config: Optional[PostgresConfig] = None
        self._conn: Any = None
        self._cursor_state: Optional[Cursor] = None

    # -- BaseConnector -----------------------------------------------------

    def connect(self, config: dict) -> None:
        self._config = PostgresConfig.from_dict(config)
        import psycopg2  # local import: not required unless actually connecting

        self._conn = psycopg2.connect(
            host=self._config.host,
            port=self._config.port,
            dbname=self._config.database,
            user=self._config.user,
            password=self._config.password,
            sslmode=self._config.sslmode,
            connect_timeout=self._config.connect_timeout,
        )
        self._conn.autocommit = True
        if self._cursor_state is None:
            self._cursor_state = Cursor.empty(self._config.source_connection_id)

    def health_check(self) -> HealthStatus:
        if self._conn is None:
            return HealthStatus(ok=False, detail="not connected")
        try:
            with self._conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            return HealthStatus(ok=True, detail="SELECT 1 succeeded")
        except Exception as exc:  # noqa: BLE001
            return HealthStatus(ok=False, detail=str(exc))

    def discover(self) -> Iterator[RawEntity]:
        if self._conn is None or self._config is None:
            raise RuntimeError("PostgresConnector.discover() called before connect()")
        cursor_state = self._cursor_state or Cursor.empty(self._config.source_connection_id)

        seen_table_urns: List[str] = []
        seen_column_urns: List[str] = []

        with self._conn.cursor() as cur:
            schemas = introspection.list_schemas(
                cur,
                include=self._config.include_schemas,
                exclude=tuple(self._config.exclude_schemas),
            )
            for schema in schemas:
                tables = introspection.list_tables(cur, schema)
                for table in tables:
                    table_urn = self._table_urn(schema, table["table_name"])
                    seen_table_urns.append(table_urn)
                    pk_columns, fk_map = introspection.list_primary_and_foreign_keys(
                        cur, table["table_oid"]
                    )
                    columns = introspection.list_columns(cur, table["table_oid"])
                    yield RawEntity(
                        entity_type=EntityType.TABLE.value,
                        key=f"{schema}.{table['table_name']}",
                        raw={"schema": schema, "table": table, "column_count": len(columns)},
                    )
                    for col in columns:
                        col_urn = self._column_urn(schema, table["table_name"], col["column_name"])
                        seen_column_urns.append(col_urn)
                        yield RawEntity(
                            entity_type=EntityType.COLUMN.value,
                            key=f"{schema}.{table['table_name']}.{col['column_name']}",
                            raw={
                                "schema": schema,
                                "table_name": table["table_name"],
                                "table_urn": table_urn,
                                "column": col,
                                "is_primary_key": col["column_name"] in pk_columns,
                                "foreign_key_ref": fk_map.get(col["column_name"]),
                            },
                        )

        # Schema drift -> delete. Tables and columns diffed independently
        # so a dropped column on a still-present table tombstones only
        # that column, not the whole table.
        for urn in diff_deleted_urns(cursor_state, seen_table_urns, entity_type=EntityType.TABLE.value):
            yield RawEntity(entity_type=EntityType.TABLE.value, key=urn, raw={}, tombstone=True)
        for urn in diff_deleted_urns(cursor_state, seen_column_urns, entity_type=EntityType.COLUMN.value):
            yield RawEntity(entity_type=EntityType.COLUMN.value, key=urn, raw={}, tombstone=True)

    def extract_metadata(self, entity: RawEntity) -> NormalizedEntity:
        if entity.tombstone:
            return self._tombstone_to_normalized(entity)
        if entity.entity_type == EntityType.TABLE.value:
            return self._table_to_normalized(entity)
        if entity.entity_type == EntityType.COLUMN.value:
            return self._column_to_normalized(entity)
        raise ValueError(f"PostgresConnector cannot extract unknown entity_type={entity.entity_type!r}")

    # extract_lineage: not overridden -> BaseConnector default (empty),
    # per architecture.md §3 ("Postgres has no native lineage source for
    # MVP").

    def get_cursor(self) -> Cursor:
        if self._cursor_state is None:
            self._cursor_state = Cursor.empty(
                self._config.source_connection_id if self._config else ""
            )
        return self._cursor_state

    def set_cursor(self, cursor: Cursor) -> None:
        self._cursor_state = cursor

    # -- internal ------------------------------------------------------

    def _table_urn(self, schema: str, table: str) -> str:
        assert self._config is not None
        return f"urn:postgres:{self._config.alias}:{self._config.database}:{schema}.{table}"

    def _column_urn(self, schema: str, table: str, column: str) -> str:
        return f"{self._table_urn(schema, table)}.{column}"

    def _record_cursor(self, normalized: NormalizedEntity) -> None:
        cursor_state = self.get_cursor()
        if normalized.operation == Operation.DELETE.value:
            cursor_state.forget(normalized.urn)
        else:
            cursor_state.record(
                normalized.urn,
                normalized.entity_type,
                normalized.content_hash,
                when=normalized.extracted_at,
            )

    def _table_to_normalized(self, entity: RawEntity) -> NormalizedEntity:
        assert self._config is not None
        schema = entity.raw["schema"]
        table = entity.raw["table"]
        urn = self._table_urn(schema, table["table_name"])
        description = table.get("description")
        payload = {
            "source_type": "postgres",
            "source_connection_id": self._config.source_connection_id,
            "database_name": self._config.database,
            "schema_name": schema,
            "table_name": table["table_name"],
            "fully_qualified_name": f"postgres://{self._config.host}/{self._config.database}.{schema}.{table['table_name']}",
            "object_type": table["object_type"],
            "description": description,
            "description_source": "source_comment" if description else None,
            "owner": table.get("db_owner_role"),
            "owner_source": "source" if table.get("db_owner_role") else None,
            "tags": [],
            "row_count_estimate": table.get("row_count_estimate"),
            "size_bytes_estimate": table.get("size_bytes_estimate"),
            "source_created_at": None,
            "source_last_modified_at": None,
        }
        normalized = NormalizedEntity(
            urn=urn,
            entity_type=EntityType.TABLE.value,
            operation=Operation.UPSERT.value,
            payload=payload,
        )
        self._record_cursor(normalized)
        return normalized

    def _column_to_normalized(self, entity: RawEntity) -> NormalizedEntity:
        assert self._config is not None
        schema = entity.raw["schema"]
        table_name = entity.raw["table_name"]
        col = entity.raw["column"]
        urn = self._column_urn(schema, table_name, col["column_name"])
        fk_ref = entity.raw.get("foreign_key_ref")
        description = col.get("description")
        payload = {
            "source_type": "postgres",
            "source_connection_id": self._config.source_connection_id,
            "table_urn": entity.raw["table_urn"],
            "name": col["column_name"],
            "ordinal_position": col["ordinal_position"],
            "native_data_type": col["native_data_type"],
            "normalized_data_type": normalize_type(col["native_data_type"]),
            "is_nullable": col["is_nullable"],
            "is_primary_key": entity.raw.get("is_primary_key", False),
            "is_foreign_key": fk_ref is not None,
            "foreign_key_ref": (
                {
                    "table_urn": self._table_urn(fk_ref["schema"], fk_ref["table"])
                    if fk_ref.get("schema") and fk_ref.get("table")
                    else None,
                    "column": fk_ref.get("column"),
                }
                if fk_ref
                else None
            ),
            "description": description,
            "description_source": "source_comment" if description else None,
            "tags": [],
        }
        normalized = NormalizedEntity(
            urn=urn,
            entity_type=EntityType.COLUMN.value,
            operation=Operation.UPSERT.value,
            payload=payload,
        )
        self._record_cursor(normalized)
        return normalized

    def _tombstone_to_normalized(self, entity: RawEntity) -> NormalizedEntity:
        assert self._config is not None
        payload = {
            "source_type": "postgres",
            "source_connection_id": self._config.source_connection_id,
        }
        normalized = NormalizedEntity(
            urn=entity.key,
            entity_type=entity.entity_type,
            operation=Operation.DELETE.value,
            payload=payload,
            extracted_at=utcnow(),
        )
        self._record_cursor(normalized)
        return normalized
