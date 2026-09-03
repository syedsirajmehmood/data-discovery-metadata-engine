import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { renderAtRoute } from '../test/renderWithRouter'
import { SearchResultsPage } from './SearchResultsPage'
import * as catalogApi from '../api/catalog'
import type { SearchResponse } from '../types/catalog'

vi.mock('../api/catalog', () => ({
  searchCatalog: vi.fn(),
}))

const searchCatalogMock = vi.mocked(catalogApi.searchCatalog)

function makeResponse(overrides: Partial<SearchResponse> = {}): SearchResponse {
  return {
    query: 'customers',
    total: 1,
    results: [
      {
        urn: 'urn:postgres:prod-db-1:analytics:public.customers',
        entity_type: 'table',
        name: 'customers',
        fully_qualified_name: 'postgres://prod-db/public.customers',
        source_type: 'postgres',
        source_connection_id: 'sc-1',
        source_connection_name: 'prod-postgres-1',
        description: 'Customer master record.',
        owner: 'jane@co',
        owner_source: 'source',
        tags: ['pii'],
        last_scraped_at: new Date().toISOString(),
        freshness: {
          stale_threshold_seconds: 12 * 3600,
          latest_scrape_run_status: 'success',
          last_successful_scrape_at: new Date().toISOString(),
          has_any_scrape_run: true,
        },
      },
    ],
    facets: {
      entity_type: [{ value: 'table', count: 1 }],
      source_connection: [{ value: { id: 'sc-1', name: 'prod-postgres-1' }, count: 1 }],
      tags: [{ value: 'pii', count: 1 }],
    },
    degraded_source_connections: [],
    ...overrides,
  }
}

describe('SearchResultsPage', () => {
  beforeEach(() => {
    searchCatalogMock.mockReset()
    window.localStorage.clear()
  })

  it('shows the recently-viewed landing state on an empty query', () => {
    renderAtRoute(<SearchResultsPage />, '/search', '/search')
    expect(screen.getByText('Recently viewed')).toBeInTheDocument()
    expect(screen.getByText(/Nothing viewed yet/)).toBeInTheDocument()
    expect(searchCatalogMock).not.toHaveBeenCalled()
  })

  it('shows a loading skeleton then results', async () => {
    let resolvePromise!: (v: SearchResponse) => void
    searchCatalogMock.mockReturnValue(
      new Promise((resolve) => {
        resolvePromise = resolve
      }),
    )
    renderAtRoute(<SearchResultsPage />, '/search', '/search?q=customers')

    expect(screen.getByLabelText('Loading results')).toBeInTheDocument()

    resolvePromise(makeResponse())

    await waitFor(() => expect(screen.getByText(/customers/, { selector: '.result-row__location' })).toBeInTheDocument())
    expect(screen.getByText('"customers" — 1 result')).toBeInTheDocument()
  })

  it('shows the zero-results state with a link to Sources', async () => {
    searchCatalogMock.mockResolvedValue(makeResponse({ total: 0, results: [] }))
    renderAtRoute(<SearchResultsPage />, '/search', '/search?q=nope')

    await waitFor(() => expect(screen.getByText(/No assets match/)).toBeInTheDocument())
    expect(screen.getByRole('link', { name: /check source status/i })).toHaveAttribute('href', '/sources')
  })

  it('shows the search-backend-error banner with retry', async () => {
    searchCatalogMock.mockRejectedValue(new Error('boom'))
    renderAtRoute(<SearchResultsPage />, '/search', '/search?q=customers')

    await waitFor(() => expect(screen.getByText('Search is temporarily unavailable.')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })

  it('shows the degraded-sources banner when sources are degraded', async () => {
    searchCatalogMock.mockResolvedValue(
      makeResponse({ degraded_source_connections: [{ id: 'sc-2', name: 'raw-events-s3' }] }),
    )
    renderAtRoute(<SearchResultsPage />, '/search', '/search?q=customers')

    await waitFor(() => expect(screen.getByText(/haven't completed a scrape recently/)).toBeInTheDocument())
  })

  it('renders owner as "no owner set" and description as "No description" when absent', async () => {
    searchCatalogMock.mockResolvedValue(
      makeResponse({
        results: [
          {
            ...makeResponse().results[0],
            owner: null,
            owner_source: null,
            description: null,
          },
        ],
      }),
    )
    renderAtRoute(<SearchResultsPage />, '/search', '/search?q=customers')

    await waitFor(() => expect(screen.getByText(/no owner set/)).toBeInTheDocument())
    expect(screen.getByText('No description')).toBeInTheDocument()
  })

  it('toggling a facet checkbox re-triggers a search with the filter applied', async () => {
    const user = userEvent.setup()
    searchCatalogMock.mockResolvedValue(makeResponse())
    renderAtRoute(<SearchResultsPage />, '/search', '/search?q=customers')

    await waitFor(() => expect(screen.getByText('Table (1)')).toBeInTheDocument())
    searchCatalogMock.mockClear()
    searchCatalogMock.mockResolvedValue(makeResponse())

    await user.click(screen.getByLabelText('Table (1)'))

    await waitFor(() =>
      expect(searchCatalogMock).toHaveBeenCalledWith(expect.objectContaining({ entityTypes: ['table'] })),
    )
  })
})
