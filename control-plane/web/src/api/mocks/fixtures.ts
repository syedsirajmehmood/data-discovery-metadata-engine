import type {
  AssetEntity,
  FreshnessContext,
  SearchResultItem,
  SourcesStatusResponse,
} from '../../types/catalog'

/**
 * Fixture data for dev-mode mocking and tests. Shapes match the documented
 * catalog read API (architecture.md §8) plus the assumed extensions noted
 * in src/types/catalog.ts and README.md. Not real backend data — FE2's
 * backend does not exist in this worktree yet.
 */

const HOUR = 3600 * 1000
const DAY = 24 * HOUR
const now = () => Date.now()
const ago = (ms: number) => new Date(now() - ms).toISOString()

const SIX_HOUR_INTERVAL = 6 * 3600 // seconds
const TWELVE_HOUR_THRESHOLD = SIX_HOUR_INTERVAL * 2

function freshnessOk(lastSuccessAgoMs: number): FreshnessContext {
  return {
    stale_threshold_seconds: TWELVE_HOUR_THRESHOLD,
    latest_scrape_run_status: 'success',
    last_successful_scrape_at: ago(lastSuccessAgoMs),
    has_any_scrape_run: true,
  }
}

function freshnessScrapeIssue(lastSuccessAgoMs: number, status: 'failed' | 'partial_failure'): FreshnessContext {
  return {
    stale_threshold_seconds: TWELVE_HOUR_THRESHOLD,
    latest_scrape_run_status: status,
    last_successful_scrape_at: ago(lastSuccessAgoMs),
    has_any_scrape_run: true,
  }
}

// ---- Table entities (prod-postgres-1) ----

export const customersTable: AssetEntity = {
  id: 'ent-customers',
  urn: 'urn:postgres:prod-db-1:analytics:public.customers',
  entity_type: 'table',
  source_type: 'postgres',
  data_plane_id: 'dp-prod',
  data_plane_name: 'customer-prod-vpc',
  source_connection_id: 'sc-prod-postgres-1',
  source_connection_name: 'prod-postgres-1',
  first_seen_at: ago(90 * DAY),
  last_scraped_at: ago(20 * 60 * 1000),
  is_deleted: false,
  database_name: 'prod-db',
  schema_name: 'public',
  table_name: 'customers',
  fully_qualified_name: 'postgres://prod-db/public.customers',
  object_type: 'table',
  description: 'Customer master record, one row per registered account.',
  description_source: 'source_comment',
  owner: 'jane@co',
  owner_source: 'source',
  tags: ['pii', 'core'],
  row_count_estimate: 1_200_000,
  size_bytes_estimate: 340 * 1024 * 1024,
  source_created_at: ago(400 * DAY),
  source_last_modified_at: ago(2 * HOUR),
  columns: [
    { name: 'id', ordinal_position: 1, native_data_type: 'bigint', normalized_data_type: 'integer', is_nullable: false, is_primary_key: true, is_foreign_key: false, foreign_key_ref: null, description: null, tags: [] },
    { name: 'email', ordinal_position: 2, native_data_type: 'text', normalized_data_type: 'string', is_nullable: false, is_primary_key: false, is_foreign_key: false, foreign_key_ref: null, description: null, tags: [] },
    { name: 'created_at', ordinal_position: 3, native_data_type: 'timestamp', normalized_data_type: 'timestamp', is_nullable: false, is_primary_key: false, is_foreign_key: false, foreign_key_ref: null, description: null, tags: [] },
    { name: 'plan_id', ordinal_position: 4, native_data_type: 'bigint', normalized_data_type: 'integer', is_nullable: true, is_primary_key: false, is_foreign_key: true, foreign_key_ref: 'plans.id', description: null, tags: [] },
  ],
  freshness: freshnessOk(20 * 60 * 1000),
}

