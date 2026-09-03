import { apiFetch } from './client'
import type {
  AssetResponse,
  DataPlaneGroup,
  RawSourceConnectionStatus,
  RawSourcesStatusResponse,
  RawSourceStatus,
  ScrapeNowResponse,
  ScrapeRunStatus,
  SearchParams,
  SearchResponse,
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
export function searchCatalog(params: SearchParams): Promise<SearchResponse> {
  const qs = new URLSearchParams()
  qs.set('q', params.q)
  if (params.entityTypes?.length) qs.set('entity_type', params.entityTypes.join(','))
  if (params.sourceConnectionIds?.length) qs.set('source_connection_id', params.sourceConnectionIds.join(','))
  if (params.tags?.length) qs.set('tags', params.tags.join(','))
  if (params.sort) qs.set('sort', params.sort)
  return apiFetch<SearchResponse>(`/v1/catalog/search?${qs.toString()}`)
}

/**
 * GET /v1/catalog/tables/{urn} — architecture.md §8. Despite the "tables"
 * path segment, this is documented as the single asset-detail endpoint for
 * both Table and Dataset entities (design.md's generic "Asset" term); the
 * urn's namespace prefix (`urn:postgres:...` vs `urn:s3:...`) tells the
 * backend which entity type to return. urn must be a raw (non-encoded)
 * value; this function handles the URI encoding.
 */
export function getAsset(urn: string): Promise<AssetResponse> {
  return apiFetch<AssetResponse>(`/v1/catalog/tables/${encodeURIComponent(urn)}`)
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
