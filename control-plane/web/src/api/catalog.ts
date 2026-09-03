import { apiFetch } from './client'
import type {
  AssetResponse,
  Column,
  DataPlaneGroup,
  DescriptionSource,
  EntityKind,
  OwnerSource,
  RawColumnDetail,
  RawSearchResponse,
  RawSearchResultItem,
  RawSourceConnectionStatus,
  RawSourcesStatusResponse,
  RawSourceStatus,
  RawTableDetailResponse,
  ScrapeNowResponse,
  ScrapeRunStatus,
  SearchParams,
  SearchResponse,
  SearchResultItem,
  SourceConnectionStatus,
  SourceConnectionSummary,
  SourceType,
  SourcesStatusResponse,
} from '../types/catalog'

// Assumed default scrape interval (spec.md NFR-1's stated default) used only
// for staleness math below — the real per-connection configured interval is
// not returned by GET /v1/catalog/sources/status, so this is a fixed
// approximation, not a per-source value. Flagged in mapSourcesStatusResponse.
const ASSUMED_SCRAPE_INTERVAL_SECONDS = 6 * 60 * 60

function inferSourceType(sourceConnectionId: string): SourceType {
  // The backend's SourceConnectionStatus doesn't include a connector_type
  // field, so this infers it from the id string as a best effort. A real
  // fix means adding connector_type to the backend response, not guessing
  // client-side — left as a known gap (see status.md, 2026-09-03).
  const id = sourceConnectionId.toLowerCase()
  if (id.includes('s3') || id.includes('minio')) return 's3'
  return 'postgres'
}

function deriveStatus(
  raw: RawSourceConnectionStatus,
  intervalSeconds: number,
): SourceConnectionStatus {
  if (!raw.last_run_started_at) return 'never'
  if (raw.last_run_status === 'failed') return 'failed'
  if (raw.last_run_status === 'partial_failure') return 'stale'
  const lastTimestamp = raw.last_run_completed_at ?? raw.last_run_started_at
  const ageSeconds = (Date.now() - new Date(lastTimestamp).getTime()) / 1000
  return ageSeconds > intervalSeconds * 2 ? 'stale' : 'ok'
}

function mapSourceConnection(raw: RawSourceConnectionStatus, dp: RawSourceStatus): SourceConnectionSummary {
  const status = deriveStatus(raw, ASSUMED_SCRAPE_INTERVAL_SECONDS)
  const activeCount = Math.max(0, raw.entities_seen_count - raw.entities_tombstoned_count)
  return {
    id: raw.source_connection_id,
    name: raw.source_connection_id,
    type: inferSourceType(raw.source_connection_id),
    data_plane_id: dp.data_plane_id,
    data_plane_name: dp.data_plane_name ?? dp.data_plane_id,
    status,
    asset_count: activeCount,
    tombstoned_count: raw.entities_tombstoned_count,
    // Not returned by the backend (no per-connection configured-interval
    // field on SourceConnectionStatus) — see ASSUMED_SCRAPE_INTERVAL_SECONDS.
    scrape_interval_seconds: ASSUMED_SCRAPE_INTERVAL_SECONDS,
    last_scrape_at: raw.last_run_completed_at ?? raw.last_run_started_at,
    last_scrape_status: raw.last_run_status as ScrapeRunStatus | null,
    last_attempt_at: raw.last_run_started_at,
    // Not tracked by the backend (a single snapshot, not run history) —
    // approximated as 1 if the latest run failed, 0 otherwise.
    consecutive_failure_count: raw.last_run_status === 'failed' ? 1 : 0,
    error_summary: raw.error_summary,
    // The backend doesn't scope this endpoint by source_connection_id
    // (router.py's get_sources_status ignores any such param and always
    // returns every connection's latest snapshot) and has no run-history
    // table wired up yet (see RUNBOOK.md's "What this exercise found" —
    // scrape_run entities only reach ClickHouse, not this endpoint's
    // Postgres-backed source). The one data point available (the latest
    // run) is surfaced as a single-entry history so the Detail page shows
    // real data instead of "no scrape runs yet" when a run did happen.
    scrape_runs: raw.last_run_started_at
      ? [
          {
            id: `${raw.source_connection_id}-latest`,
            source_connection_id: raw.source_connection_id,
            started_at: raw.last_run_started_at,
            completed_at: raw.last_run_completed_at,
            status: (raw.last_run_status ?? 'running') as ScrapeRunStatus,
            entities_seen_count: raw.entities_seen_count,
            entities_created_count: raw.entities_created_count,
            entities_tombstoned_count: raw.entities_tombstoned_count,
            error_summary: raw.error_summary,
          },
        ]
      : [],
    // Not available from this endpoint at all (no tombstoned-entity list
    // in the backend response) — left empty rather than fabricated.
    tombstoned_entities: [],
  }
}

