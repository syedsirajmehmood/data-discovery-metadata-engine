/**
 * Types for the catalog read API this UI consumes.
 *
 * Source of truth for field names: `.claude/team/spec.md` (BA metadata
 * schema) and `.claude/team/architecture.md` §4/§8 (documented endpoints:
 * GET /v1/catalog/search, GET /v1/catalog/tables/{urn},
 * GET /v1/catalog/tables/{urn}/lineage, GET /v1/catalog/sources/status).
 *
 * Where architecture.md/spec.md left a response shape unspecified (facet
 * lists, per-connection scrape-run history, tombstoned-entity listing),
 * this file documents the assumed shape inline with a JUDGMENT CALL
 * comment. See control-plane/web/README.md "API assumptions" for the
 * consolidated list.
 */

export type SourceType = 'postgres' | 's3'
export type EntityKind = 'table' | 'dataset'
export type ScrapeRunStatus = 'success' | 'partial_failure' | 'failed' | 'running'
export type DescriptionSource = 'source_comment' | 'manual'
export type OwnerSource = 'source' | 'manual'

/** Common fields present on every entity (spec.md, "common fields" block). */
export interface EntityCommon {
  id: string
  urn: string
  data_plane_id: string
  data_plane_name: string
  source_connection_id: string
  source_connection_name: string
  first_seen_at: string
  last_scraped_at: string | null
  is_deleted: boolean
}

export interface Column {
  name: string
  ordinal_position: number
  native_data_type: string
  normalized_data_type: string
  is_nullable: boolean
  is_primary_key: boolean
  is_foreign_key: boolean
  foreign_key_ref: string | null
  description: string | null
  tags: string[]
}

/**
 * Freshness inputs denormalized onto every entity/search-result so the
 * shared freshness-badge component (design.md §3.3 / §5) can compute a
 * badge without a second round trip per row.
 *
 * JUDGMENT CALL: architecture.md doesn't spell out how a search-result row
 * gets enough source-connection context to render a freshness badge. We
 * assume the search index (OpenSearch, per architecture.md §4) denormalizes
 * these fields from the owning source connection at index time, same as it
 * already denormalizes name/description/tags/owner.
 */
export interface FreshnessContext {
  /** 2x the source connection's configured scrape interval, in seconds. */
  stale_threshold_seconds: number
  /** Status of the most recent Scrape Run attempt for the owning source connection. */
  latest_scrape_run_status: ScrapeRunStatus | null
  /** Timestamp of the last scrape run that completed with status success, for this source connection. */
  last_successful_scrape_at: string | null
  /** False only for a source connection with zero Scrape Runs ever. */
  has_any_scrape_run: boolean
}

export interface TableEntity extends EntityCommon {
  entity_type: 'table'
  source_type: 'postgres'
  database_name: string
  schema_name: string
  table_name: string
  fully_qualified_name: string
  object_type: 'table' | 'view' | 'materialized_view'
  description: string | null
  description_source: DescriptionSource | null
  owner: string | null
  owner_source: OwnerSource | null
  tags: string[]
  row_count_estimate: number | null
  size_bytes_estimate: number | null
  source_created_at: string | null
  source_last_modified_at: string | null
  columns: Column[]
  freshness: FreshnessContext
}

export interface DatasetEntity extends EntityCommon {
  entity_type: 'dataset'
  source_type: 's3'
  bucket: string
  prefix: string
  fully_qualified_name: string
  file_format: 'parquet' | 'csv' | 'json' | 'mixed' | 'unknown' | null
  schema_inferred: boolean
  object_count_estimate: number | null
  total_size_bytes_estimate: number | null
  description: string | null
  description_source: DescriptionSource | null
  owner: string | null
  owner_source: OwnerSource | null
  tags: string[]
  /** Present only when schema_inferred = true. */
  fields?: Column[]
  /**
   * JUDGMENT CALL: design.md §3's "schema not inferred" layout shows
   * "Sample key prefixes" — not itemized in spec.md's Dataset schema.
   * Modeled as optional so the UI degrades gracefully if the backend
   * omits it.
   */
  sample_key_prefixes?: string[]
  freshness: FreshnessContext
}

