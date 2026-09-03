"""``RelationalStore`` — Postgres system-of-record client.

``upsert_entity`` is the exact method name FE1's fan-out worker calls
(architecture.md §8) for every accepted entity in a push batch. It dispatches
on ``EntityRecord.entity_type`` to the matching table in ``models.py`` and
performs a tenant-scoped upsert keyed on ``(tenant_id, urn)`` — the same key
the push contract uses for idempotency (architecture.md §2), so a replayed
or re-scraped-unchanged entity never creates a duplicate row.

Everything else on this class exists to serve
``control-plane/api/catalog/`` (FE2's own read API) and is intentionally
read-only / additive: no other engineer's code should need to import
``models.py`` directly.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from storage.relational.db import make_engine, make_session_factory
from storage.relational.models import (
    ApiKey,
    Base,
    ColumnEntity,
    ConnectorRun,
    DataPlaneRegistration,
    ENTITY_TABLES_BY_TYPE,
    TableEntity,
)
from storage.types import EntityRecord, EntityType, UpsertResult

# Columns every entity table carries that are never taken from `payload`
# (they come from the envelope / are store-managed) — see models.EntityCommonMixin.
_ENVELOPE_MANAGED_COLUMNS = {
    "id",
    "tenant_id",
    "urn",
    "data_plane_id",
    "source_connection_id",
    "content_hash",
    "first_seen_at",
    "last_scraped_at",
    "is_deleted",
}


class UnknownEntityTypeError(ValueError):
    pass


class RelationalStore:
    def __init__(
        self,
        engine: Optional[Engine] = None,
        session_factory: Optional[sessionmaker] = None,
    ) -> None:
        self._engine = engine if engine is not None else (None if session_factory is not None else make_engine())
        if session_factory is not None:
            self._session_factory = session_factory
        else:
            self._session_factory = make_session_factory(self._engine)

    # -- schema bootstrap (tests / local dev; production uses migrations/) --

    def create_all(self) -> None:
        if self._engine is None:
            raise RuntimeError("create_all() requires RelationalStore to have been constructed with an engine")
        Base.metadata.create_all(self._engine)

    # ------------------------------------------------------------------
    # The seam: upsert_entity
    # ------------------------------------------------------------------

    def upsert_entity(self, record: EntityRecord) -> UpsertResult:
        entity_type = record.entity_type.value if isinstance(record.entity_type, EntityType) else record.entity_type
        model = ENTITY_TABLES_BY_TYPE.get(entity_type)
        if model is None:
            raise UnknownEntityTypeError(
                f"RelationalStore has no table mapped for entity_type={entity_type!r}"
            )

        with self._session_factory() as session:
            existing = session.execute(
                select(model).where(model.tenant_id == record.tenant_id, model.urn == record.urn)
            ).scalar_one_or_none()

            if record.is_delete:
                if existing is None:
                    # Nothing to tombstone — not an error, just a no-op.
                    return UpsertResult(urn=record.urn, created=False, skipped=True)
                existing.is_deleted = True
                existing.last_scraped_at = record.extracted_at
                session.commit()
                return UpsertResult(urn=record.urn, created=False, tombstoned=True)

            if (
                existing is not None
                and record.content_hash is not None
                and existing.content_hash == record.content_hash
                and not existing.is_deleted
            ):
                # Cheap no-op per architecture.md §2: content unchanged since
                # last scrape, still bump freshness without a full rewrite.
                existing.last_scraped_at = record.extracted_at
                session.commit()
                return UpsertResult(urn=record.urn, created=False, skipped=True)

            row = self._row_from_record(model, record)
            if existing is None:
                obj = model(**row)
                session.add(obj)
                session.commit()
                return UpsertResult(urn=record.urn, created=True)

            for key, value in row.items():
                if key in ("tenant_id", "urn"):
                    continue
                setattr(existing, key, value)
            existing.is_deleted = False
            session.commit()
            return UpsertResult(urn=record.urn, created=False)

    @staticmethod
    def _row_from_record(model: type, record: EntityRecord) -> dict[str, Any]:
        valid_columns = {c.name for c in model.__table__.columns}
        row = {k: v for k, v in record.payload.items() if k in valid_columns and k not in _ENVELOPE_MANAGED_COLUMNS}
        row.update(
            tenant_id=record.tenant_id,
            urn=record.urn,
            data_plane_id=record.data_plane_id,
            source_connection_id=record.source_connection_id,
            content_hash=record.content_hash,
            last_scraped_at=record.extracted_at,
            is_deleted=False,
        )
        return row

    # ------------------------------------------------------------------
    # Scrape-run bookkeeping ("Scrape Run" entity, spec.md)
    # ------------------------------------------------------------------

    def record_connector_run(
        self,
        *,
        tenant_id: str,
        data_plane_id: str,
        source_connection_id: str,
        started_at: datetime,
        completed_at: Optional[datetime],
        status: str,
        entities_seen_count: int = 0,
        entities_created_count: int = 0,
        entities_tombstoned_count: int = 0,
        error_summary: Optional[str] = None,
    ) -> str:
        with self._session_factory() as session:
            run = ConnectorRun(
                tenant_id=tenant_id,
                data_plane_id=data_plane_id,
                source_connection_id=source_connection_id,
                started_at=started_at,
                completed_at=completed_at,
                status=status,
                entities_seen_count=entities_seen_count,
                entities_created_count=entities_created_count,
                entities_tombstoned_count=entities_tombstoned_count,
                error_summary=error_summary,
            )
            session.add(run)
            session.commit()
            return str(run.id)

    # ------------------------------------------------------------------
    # Read paths for control-plane/api/catalog/
    # ------------------------------------------------------------------

    def get_table_with_columns(self, tenant_id: str, urn: str) -> Optional[dict]:
        """Tenant-scoped table detail + ordered column list — backs
        ``GET /v1/catalog/tables/{urn}``. `tenant_id` must come from the
        server-resolved auth context, never a path/query param (§6)."""
        with self._session_factory() as session:
            table = session.execute(
                select(TableEntity).where(TableEntity.tenant_id == tenant_id, TableEntity.urn == urn)
            ).scalar_one_or_none()
            if table is None:
                return None
            columns = (
                session.execute(
                    select(ColumnEntity)
                    .where(ColumnEntity.tenant_id == tenant_id, ColumnEntity.table_urn == urn)
                    .order_by(ColumnEntity.ordinal_position)
                )
                .scalars()
                .all()
            )
            return {"table": _row_to_dict(table), "columns": [_row_to_dict(c) for c in columns]}

    def list_sources_status(self, tenant_id: str) -> list[dict]:
        """Backs ``GET /v1/catalog/sources/status`` — every registered data
        plane for this tenant, joined with the most recent connector run per
        ``source_connection_id`` (supports AC-7's "did my last scrape even
        succeed" without checking connector logs)."""
        with self._session_factory() as session:
            data_planes = (
                session.execute(
                    select(DataPlaneRegistration).where(DataPlaneRegistration.tenant_id == tenant_id)
                )
                .scalars()
                .all()
            )
            runs = (
                session.execute(
                    select(ConnectorRun)
                    .where(ConnectorRun.tenant_id == tenant_id)
                    .order_by(ConnectorRun.source_connection_id, ConnectorRun.started_at.desc())
                )
                .scalars()
                .all()
            )
            latest_run_by_source: dict[str, ConnectorRun] = {}
            for run in runs:
                latest_run_by_source.setdefault(run.source_connection_id, run)

            sources: dict[str, dict] = {}
            for dp in data_planes:
                sources[str(dp.id)] = {
                    "data_plane_id": str(dp.id),
                    "data_plane_name": dp.name,
                    "last_seen_at": dp.last_seen_at,
                    "source_connections": [],
                }
            for source_connection_id, run in latest_run_by_source.items():
                dp_key = str(run.data_plane_id)
                entry = {
                    "source_connection_id": source_connection_id,
                    "last_run_status": run.status,
                    "last_run_started_at": run.started_at,
                    "last_run_completed_at": run.completed_at,
                    "entities_seen_count": run.entities_seen_count,
                    "entities_created_count": run.entities_created_count,
                    "entities_tombstoned_count": run.entities_tombstoned_count,
                    "error_summary": run.error_summary,
                }
                if dp_key in sources:
                    sources[dp_key]["source_connections"].append(entry)
                else:
                    sources[dp_key] = {
                        "data_plane_id": dp_key,
                        "data_plane_name": None,
                        "last_seen_at": None,
                        "source_connections": [entry],
                    }
            return list(sources.values())

    def resolve_tenant_id_for_api_key_hash(self, key_hash: str) -> Optional[str]:
        """Auth seam for ``api/catalog/deps.py``: looks up an (unrevoked)
        API key by its hash and returns the tenant_id it is scoped to, or
        None. The caller hashes the raw key before calling this — the store
        never sees or stores a raw key."""
        with self._session_factory() as session:
            key = session.execute(
                select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None))
            ).scalar_one_or_none()
            return str(key.tenant_id) if key is not None else None


def _row_to_dict(row: Any) -> dict:
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}
