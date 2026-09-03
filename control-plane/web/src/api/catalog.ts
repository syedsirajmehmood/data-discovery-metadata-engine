import { apiFetch } from './client'
import type {
  AssetResponse,
  ScrapeNowResponse,
  SearchParams,
  SearchResponse,
  SourcesStatusResponse,
} from '../types/catalog'

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
  const qs = sourceConnectionId ? `?source_connection_id=${encodeURIComponent(sourceConnectionId)}` : ''
  return apiFetch<SourcesStatusResponse>(`/v1/catalog/sources/status${qs}`)
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