export type AssetEntity = TableEntity | DatasetEntity

/** GET /v1/catalog/search */
export interface SearchResultItem {
  urn: string
  entity_type: EntityKind
  name: string
  fully_qualified_name: string
  source_type: SourceType
  source_connection_id: string
  source_connection_name: string
  file_format?: DatasetEntity['file_format']
  description: string | null
  owner: string | null
  owner_source: OwnerSource | null
  tags: string[]
  last_scraped_at: string | null
  freshness: FreshnessContext
}

export interface FacetOption<T = string> {
  value: T
  count: number
}

/**
 * JUDGMENT CALL: architecture.md documents GET /v1/catalog/search's
 * existence but not a facet-count shape. We assume the standard
 * faceted-search pattern (facet counts computed over the current query,
 * before the facet filters themselves are applied) since design.md §2
 * requires entity-type/source-connection/tag filters sourced from real
 * data, not a hardcoded list.
 */
export interface SearchFacets {
  entity_type: FacetOption[]
  source_connection: FacetOption<{ id: string; name: string }>[]
  tags: FacetOption[]
}

export interface DegradedSourceConnection {
  id: string
  name: string
}

export interface SearchResponse {
  query: string
  total: number
  results: SearchResultItem[]
  facets: SearchFacets
  /** Source connections stale/failed at query time — drives design.md §2's degraded-sources banner. */
  degraded_source_connections: DegradedSourceConnection[]
}

export type SortOption = 'relevance' | 'recent' | 'name'

export interface SearchParams {
  q: string
  entityTypes?: EntityKind[]
  sourceConnectionIds?: string[]
  tags?: string[]
  sort?: SortOption
}

/** GET /v1/catalog/tables/{urn} — used for both Table and Dataset assets. */
export type AssetResponse = AssetEntity

export interface ScrapeRun {
  id: string
  source_connection_id: string
  started_at: string
  completed_at: string | null
  status: ScrapeRunStatus
  entities_seen_count: number
  entities_created_count: number
  entities_tombstoned_count: number
  error_summary: string | null
}

export type SourceConnectionStatus = 'ok' | 'stale' | 'failed' | 'never'

export interface TombstonedEntitySummary {
  urn: string
  name: string
  entity_type: EntityKind
  last_scraped_at: string | null
}

export interface SourceConnectionSummary {
  id: string
  name: string
  type: SourceType
  data_plane_id: string
  data_plane_name: string
  status: SourceConnectionStatus
  asset_count: number
  tombstoned_count: number
  scrape_interval_seconds: number
  last_scrape_at: string | null
  last_scrape_status: ScrapeRunStatus | null
  /** Timestamp of the most recent attempt, used for the "attempt HH:MM" list-row display when failed. */
  last_attempt_at: string | null
  consecutive_failure_count: number
  error_summary: string | null
  /**
   * Present only on the single-connection-scoped response
   * (?source_connection_id=... — see README "API assumptions").
   */
  scrape_runs?: ScrapeRun[]
  tombstoned_entities?: TombstonedEntitySummary[]
}

export interface DataPlaneGroup {
  id: string
  name: string
  source_connections: SourceConnectionSummary[]
}

/** GET /v1/catalog/sources/status */
export interface SourcesStatusResponse {
  data_planes: DataPlaneGroup[]
}

/**
 * Wire shape of GET /v1/catalog/sources/status, as FE2 actually built it
 * (control-plane/api/catalog/schemas.py: SourcesStatusResponse/SourceStatus/
 * SourceConnectionStatus) — reconciled 2026-09-03 after the shapes above
 * (`data_planes` / `SourceConnectionSummary`, what this page was originally
 * built against) turned out not to match what the backend returns
 * (`sources`, much lower-level per-connection fields, no per-connection
 * `type`, no configured `scrape_interval_seconds`, no consecutive-failure
 * history, no scrape-run history, no tombstoned-entity list). See
 * src/api/catalog.ts's `mapSourcesStatusResponse` for the adapter that
 * turns this into the shape above, and its inline comments for exactly
 * which fields are real vs. a documented best-effort approximation.
 */