export const plansTable: AssetEntity = {
  id: 'ent-plans',
  urn: 'urn:postgres:prod-db-1:analytics:public.plans',
  entity_type: 'table',
  source_type: 'postgres',
  data_plane_id: 'dp-prod',
  data_plane_name: 'customer-prod-vpc',
  source_connection_id: 'sc-prod-postgres-1',
  source_connection_name: 'prod-postgres-1',
  first_seen_at: ago(90 * DAY),
  last_scraped_at: ago(20 * 60 * 1000),
  is_deleted: false,
  database_name: 'prod-db',
  schema_name: 'public',
  table_name: 'plans',
  fully_qualified_name: 'postgres://prod-db/public.plans',
  object_type: 'table',
  description: null,
  description_source: null,
  owner: null,
  owner_source: null,
  tags: [],
  row_count_estimate: 12,
  size_bytes_estimate: 16 * 1024,
  source_created_at: ago(400 * DAY),
  source_last_modified_at: ago(40 * DAY),
  columns: [
    { name: 'id', ordinal_position: 1, native_data_type: 'bigint', normalized_data_type: 'integer', is_nullable: false, is_primary_key: true, is_foreign_key: false, foreign_key_ref: null, description: null, tags: [] },
    { name: 'name', ordinal_position: 2, native_data_type: 'character varying(255)', normalized_data_type: 'string', is_nullable: false, is_primary_key: false, is_foreign_key: false, foreign_key_ref: null, description: null, tags: [] },
  ],
  freshness: freshnessOk(20 * 60 * 1000),
}

const legacyCustomersBakTable: AssetEntity = {
  id: 'ent-legacy-customers-bak',
  urn: 'urn:postgres:prod-db-1:analytics:public.legacy_customers_bak',
  entity_type: 'table',
  source_type: 'postgres',
  data_plane_id: 'dp-prod',
  data_plane_name: 'customer-prod-vpc',
  source_connection_id: 'sc-prod-postgres-1',
  source_connection_name: 'prod-postgres-1',
  first_seen_at: ago(200 * DAY),
  last_scraped_at: ago(5 * DAY),
  is_deleted: true,
  database_name: 'prod-db',
  schema_name: 'public',
  table_name: 'legacy_customers_bak',
  fully_qualified_name: 'postgres://prod-db/public.legacy_customers_bak',
  object_type: 'table',
  description: null,
  description_source: null,
  owner: null,
  owner_source: null,
  tags: [],
  row_count_estimate: 40_000,
  size_bytes_estimate: 12 * 1024 * 1024,
  source_created_at: ago(500 * DAY),
  source_last_modified_at: ago(90 * DAY),
  columns: [],
  freshness: freshnessOk(5 * DAY),
}

// ---- Dataset entities (raw-events-s3, stale connection) ----

export const customersSnapshotDataset: AssetEntity = {
  id: 'ent-customers-snapshot',
  urn: 'urn:s3:raw-events/customers_snapshot',
  entity_type: 'dataset',
  source_type: 's3',
  data_plane_id: 'dp-prod',
  data_plane_name: 'customer-prod-vpc',
  source_connection_id: 'sc-raw-events-s3',
  source_connection_name: 'raw-events-s3',
  first_seen_at: ago(60 * DAY),
  last_scraped_at: ago(9 * DAY),
  is_deleted: false,
  bucket: 'raw-events',
  prefix: 'customers_snapshot/',
  fully_qualified_name: 's3://raw-events/customers_snapshot/',
  file_format: 'mixed',
  schema_inferred: false,
  object_count_estimate: 1204,
  total_size_bytes_estimate: Math.round(18.4 * 1024 * 1024 * 1024),
  description: null,
  description_source: null,
  owner: null,
  owner_source: null,
  tags: [],
  sample_key_prefixes: [
    'customers_snapshot/2026-08-30/',
    'customers_snapshot/2026-08-31/',
    'customers_snapshot/2026-09-01/',
  ],
  freshness: freshnessOk(9 * DAY),
}