/**
 * Accepts either shape: the real backend's `{ sources: [...] }` (mapped
 * below) or the mock-fetch layer's already-UI-shaped `{ data_planes: [...] }`
 * (passed through unchanged — src/api/mocks/fixtures.ts's rich fixtures,
 * and the 45 existing tests built against them, are left untouched rather
 * than degraded to what the real backend can currently express).
 */
function mapSourcesStatusResponse(
  raw: RawSourcesStatusResponse | SourcesStatusResponse,
): SourcesStatusResponse {
  if ('data_planes' in raw) return raw
  const data_planes: DataPlaneGroup[] = raw.sources.map((dp) => ({
    id: dp.data_plane_id,
    name: dp.data_plane_name ?? dp.data_plane_id,
    source_connections: dp.source_connections.map((sc) => mapSourceConnection(sc, dp)),
  }))
  return { data_planes }
}

/** GET /v1/catalog/search — architecture.md §8. */
/**
 * Accepts either shape: the real backend's minimal `{total, results}` (mapped
 * below) or the mock-fetch layer's already-UI-shaped full `SearchResponse`
 * (passed through unchanged, same reasoning as mapSourcesStatusResponse).
 */
function mapSearchResponse(raw: RawSearchResponse | SearchResponse, query: string): SearchResponse {
  if ('facets' in raw) return raw
  const results: SearchResultItem[] = raw.results.map((item: RawSearchResultItem) => ({
    urn: item.urn,
    entity_type: item.entity_type as EntityKind,
    name: item.name ?? item.urn,
    fully_qualified_name: item.fully_qualified_name ?? item.urn,
    source_type: (item.source_type ?? 'postgres') as SourceType,
    // Not returned by the backend's SearchResultItem at all (see
    // api/catalog/schemas.py) — no way to recover which source connection
    // produced a result from this endpoint today. Left blank rather than
    // guessed; the result row just renders no connection name.
    source_connection_id: '',
    source_connection_name: '',
    description: item.description,
    owner: item.owner,
    owner_source: null, // not returned by the backend
    tags: item.tags,
    last_scraped_at: item.last_scraped_at,
    // FreshnessBadge/computeFreshness require this object unconditionally
    // (design.md §5: one shared component, no per-screen reimplementation)
    // but the backend doesn't return per-result freshness context. Built
    // from the one real field available (last_scraped_at) plus the same
    // assumed-interval approximation used in mapSourcesStatusResponse —
    // "success"/has-run-at-all is inferred from last_scraped_at being
    // non-null, not from real Scrape Run data.
    freshness: {
      stale_threshold_seconds: ASSUMED_SCRAPE_INTERVAL_SECONDS * 2,
      latest_scrape_run_status: item.last_scraped_at ? 'success' : null,
      last_successful_scrape_at: item.last_scraped_at,
      has_any_scrape_run: item.last_scraped_at !== null,
    },
  }))
  return {
    query,
    total: raw.total,
    results,
    // Not computed by the backend (GET /v1/catalog/search returns no facet
    // counts) — empty rather than fabricated; the filter sidebar renders
    // with no options instead of crashing on an undefined facets object.
    facets: { entity_type: [], source_connection: [], tags: [] },
    // Same root gap as sources/status always being empty (RUNBOOK.md) —
    // the backend has no wired-up notion of "which sources are currently
    // degraded" to surface here yet.
    degraded_source_connections: [],
  }
}

export function searchCatalog(params: SearchParams): Promise<SearchResponse> {
  const qs = new URLSearchParams()
  qs.set('q', params.q)
  if (params.entityTypes?.length) qs.set('entity_type', params.entityTypes.join(','))
  if (params.sourceConnectionIds?.length) qs.set('source_connection_id', params.sourceConnectionIds.join(','))
  if (params.tags?.length) qs.set('tags', params.tags.join(','))
  if (params.sort) qs.set('sort', params.sort)
  return apiFetch<RawSearchResponse | SearchResponse>(`/v1/catalog/search?${qs.toString()}`).then((res) =>
    mapSearchResponse(res, params.q),
  )
}

/**
 * GET /v1/catalog/tables/{urn} — architecture.md §8. Despite the "tables"
 * path segment, this is documented as the single asset-detail endpoint for
 * both Table and Dataset entities (design.md's generic "Asset" term); the
 * urn's namespace prefix (`urn:postgres:...` vs `urn:s3:...`) tells the
 * backend which entity type to return. urn must be a raw (non-encoded)
 * value; this function handles the URI encoding.
 */
function mapForeignKeyRef(ref: RawColumnDetail['foreign_key_ref']): string | null {
  if (!ref) return null
  const table = ref.table_urn ?? '?'
  const column = ref.column ?? '?'
  return `${table}.${column}`
}

