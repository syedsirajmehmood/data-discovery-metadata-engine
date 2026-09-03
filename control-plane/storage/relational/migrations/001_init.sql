-- 001_init.sql — initial schema for the control-plane Postgres system of
-- record. Hand-authored to mirror storage/relational/models.py exactly;
-- if you change models.py, update this file (and add a new numbered
-- migration for any change after this one lands in a real environment —
-- this file is only ever the *baseline*, never edited once applied).
--
-- Apply locally with:
--   psql "$POSTGRES_DSN" -f storage/relational/migrations/001_init.sql
-- or via `python -m storage.relational.migrate` (uses SQLAlchemy
-- metadata.create_all against these same models — see migrate.py).

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS data_plane_registrations (
    -- VARCHAR, not UUID: architecture.md §2's push envelope carries
    -- data_plane_id as an opaque identifier (example "dp_9f3...", not
    -- necessarily canonical UUID text); every entities_* row below stores
    -- that same value verbatim, so this primary key must accept it as-is.
    id VARCHAR(64) PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    name VARCHAR(255) NOT NULL,
    registered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_data_plane_registrations_tenant ON data_plane_registrations(tenant_id);

CREATE TABLE IF NOT EXISTS api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    data_plane_id VARCHAR(64) REFERENCES data_plane_registrations(id),
    key_hash VARCHAR(128) NOT NULL UNIQUE,
    label VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_api_keys_tenant ON api_keys(tenant_id);
CREATE INDEX IF NOT EXISTS ix_api_keys_key_hash ON api_keys(key_hash);

CREATE TABLE IF NOT EXISTS connector_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    data_plane_id VARCHAR(64) NOT NULL,
    source_connection_id VARCHAR(255) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    status VARCHAR(32) NOT NULL,
    entities_seen_count INTEGER NOT NULL DEFAULT 0,
    entities_created_count INTEGER NOT NULL DEFAULT 0,
    entities_tombstoned_count INTEGER NOT NULL DEFAULT 0,
    error_summary TEXT
);
CREATE INDEX IF NOT EXISTS ix_connector_runs_tenant ON connector_runs(tenant_id);
CREATE INDEX IF NOT EXISTS ix_connector_runs_source ON connector_runs(source_connection_id);
CREATE INDEX IF NOT EXISTS ix_connector_runs_tenant_source_started
    ON connector_runs(tenant_id, source_connection_id, started_at);

-- Common entity envelope columns repeated on every entities_* table:
--   id, tenant_id, urn, data_plane_id, source_connection_id, content_hash,
--   first_seen_at, last_scraped_at, is_deleted
-- with a UNIQUE (tenant_id, urn) constraint so upserts are idempotent
-- per-tenant (architecture.md §2 idempotency, §6 multi-tenancy).

CREATE TABLE IF NOT EXISTS entities_table (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    urn VARCHAR(1024) NOT NULL,
    data_plane_id VARCHAR(64) NOT NULL,
    source_connection_id VARCHAR(255) NOT NULL,
    content_hash VARCHAR(128),
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_scraped_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_deleted BOOLEAN NOT NULL DEFAULT false,
    source_type VARCHAR(32) NOT NULL DEFAULT 'postgres',
    database_name VARCHAR(255) NOT NULL,
    schema_name VARCHAR(255) NOT NULL,
    table_name VARCHAR(255) NOT NULL,
    fully_qualified_name VARCHAR(1024) NOT NULL,
    object_type VARCHAR(32) NOT NULL DEFAULT 'table',
    description TEXT,
    description_source VARCHAR(32),
    owner VARCHAR(255),
    owner_source VARCHAR(16),
    tags VARCHAR(255)[] NOT NULL DEFAULT '{}',
    row_count_estimate INTEGER,
    size_bytes_estimate INTEGER,
    source_created_at TIMESTAMPTZ,
    source_last_modified_at TIMESTAMPTZ,
    CONSTRAINT uq_entities_table_tenant_urn UNIQUE (tenant_id, urn)
);
CREATE INDEX IF NOT EXISTS ix_entities_table_tenant ON entities_table(tenant_id);