export interface RawSourceConnectionStatus {
  source_connection_id: string
  last_run_status: ScrapeRunStatus | null
  last_run_started_at: string | null
  last_run_completed_at: string | null
  entities_seen_count: number
  entities_created_count: number
  entities_tombstoned_count: number
  error_summary: string | null
}

export interface RawSourceStatus {
  data_plane_id: string
  data_plane_name: string | null
  last_seen_at: string | null
  source_connections: RawSourceConnectionStatus[]
}

export interface RawSourcesStatusResponse {
  sources: RawSourceStatus[]
}

/**
 * Wire shape of GET /v1/catalog/search, as FE2 actually built it
 * (control-plane/api/catalog/schemas.py: SearchResponse/SearchResultItem)
 * — reconciled 2026-09-03, same category of gap as the sources/status
 * shapes above: no `facets`, no `degraded_source_connections`, and each
 * result is missing `source_connection_id`/`source_connection_name`/
 * `owner_source`/`freshness` (a computed object every result needs —
 * FreshnessBadge/computeFreshness read it unconditionally, so its absence
 * was an uncaught crash on the search page, not just a missing display
 * field). See src/api/catalog.ts's `mapSearchResponse` for the adapter.
 */
export interface RawSearchResultItem {
  urn: string
  entity_type: string
  source_type: string | null
  name: string | null
  description: string | null
  tags: string[]
  owner: string | null
  fully_qualified_name: string | null
  last_scraped_at: string | null
  score: number | null
}

export interface RawSearchResponse {
  total: number
  results: RawSearchResultItem[]
}

/**
 * Wire shape of GET /v1/catalog/tables/{urn}, as FE2 actually built it
 * (control-plane/api/catalog/schemas.py: TableDetailResponse/TableDetail/
 * ColumnDetail) — reconciled 2026-09-03, same category of gap again: no
 * `id` (only `urn`), no `data_plane_name`/`source_connection_name` (only
 * the ids), no `source_created_at`/`source_last_modified_at`, no
 * `freshness`, and `foreign_key_ref` is a raw object, not the `string |
 * null` this UI's `Column` type expects. See `mapAssetResponse`.
 *
 * Bigger, NOT-fixed-here gap: this endpoint only ever queries Postgres's
 * `TableEntity` table (`RelationalStore.get_table_with_columns`) — an S3
 * Dataset urn 404s here even though FE3's `getAsset` doc comment (and
 * design.md) assume this is "the single asset-detail endpoint for both
 * Table and Dataset entities." Clicking a Dataset search result will 404
 * until the backend adds Dataset lookup to this endpoint. Table urns
 * (Postgres sources) work correctly.
 */
export interface RawColumnDetail {
  urn: string
  table_urn: string
  name: string
  ordinal_position: number
  native_data_type: string
  normalized_data_type: string
  is_nullable: boolean
  is_primary_key: boolean
  is_foreign_key: boolean
  foreign_key_ref: { table_urn?: string; column?: string } | null
  description: string | null
  description_source: string | null
  tags: string[]
}

export interface RawTableDetail {
  urn: string
  fully_qualified_name: string
  source_type: string
  database_name: string
  schema_name: string
  table_name: string
  object_type: string
  description: string | null
  description_source: string | null
  owner: string | null
  owner_source: string | null
  tags: string[]
  row_count_estimate: number | null
  size_bytes_estimate: number | null
  source_connection_id: string
  data_plane_id: string
  first_seen_at: string | null
  last_scraped_at: string | null
  is_deleted: boolean
}

export interface RawTableDetailResponse {
  table: RawTableDetail
  columns: RawColumnDetail[]
}

/**
 * POST /v1/catalog/sources/{source_connection_id}/scrape
 *
 * NOT part of architecture.md's documented catalog read API — this
 * endpoint does not exist in the backend yet. Modeled here per
 * architecture.md §5's forward-compatible pattern ("the agent polls a
 * commands endpoint on its own schedule... just a new outbound call the
 * agent already knows how to make"): the expected contract is that this
 * call enqueues a command for the data-plane agent to pick up on its next
 * poll, not that it triggers a scrape synchronously.
 */
export interface ScrapeNowResponse {
  queued: boolean
  source_connection_id: string
}