export const eventsParquetDataset: AssetEntity = {
  id: 'ent-events-parquet',
  urn: 'urn:s3:raw-events/events_parquet',
  entity_type: 'dataset',
  source_type: 's3',
  data_plane_id: 'dp-prod',
  data_plane_name: 'customer-prod-vpc',
  source_connection_id: 'sc-raw-events-s3',
  source_connection_name: 'raw-events-s3',
  first_seen_at: ago(60 * DAY),
  last_scraped_at: ago(9 * DAY),
  is_deleted: false,
  bucket: 'raw-events',
  prefix: 'events_parquet/',
  fully_qualified_name: 's3://raw-events/events_parquet/',
  file_format: 'parquet',
  schema_inferred: true,
  object_count_estimate: 8_450,
  total_size_bytes_estimate: Math.round(2.1 * 1024 * 1024 * 1024),
  description: 'Daily partitioned event stream export.',
  description_source: 'manual',
  owner: 'eli@co',
  owner_source: 'manual',
  tags: ['events'],
  fields: [
    { name: 'event_id', ordinal_position: 1, native_data_type: 'BYTE_ARRAY (UTF8)', normalized_data_type: 'string', is_nullable: false, is_primary_key: false, is_foreign_key: false, foreign_key_ref: null, description: null, tags: [] },
    { name: 'occurred_at', ordinal_position: 2, native_data_type: 'INT64 (TIMESTAMP_MILLIS)', normalized_data_type: 'timestamp', is_nullable: false, is_primary_key: false, is_foreign_key: false, foreign_key_ref: null, description: null, tags: [] },
  ],
  freshness: freshnessOk(9 * DAY),
}

// ---- Table entities (orders-pg, FAILED connection but recent successful history -> scrape_issue) ----

export const sessionsTable: AssetEntity = {
  id: 'ent-sessions',
  urn: 'urn:postgres:orders-db-1:public:public.sessions',
  entity_type: 'table',
  source_type: 'postgres',
  data_plane_id: 'dp-prod',
  data_plane_name: 'customer-prod-vpc',
  source_connection_id: 'sc-orders-pg',
  source_connection_name: 'orders-pg',
  first_seen_at: ago(120 * DAY),
  last_scraped_at: ago(6 * HOUR),
  is_deleted: false,
  database_name: 'orders-db',
  schema_name: 'public',
  table_name: 'sessions',
  fully_qualified_name: 'postgres://orders-db/public.sessions',
  object_type: 'table',
  description: 'User session records.',
  description_source: 'source_comment',
  owner: 'eli@co',
  owner_source: 'source',
  tags: [],
  row_count_estimate: 85_000,
  size_bytes_estimate: 20 * 1024 * 1024,
  source_created_at: ago(300 * DAY),
  source_last_modified_at: ago(6 * HOUR),
  columns: [
    { name: 'id', ordinal_position: 1, native_data_type: 'bigint', normalized_data_type: 'integer', is_nullable: false, is_primary_key: true, is_foreign_key: false, foreign_key_ref: null, description: null, tags: [] },
    { name: 'user_id', ordinal_position: 2, native_data_type: 'bigint', normalized_data_type: 'integer', is_nullable: false, is_primary_key: false, is_foreign_key: false, foreign_key_ref: null, description: null, tags: [] },
  ],
  freshness: freshnessScrapeIssue(6 * HOUR, 'failed'),
}

export const eventsRawTable: AssetEntity = {
  ...sessionsTable,
  id: 'ent-events-raw',
  urn: 'urn:postgres:orders-db-1:public:public.events_raw',
  table_name: 'events_raw',
  fully_qualified_name: 'postgres://orders-db/public.events_raw',
  description: null,
  description_source: null,
  owner: null,
  owner_source: null,
  columns: [],
}

// ---- Search index (denormalized) ----