CREATE TABLE IF NOT EXISTS entities_column (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    urn VARCHAR(1024) NOT NULL,
    data_plane_id VARCHAR(64) NOT NULL,
    source_connection_id VARCHAR(255) NOT NULL,
    content_hash VARCHAR(128),
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_scraped_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_deleted BOOLEAN NOT NULL DEFAULT false,
    table_urn VARCHAR(1024) NOT NULL,
    name VARCHAR(255) NOT NULL,
    ordinal_position INTEGER NOT NULL,
    native_data_type VARCHAR(255) NOT NULL,
    normalized_data_type VARCHAR(64) NOT NULL,
    is_nullable BOOLEAN NOT NULL DEFAULT true,
    is_primary_key BOOLEAN NOT NULL DEFAULT false,
    is_foreign_key BOOLEAN NOT NULL DEFAULT false,
    foreign_key_ref JSONB,
    description TEXT,
    description_source VARCHAR(32),
    tags VARCHAR(255)[] NOT NULL DEFAULT '{}',
    CONSTRAINT uq_entities_column_tenant_urn UNIQUE (tenant_id, urn)
);
CREATE INDEX IF NOT EXISTS ix_entities_column_tenant ON entities_column(tenant_id);
CREATE INDEX IF NOT EXISTS ix_entities_column_table_urn ON entities_column(table_urn);

CREATE TABLE IF NOT EXISTS entities_dataset (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    urn VARCHAR(1024) NOT NULL,
    data_plane_id VARCHAR(64) NOT NULL,
    source_connection_id VARCHAR(255) NOT NULL,
    content_hash VARCHAR(128),
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_scraped_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_deleted BOOLEAN NOT NULL DEFAULT false,
    source_type VARCHAR(32) NOT NULL DEFAULT 's3',
    bucket VARCHAR(255) NOT NULL,
    prefix VARCHAR(1024) NOT NULL,
    fully_qualified_name VARCHAR(1024) NOT NULL,
    file_format VARCHAR(32),
    schema_inferred BOOLEAN NOT NULL DEFAULT false,
    object_count_estimate INTEGER,
    total_size_bytes_estimate INTEGER,
    description TEXT,
    description_source VARCHAR(32),
    owner VARCHAR(255),
    owner_source VARCHAR(16),
    tags VARCHAR(255)[] NOT NULL DEFAULT '{}',
    fields JSONB,
    CONSTRAINT uq_entities_dataset_tenant_urn UNIQUE (tenant_id, urn)
);
CREATE INDEX IF NOT EXISTS ix_entities_dataset_tenant ON entities_dataset(tenant_id);

CREATE TABLE IF NOT EXISTS entities_job (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    urn VARCHAR(1024) NOT NULL,
    data_plane_id VARCHAR(64) NOT NULL,
    source_connection_id VARCHAR(255) NOT NULL,
    content_hash VARCHAR(128),
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_scraped_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_deleted BOOLEAN NOT NULL DEFAULT false,
    job_type VARCHAR(32) NOT NULL,
    name VARCHAR(255) NOT NULL,
    source_system VARCHAR(255),
    owner VARCHAR(255),
    schedule VARCHAR(255),
    description TEXT,
    last_run_at TIMESTAMPTZ,
    last_run_status VARCHAR(16),
    CONSTRAINT uq_entities_job_tenant_urn UNIQUE (tenant_id, urn)
);
CREATE INDEX IF NOT EXISTS ix_entities_job_tenant ON entities_job(tenant_id);

CREATE TABLE IF NOT EXISTS entities_lineage_edge (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    urn VARCHAR(1024) NOT NULL,
    data_plane_id VARCHAR(64) NOT NULL,
    source_connection_id VARCHAR(255) NOT NULL,
    content_hash VARCHAR(128),
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_scraped_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_deleted BOOLEAN NOT NULL DEFAULT false,
    upstream_urn VARCHAR(1024) NOT NULL,
    upstream_entity_type VARCHAR(32) NOT NULL,
    downstream_urn VARCHAR(1024) NOT NULL,
    downstream_entity_type VARCHAR(32) NOT NULL,
    edge_granularity VARCHAR(16) NOT NULL DEFAULT 'table_level',
    producer_job_urn VARCHAR(1024),
    confidence VARCHAR(32) NOT NULL DEFAULT 'inferred',
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_confirmed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_entities_lineage_edge_tenant_urn UNIQUE (tenant_id, urn)
);
CREATE INDEX IF NOT EXISTS ix_entities_lineage_edge_tenant ON entities_lineage_edge(tenant_id);
CREATE INDEX IF NOT EXISTS ix_entities_lineage_edge_upstream ON entities_lineage_edge(upstream_urn);
CREATE INDEX IF NOT EXISTS ix_entities_lineage_edge_downstream ON entities_lineage_edge(downstream_urn);
