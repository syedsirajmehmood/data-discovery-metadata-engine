import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { searchCatalog } from '../api/catalog'
import type { EntityKind, SearchResponse, SortOption } from '../types/catalog'
import { ErrorBanner } from '../components/ErrorBanner'
import { FacetFilters, type FacetSelection } from '../components/search/FacetFilters'
import { ResultRow } from '../components/search/ResultRow'
import { SearchResultsSkeleton } from '../components/search/SearchResultsSkeleton'
import { DegradedSourcesBanner } from '../components/search/DegradedSourcesBanner'
import { getRecentlyViewed, type RecentlyViewedEntry } from '../lib/recentlyViewed'
import { EntityIcon, EntityTypeBadge } from '../components/EntityIcon'

type Status = 'idle' | 'loading' | 'success' | 'error'

/**
 * Search Results View (design.md §2). Query state lives in the URL so
 * results are shareable/bookmarkable and the top-nav search box and this
 * page's own state never drift apart.
 */
export function SearchResultsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const q = searchParams.get('q') ?? ''
  const sort = (searchParams.get('sort') as SortOption | null) ?? 'relevance'
  const entityTypes = useMemo(() => (searchParams.get('entity_type')?.split(',').filter(Boolean) ?? []), [searchParams])
  const sourceConnectionIds = useMemo(
    () => searchParams.get('source_connection_id')?.split(',').filter(Boolean) ?? [],
    [searchParams],
  )
  const tags = useMemo(() => searchParams.get('tags')?.split(',').filter(Boolean) ?? [], [searchParams])

  const [status, setStatus] = useState<Status>('idle')
  const [response, setResponse] = useState<SearchResponse | null>(null)
  const [recentlyViewed, setRecentlyViewed] = useState<RecentlyViewedEntry[]>([])

  useEffect(() => {
    if (!q) {
      setRecentlyViewed(getRecentlyViewed())
      setStatus('idle')
      return
    }
    let cancelled = false
    setStatus('loading')
    searchCatalog({ q, entityTypes: entityTypes as EntityKind[], sourceConnectionIds, tags, sort })
      .then((res) => {
        if (cancelled) return
        setResponse(res)
        setStatus('success')
      })
      .catch(() => {
        if (cancelled) return
        setStatus('error')
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, entityTypes.join(','), sourceConnectionIds.join(','), tags.join(','), sort])

  function updateParams(mutator: (p: URLSearchParams) => void) {
    const next = new URLSearchParams(searchParams)
    mutator(next)
    setSearchParams(next)
  }

  function handleFacetChange(selection: FacetSelection) {
    updateParams((p) => {
      if (selection.entityTypes.length) p.set('entity_type', selection.entityTypes.join(','))
      else p.delete('entity_type')

      if (selection.sourceConnectionIds.length) p.set('source_connection_id', selection.sourceConnectionIds.join(','))
      else p.delete('source_connection_id')

      if (selection.tags.length) p.set('tags', selection.tags.join(','))
      else p.delete('tags')
    })
  }

  function handleSortChange(next: SortOption) {
    updateParams((p) => p.set('sort', next))
  }

  // ---- Empty query / landing state ----
  if (!q) {
    return (
      <div className="search-page search-page--landing">
        <h1>Recently viewed</h1>
        {recentlyViewed.length === 0 ? (
          <p className="muted">
            Nothing viewed yet. Try searching above, or <Link to="/sources">browse your sources</Link>.
          </p>
        ) : (
          <ul className="result-list">
            {recentlyViewed.map((entry) => (
              <li key={entry.urn} className="result-row">
                <Link to={`/asset/${encodeURIComponent(entry.urn)}`} className="result-row__link">
                  <div className="result-row__header">
                    <EntityIcon sourceType={entry.source_type} />
                    <EntityTypeBadge entityType={entry.entity_type} />
                    <span className="result-row__source-connection">· {entry.source_connection_name}</span>
                  </div>
                  <div className="result-row__location">{entry.fully_qualified_name}</div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    )
  }

  return (
    <div className="search-page">
      {status === 'success' && response && (
        <FacetFilters
          facets={response.facets}
          selection={{ entityTypes, sourceConnectionIds, tags }}
          onChange={handleFacetChange}
        />
      )}
      {status !== 'success' && <aside className="facet-filters" aria-hidden="true" />}

      <div className="search-page__main">
        {status === 'success' && response && (
          <>
            <div className="search-page__summary">
              <h1>
                &quot;{q}&quot; — {response.total} result{response.total === 1 ? '' : 's'}
              </h1>
              <label className="search-page__sort">
                Sort:{' '}
                <select value={sort} onChange={(e) => handleSortChange(e.target.value as SortOption)}>
                  <option value="relevance">Relevance</option>
                  <option value="recent">Recently scraped</option>
                  <option value="name">Name A-Z</option>
                </select>
              </label>
            </div>

            <DegradedSourcesBanner sources={response.degraded_source_connections} />

            {response.results.length === 0 ? (
              <div className="empty-state">
                <p>No assets match &quot;{q}&quot;.</p>
                <p className="muted">
                  Try removing a filter, or <Link to="/sources">check source status</Link> — not seeing what you
                  expect?
                </p>
              </div>
            ) : (
              <ul className="result-list">
                {response.results.map((r) => (
                  <ResultRow key={r.urn} result={r} />
                ))}
              </ul>
            )}
          </>
        )}

        {status === 'loading' && <SearchResultsSkeleton />}

        {status === 'error' && (
          <ErrorBanner
            message="Search is temporarily unavailable."
            onRetry={() => {
              setStatus('loading')
              searchCatalog({ q, entityTypes: entityTypes as EntityKind[], sourceConnectionIds, tags, sort })
                .then((res) => {
                  setResponse(res)
                  setStatus('success')
                })
                .catch(() => setStatus('error'))
            }}
          />
        )}
      </div>
    </div>
  )
}