function toSearchResult(e: AssetEntity): SearchResultItem {
  return {
    urn: e.urn,
    entity_type: e.entity_type,
    name: e.entity_type === 'table' ? e.table_name : e.prefix.replace(/\/$/, ''),
    fully_qualified_name: e.fully_qualified_name,
    source_type: e.source_type,
    source_connection_id: e.source_connection_id,
    source_connection_name: e.source_connection_name,
    file_format: e.entity_type === 'dataset' ? e.file_format : undefined,
    description: e.description,
    owner: e.owner,
    owner_source: e.owner_source,
    tags: e.tags,
    last_scraped_at: e.last_scraped_at,
    freshness: e.freshness,
  }
}

export const allEntities: AssetEntity[] = [
  customersTable,
  plansTable,
  legacyCustomersBakTable,
  customersSnapshotDataset,
  eventsParquetDataset,
  sessionsTable,
  eventsRawTable,
]

export const searchableEntities: AssetEntity[] = allEntities.filter((e) => !e.is_deleted)
export const allSearchResults: SearchResultItem[] = searchableEntities.map(toSearchResult)

// ---- Sources status ----

export const sourcesStatusFixture: SourcesStatusResponse = {
  data_planes: [
    {
      id: 'dp-prod',
      name: 'customer-prod-vpc',
      source_connections: [
        {
          id: 'sc-prod-postgres-1',
          name: 'prod-postgres-1',
          type: 'postgres',
          data_plane_id: 'dp-prod',
          data_plane_name: 'customer-prod-vpc',
          status: 'ok',
          asset_count: 2,
          tombstoned_count: 1,
          scrape_interval_seconds: SIX_HOUR_INTERVAL,
          last_scrape_at: ago(20 * 60 * 1000),
          last_scrape_status: 'success',
          last_attempt_at: ago(20 * 60 * 1000),
          consecutive_failure_count: 0,
          error_summary: null,
          scrape_runs: [
            { id: 'run-1', source_connection_id: 'sc-prod-postgres-1', started_at: ago(20 * 60 * 1000 + 4000), completed_at: ago(20 * 60 * 1000), status: 'success', entities_seen_count: 3, entities_created_count: 0, entities_tombstoned_count: 0, error_summary: null },
            { id: 'run-2', source_connection_id: 'sc-prod-postgres-1', started_at: ago(6 * HOUR + 20 * 60 * 1000 + 4000), completed_at: ago(6 * HOUR + 20 * 60 * 1000), status: 'success', entities_seen_count: 3, entities_created_count: 1, entities_tombstoned_count: 0, error_summary: null },
            { id: 'run-3', source_connection_id: 'sc-prod-postgres-1', started_at: ago(12 * HOUR + 20 * 60 * 1000 + 4000), completed_at: ago(12 * HOUR + 20 * 60 * 1000), status: 'success', entities_seen_count: 2, entities_created_count: 0, entities_tombstoned_count: 1, error_summary: null },
          ],
          tombstoned_entities: [
            { urn: legacyCustomersBakTable.urn, name: 'legacy_customers_bak', entity_type: 'table', last_scraped_at: legacyCustomersBakTable.last_scraped_at },
          ],
        },
        {
          id: 'sc-raw-events-s3',
          name: 'raw-events-s3',
          type: 's3',
          data_plane_id: 'dp-prod',
          data_plane_name: 'customer-prod-vpc',
          status: 'stale',
          asset_count: 2,
          tombstoned_count: 0,
          scrape_interval_seconds: SIX_HOUR_INTERVAL,
          last_scrape_at: ago(9 * DAY),
          last_scrape_status: 'success',
          last_attempt_at: ago(9 * DAY),
          consecutive_failure_count: 0,
          error_summary: null,
          scrape_runs: [
            { id: 'run-4', source_connection_id: 'sc-raw-events-s3', started_at: ago(9 * DAY + 5000), completed_at: ago(9 * DAY), status: 'success', entities_seen_count: 2, entities_created_count: 0, entities_tombstoned_count: 0, error_summary: null },
          ],
          tombstoned_entities: [],
        },
        {
          id: 'sc-legacy-pg',
          name: 'legacy-pg',
          type: 'postgres',
          data_plane_id: 'dp-prod',
          data_plane_name: 'customer-prod-vpc',
          status: 'failed',
          asset_count: 0,
          tombstoned_count: 0,
          scrape_interval_seconds: SIX_HOUR_INTERVAL,
          last_scrape_at: null,
          last_scrape_status: 'failed',
          last_attempt_at: (() => {
            const d = new Date()
            d.setHours(9, 11, 0, 0)
            return d.toISOString()
          })(),
          consecutive_failure_count: 3,
          error_summary: 'connection refused to source DB',
          scrape_runs: [
            { id: 'run-5', source_connection_id: 'sc-legacy-pg', started_at: ago(30 * 60 * 1000 + 2000), completed_at: ago(30 * 60 * 1000), status: 'failed', entities_seen_count: 0, entities_created_count: 0, entities_tombstoned_count: 0, error_summary: 'connection refused to source DB' },
            { id: 'run-6', source_connection_id: 'sc-legacy-pg', started_at: ago(6 * HOUR + 30 * 60 * 1000 + 2000), completed_at: ago(6 * HOUR + 30 * 60 * 1000), status: 'failed', entities_seen_count: 0, entities_created_count: 0, entities_tombstoned_count: 0, error_summary: 'connection refused to source DB' },
            { id: 'run-7', source_connection_id: 'sc-legacy-pg', started_at: ago(12 * HOUR + 30 * 60 * 1000 + 2000), completed_at: ago(12 * HOUR + 30 * 60 * 1000), status: 'failed', entities_seen_count: 0, entities_created_count: 0, entities_tombstoned_count: 0, error_summary: 'connection refused to source DB' },
          ],
          tombstoned_entities: [],
        },
        {
          id: 'sc-orders-pg',
          name: 'orders-pg',
          type: 'postgres',
          data_plane_id: 'dp-prod',
          data_plane_name: 'customer-prod-vpc',
          status: 'failed',
          asset_count: 2,
          tombstoned_count: 0,
          scrape_interval_seconds: SIX_HOUR_INTERVAL,
          last_scrape_at: ago(6 * HOUR),
          last_scrape_status: 'failed',
          last_attempt_at: ago(15 * 60 * 1000),
          consecutive_failure_count: 1,
          error_summary: "auth rejected: password authentication failed for user 'catalog_reader'",
          scrape_runs: [
            { id: 'run-8', source_connection_id: 'sc-orders-pg', started_at: ago(15 * 60 * 1000 + 1000), completed_at: ago(15 * 60 * 1000), status: 'failed', entities_seen_count: 0, entities_created_count: 0, entities_tombstoned_count: 0, error_summary: "auth rejected: password authentication failed for user 'catalog_reader'" },
            { id: 'run-9', source_connection_id: 'sc-orders-pg', started_at: ago(6 * HOUR + 4000), completed_at: ago(6 * HOUR), status: 'success', entities_seen_count: 2, entities_created_count: 0, entities_tombstoned_count: 0, error_summary: null },
            { id: 'run-10', source_connection_id: 'sc-orders-pg', started_at: ago(12 * HOUR + 4000), completed_at: ago(12 * HOUR), status: 'success', entities_seen_count: 2, entities_created_count: 0, entities_tombstoned_count: 0, error_summary: null },
          ],
          tombstoned_entities: [],
        },
      ],
    },
    {
      id: 'dp-staging',
      name: 'customer-staging-vpc',
      source_connections: [
        {
          id: 'sc-staging-pg',
          name: 'staging-pg',
          type: 'postgres',
          data_plane_id: 'dp-staging',
          data_plane_name: 'customer-staging-vpc',
          status: 'never',
          asset_count: 0,
          tombstoned_count: 0,
          scrape_interval_seconds: SIX_HOUR_INTERVAL,
          last_scrape_at: null,
          last_scrape_status: null,
          last_attempt_at: null,
          consecutive_failure_count: 0,
          error_summary: null,
          scrape_runs: [],
          tombstoned_entities: [],
        },
      ],
    },
  ],
}

export const emptySourcesStatusFixture: SourcesStatusResponse = { data_planes: [] }
