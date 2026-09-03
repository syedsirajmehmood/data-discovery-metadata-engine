import type { SearchFacets, SearchResponse, SourcesStatusResponse } from '../../types/catalog'
import { allEntities, allSearchResults, emptySourcesStatusFixture, sourcesStatusFixture } from './fixtures'

/**
 * Dev-mode fetch mock. Installed by main.tsx when VITE_USE_MOCKS is not
 * explicitly "false" (default: on, since FE2's real backend does not
 * exist in this worktree yet — see README "Running against mocks").
 *
 * This intercepts the exact endpoint shapes documented in
 * architecture.md §8 plus this app's documented extensions
 * (src/types/catalog.ts), so swapping it out for a real backend later is
 * just unsetting VITE_USE_MOCKS / setting VITE_API_BASE_URL.
 *
 * A few query-param triggers exist purely for manually exercising error/
 * empty states in the running dev app (documented in README):
 *   - GET /v1/catalog/search?q=erroritis        -> simulated 500
 *   - GET /v1/catalog/tables/{urn}?simulate=404  -> simulated 404
 *   - GET /v1/catalog/tables/{urn}?simulate=error -> simulated 500
 *   - GET /v1/catalog/sources/status?empty=1     -> onboarding empty state
 */

const MOCK_DELAY_MS = 350

function delay<T>(value: T): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), MOCK_DELAY_MS))
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function buildFacets(): SearchFacets {
  const bySourceConnection = new Map<string, { id: string; name: string; count: number }>()
  const byEntityType = new Map<string, number>()
  const byTag = new Map<string, number>()

  for (const r of allSearchResults) {
    byEntityType.set(r.entity_type, (byEntityType.get(r.entity_type) ?? 0) + 1)
    const existing = bySourceConnection.get(r.source_connection_id)
    bySourceConnection.set(r.source_connection_id, {
      id: r.source_connection_id,
      name: r.source_connection_name,
      count: (existing?.count ?? 0) + 1,
    })
    for (const t of r.tags) byTag.set(t, (byTag.get(t) ?? 0) + 1)
  }

  return {
    entity_type: [...byEntityType.entries()].map(([value, count]) => ({ value, count })),
    source_connection: [...bySourceConnection.values()].map((v) => ({ value: { id: v.id, name: v.name }, count: v.count })),
    tags: [...byTag.entries()].map(([value, count]) => ({ value, count })),
  }
}

function matchesQuery(text: string, q: string): boolean {
  return text.toLowerCase().includes(q.toLowerCase())
}

function handleSearch(url: URL): Promise<Response> {
  const q = url.searchParams.get('q') ?? ''
  if (matchesQuery(q, 'erroritis')) {
    return delay(jsonResponse({ error: 'search_backend_unavailable' }, 500))
  }

  const entityTypeFilter = url.searchParams.get('entity_type')?.split(',').filter(Boolean)
  const sourceConnFilter = url.searchParams.get('source_connection_id')?.split(',').filter(Boolean)
  const tagsFilter = url.searchParams.get('tags')?.split(',').filter(Boolean)
  const sort = url.searchParams.get('sort') ?? 'relevance'

  let results = allSearchResults.filter((r) => {
    if (q) {
      const haystack = [r.name, r.fully_qualified_name, r.description ?? '', ...r.tags].join(' ')
      if (!matchesQuery(haystack, q)) return false
    }
    if (entityTypeFilter?.length && !entityTypeFilter.includes(r.entity_type)) return false
    if (sourceConnFilter?.length && !sourceConnFilter.includes(r.source_connection_id)) return false
    if (tagsFilter?.length && !tagsFilter.some((t) => r.tags.includes(t))) return false
    return true
  })

  if (sort === 'name') {
    results = [...results].sort((a, b) => a.name.localeCompare(b.name))
  } else if (sort === 'recent') {
    results = [...results].sort((a, b) => (b.last_scraped_at ?? '').localeCompare(a.last_scraped_at ?? ''))
  }

  const degraded = sourcesStatusFixture.data_planes
    .flatMap((dp) => dp.source_connections)
    .filter((sc) => sc.status === 'stale' || sc.status === 'failed')
    .map((sc) => ({ id: sc.id, name: sc.name }))

  const body: SearchResponse = {
    query: q,
    total: results.length,
    results,
    facets: buildFacets(),
    degraded_source_connections: degraded,
  }
  return delay(jsonResponse(body))
}

function handleAssetDetail(url: URL, urn: string): Promise<Response> {
  if (url.searchParams.get('simulate') === '404') {
    return delay(jsonResponse({ error: 'not_found' }, 404))
  }
  if (url.searchParams.get('simulate') === 'error') {
    return delay(jsonResponse({ error: 'internal_error' }, 500))
  }
  const entity = allEntities.find((e) => e.urn === urn)
  if (!entity) {
    return delay(jsonResponse({ error: 'not_found' }, 404))
  }
  return delay(jsonResponse(entity))
}

function handleSourcesStatus(url: URL): Promise<Response> {
  if (url.searchParams.get('empty') === '1') {
    const body: SourcesStatusResponse = emptySourcesStatusFixture
    return delay(jsonResponse(body))
  }
  const scopedId = url.searchParams.get('source_connection_id')
  if (!scopedId) {
    // Unscoped list call: strip the heavy per-connection fields.
    const body: SourcesStatusResponse = {
      data_planes: sourcesStatusFixture.data_planes.map((dp) => ({
        ...dp,
        source_connections: dp.source_connections.map(({ scrape_runs: _runs, tombstoned_entities: _te, ...rest }) => rest),
      })),
    }
    return delay(jsonResponse(body))
  }
  const body: SourcesStatusResponse = {
    data_planes: sourcesStatusFixture.data_planes
      .map((dp) => ({ ...dp, source_connections: dp.source_connections.filter((sc) => sc.id === scopedId) }))
      .filter((dp) => dp.source_connections.length > 0),
  }
  return delay(jsonResponse(body))
}

function handleScrapeNow(sourceConnectionId: string): Promise<Response> {
  return delay(jsonResponse({ queued: true, source_connection_id: sourceConnectionId }, 202))
}

export function installMockFetch(): void {
  const realFetch = window.fetch.bind(window)

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const urlString = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
    const url = new URL(urlString, window.location.origin)
    const method = init?.method ?? 'GET'

    if (url.pathname === '/v1/catalog/search' && method === 'GET') {
      return handleSearch(url)
    }

    const assetMatch = url.pathname.match(/^\/v1\/catalog\/tables\/(.+)$/)
    if (assetMatch && method === 'GET' && !url.pathname.endsWith('/lineage')) {
      return handleAssetDetail(url, decodeURIComponent(assetMatch[1]))
    }

    if (url.pathname === '/v1/catalog/sources/status' && method === 'GET') {
      return handleSourcesStatus(url)
    }

    const scrapeMatch = url.pathname.match(/^\/v1\/catalog\/sources\/(.+)\/scrape$/)
    if (scrapeMatch && method === 'POST') {
      return handleScrapeNow(decodeURIComponent(scrapeMatch[1]))
    }

    // Anything else (e.g. the intentionally-unbuilt lineage endpoint) falls
    // through to the real network so it fails loudly rather than silently.
    return realFetch(input, init)
  }
}
