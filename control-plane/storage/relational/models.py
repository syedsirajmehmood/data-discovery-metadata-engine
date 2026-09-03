"""SQLAlchemy ORM models for the Postgres system-of-record.

Covers architecture.md §8's list (tenants, api_keys,
data_plane_registrations, connector_runs, entities) plus one table per
entity type from spec.md's "Metadata schema requirements" section (Table,
Column, Dataset, Job/DAG, Lineage Edge — "Scrape Run" maps to
``connector_runs``).

Multi-tenancy (architecture.md §6 / spec.md NFR-2): every entity table has a
non-nullable, indexed ``tenant_id`` and a composite unique constraint on
``(tenant_id, urn)`` so upserts are idempotent per-tenant and cross-tenant
collisions on the same URN (e.g. two tenants both cataloging
``public.orders``) can never collide.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


# --------------------------------------------------------------------------
# Registry: tenants, API keys, data-plane registrations, scrape runs
# --------------------------------------------------------------------------


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApiKey(Base):
    """Long-lived, revocable API key scoped to exactly one
    ``(tenant_id, data_plane_id)`` pair (architecture.md §2's auth model).

    Only the hash is stored — the raw key is shown once at issuance time by
    the (not-FE2-owned) registration flow and never persisted in plaintext.
    Also doubles as the catalog-read-API auth mechanism (see
    ``api/catalog/deps.py``) since architecture.md doesn't separately define
    a UI-user auth system for MVP; a UI/service key with
    ``data_plane_id IS NULL`` is a tenant-scoped read key rather than a
    data-plane push key.
    """

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    data_plane_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("data_plane_registrations.id"), nullable=True
    )
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class DataPlaneRegistration(Base):
    __tablename__ = "data_plane_registrations"

    # String, not UUID: architecture.md §2's push envelope carries
    # data_plane_id as an opaque identifier (example: "dp_9f3...", not
    # necessarily canonical UUID text), and every entities_* row stores
    # whatever value the data plane sent verbatim (EntityCommonMixin below)
    # — so this primary key must accept the same shape. Defaults to a UUID4
    # string for convenience when nothing else generates the id.
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ConnectorRun(Base):
    """"Scrape Run" per spec.md — supports AC-4/AC-7 freshness + audit."""

    __tablename__ = "connector_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    data_plane_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_connection_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # success|partial_failure|failed|running
    entities_seen_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    entities_created_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    entities_tombstoned_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_connector_runs_tenant_source_started", "tenant_id", "source_connection_id", "started_at"),
    )


# --------------------------------------------------------------------------
# Common columns mixin for entity tables
# --------------------------------------------------------------------------


class EntityCommonMixin:
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    urn: Mapped[str] = mapped_column(String(1024), nullable=False)
    # String, not UUID — see DataPlaneRegistration.id's docstring: this
    # stores the push envelope's opaque data_plane_id verbatim.
    data_plane_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_connection_id: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class TableEntity(EntityCommonMixin, Base):
    """Postgres table/view — spec.md "Table"."""

    __tablename__ = "entities_table"

    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="postgres")
    database_name: Mapped[str] = mapped_column(String(255), nullable=False)
    schema_name: Mapped[str] = mapped_column(String(255), nullable=False)
    table_name: Mapped[str] = mapped_column(String(255), nullable=False)
    fully_qualified_name: Mapped[str] = mapped_column(String(1024), nullable=False)
    object_type: Mapped[str] = mapped_column(String(32), nullable=False, default="table")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description_source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # source_comment|manual
    owner: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    owner_source: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # source|manual
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    row_count_estimate: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    size_bytes_estimate: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    source_last_modified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", "urn", name="uq_entities_table_tenant_urn"),)


class ColumnEntity(EntityCommonMixin, Base):
    """Belongs to a Table — spec.md "Column"."""

    __tablename__ = "entities_column"

    table_urn: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    ordinal_position: Mapped[int] = mapped_column(Integer, nullable=False)
    native_data_type: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_data_type: Mapped[str] = mapped_column(String(64), nullable=False)
    is_nullable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_primary_key: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_foreign_key: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    foreign_key_ref: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description_source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)

    __table_args__ = (UniqueConstraint("tenant_id", "urn", name="uq_entities_column_tenant_urn"),)


class DatasetEntity(EntityCommonMixin, Base):
    """S3-sourced dataset — spec.md "Dataset"."""

    __tablename__ = "entities_dataset"

    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="s3")
    bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    prefix: Mapped[str] = mapped_column(String(1024), nullable=False)
    fully_qualified_name: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_format: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # parquet|csv|json|mixed|unknown
    schema_inferred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    object_count_estimate: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_size_bytes_estimate: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description_source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    owner: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    owner_source: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    fields: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)  # Column-shaped, when schema_inferred

    __table_args__ = (UniqueConstraint("tenant_id", "urn", name="uq_entities_dataset_tenant_urn"),)


class JobEntity(EntityCommonMixin, Base):
    """spec.md "Job / DAG" — schema-only for MVP, no connector populates it yet."""

    __tablename__ = "entities_job"

    job_type: Mapped[str] = mapped_column(String(32), nullable=False)  # dbt_model|airflow_dag|...
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_system: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    owner: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    schedule: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", "urn", name="uq_entities_job_tenant_urn"),)


class LineageEdgeEntity(EntityCommonMixin, Base):
    """spec.md "Lineage Edge". Table-level for MVP; column-level is
    schema-supported via ``edge_granularity`` per the same row shape.
    """

    __tablename__ = "entities_lineage_edge"

    upstream_urn: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    upstream_entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    downstream_urn: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    downstream_entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    edge_granularity: Mapped[str] = mapped_column(String(16), nullable=False, default="table_level")
    producer_job_urn: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    confidence: Mapped[str] = mapped_column(String(32), nullable=False, default="inferred")
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("tenant_id", "urn", name="uq_entities_lineage_edge_tenant_urn"),)


ENTITY_TABLES_BY_TYPE = {
    "table": TableEntity,
    "column": ColumnEntity,
    "dataset": DatasetEntity,
    "job": JobEntity,
    "lineage_edge": LineageEdgeEntity,
}