function mapColumn(raw: RawColumnDetail): Column {
  return {
    name: raw.name,
    ordinal_position: raw.ordinal_position,
    native_data_type: raw.native_data_type,
    normalized_data_type: raw.normalized_data_type,
    is_nullable: raw.is_nullable,
    is_primary_key: raw.is_primary_key,
    is_foreign_key: raw.is_foreign_key,
    foreign_key_ref: mapForeignKeyRef(raw.foreign_key_ref),
    description: raw.description,
    tags: raw.tags,
  }
}

/**
 * Accepts either shape: the real backend's `RawTableDetailResponse` (mapped
 * below, Table entities only — see RawTableDetailResponse's doc comment on
 * the Dataset gap) or the mock-fetch layer's already-UI-shaped
 * `AssetResponse` (passed through unchanged, same reasoning as the other
 * mapXResponse functions in this file).
 */
function mapAssetResponse(raw: RawTableDetailResponse | AssetResponse): AssetResponse {
  if ('entity_type' in raw) return raw
  const { table, columns } = raw
  return {
    id: table.urn,
    urn: table.urn,
    data_plane_id: table.data_plane_id,
    // Not returned by the backend (only the id) — defaulted to the id
    // itself rather than fabricated.
    data_plane_name: table.data_plane_id,
    source_connection_id: table.source_connection_id,
    source_connection_name: table.source_connection_id,
    first_seen_at: table.first_seen_at ?? '',
    last_scraped_at: table.last_scraped_at,
    is_deleted: table.is_deleted,
    entity_type: 'table',
    source_type: 'postgres',
    database_name: table.database_name,
    schema_name: table.schema_name,
    table_name: table.table_name,
    fully_qualified_name: table.fully_qualified_name,
    object_type: table.object_type as 'table' | 'view' | 'materialized_view',
    description: table.description,
    description_source: table.description_source as DescriptionSource | null,
    owner: table.owner,
    owner_source: table.owner_source as OwnerSource | null,
    tags: table.tags,
    row_count_estimate: table.row_count_estimate,
    size_bytes_estimate: table.size_bytes_estimate,
    // Not returned by the backend's TableDetail at all (spec.md's schema
    // has these fields; FE2's response model doesn't expose them yet).
    source_created_at: null,
    source_last_modified_at: null,
    columns: columns.map(mapColumn),
    // See mapSearchResponse's freshness comment — same approximation.
    freshness: {
      stale_threshold_seconds: ASSUMED_SCRAPE_INTERVAL_SECONDS * 2,
      latest_scrape_run_status: table.last_scraped_at ? 'success' : null,
      last_successful_scrape_at: table.last_scraped_at,
      has_any_scrape_run: table.last_scraped_at !== null,
    },
  }
}

export function getAsset(urn: string): Promise<AssetResponse> {
  return apiFetch<RawTableDetailResponse | AssetResponse>(`/v1/catalog/tables/${encodeURIComponent(urn)}`).then(
    mapAssetResponse,
  )
}

/**
 * GET /v1/catalog/sources/status — architecture.md §8.
 *
 * JUDGMENT CALL: architecture.md documents exactly this one sources-status
 * endpoint, with no separate per-connection detail endpoint. To support
 * the Source Connection Detail screen's scrape-run history and tombstoned
 * list (design.md §4.2) without inventing a new route outside the
 * documented API surface, an optional `source_connection_id` scopes the
 * same endpoint to one connection and additionally populates
 * `scrape_runs` / `tombstoned_entities` (omitted on the unscoped list call
 * to keep that payload light). See README "API assumptions".
 */
export function getSourcesStatus(sourceConnectionId?: string): Promise<SourcesStatusResponse> {
  // sourceConnectionId is accepted for API-shape compatibility with callers
  // (SourceConnectionDetailPage) but the backend ignores it and always
  // returns every connection — see mapSourcesStatusResponse's doc comment.
  const qs = sourceConnectionId ? `?source_connection_id=${encodeURIComponent(sourceConnectionId)}` : ''
  return apiFetch<RawSourcesStatusResponse | SourcesStatusResponse>(`/v1/catalog/sources/status${qs}`).then(
    mapSourcesStatusResponse,
  )
}

/**
 * POST /v1/catalog/sources/{source_connection_id}/scrape
 *
 * NOT part of architecture.md's documented catalog read API — this
 * endpoint does not exist on the backend yet as of this writing. Called
 * anyway per design.md §4.2's [Scrape now] requirement; the UI treats a
 * 404/501 as "not yet supported" rather than crashing. Expected contract
 * once built (architecture.md §5's command-queue pattern): enqueues a
 * "scrape now" command that the data-plane agent picks up on its next
 * outbound poll of GET /v1/commands — this call queues work, it does not
 * synchronously run a scrape.
 */
export function triggerScrapeNow(sourceConnectionId: string): Promise<ScrapeNowResponse> {
  return apiFetch<ScrapeNowResponse>(`/v1/catalog/sources/${encodeURIComponent(sourceConnectionId)}/scrape`, {
    method: 'POST',
  })
}
