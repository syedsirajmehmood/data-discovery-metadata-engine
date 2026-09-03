import { screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { renderAtRoute } from '../test/renderWithRouter'
import { SourceConnectionListPage } from './SourceConnectionListPage'
import * as catalogApi from '../api/catalog'
import type { SourcesStatusResponse } from '../types/catalog'

vi.mock('../api/catalog', () => ({
  getSourcesStatus: vi.fn(),
}))

const getSourcesStatusMock = vi.mocked(catalogApi.getSourcesStatus)

const fixture: SourcesStatusResponse = {
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
          asset_count: 128,
          tombstoned_count: 0,
          scrape_interval_seconds: 6 * 3600,
          last_scrape_at: new Date(Date.now() - 20 * 60 * 1000).toISOString(),
          last_scrape_status: 'success',
          last_attempt_at: new Date().toISOString(),
          consecutive_failure_count: 0,
          error_summary: null,
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
          scrape_interval_seconds: 6 * 3600,
          last_scrape_at: null,
          last_scrape_status: 'failed',
          last_attempt_at: (() => {
            const d = new Date()
            d.setHours(9, 11, 0, 0)
            return d.toISOString()
          })(),
          consecutive_failure_count: 3,
          error_summary: 'connection refused to source DB',
        },
      ],
    },
  ],
}

describe('SourceConnectionListPage', () => {
  beforeEach(() => {
    getSourcesStatusMock.mockReset()
  })

  it('groups connections by data plane and shows status/asset/last-scrape/error columns', async () => {
    getSourcesStatusMock.mockResolvedValue(fixture)
    renderAtRoute(<SourceConnectionListPage />, '/sources', '/sources')

    await waitFor(() => expect(screen.getByText(/Data plane: customer-prod-vpc/)).toBeInTheDocument())
    expect(screen.getByRole('link', { name: 'prod-postgres-1' })).toHaveAttribute('href', '/sources/sc-prod-postgres-1')
    expect(screen.getByText('128')).toBeInTheDocument()
    expect(screen.getByText('attempt 09:11')).toBeInTheDocument()
  })

  it('sorts worst-status-first within a data plane', async () => {
    getSourcesStatusMock.mockResolvedValue(fixture)
    renderAtRoute(<SourceConnectionListPage />, '/sources', '/sources')

    await waitFor(() => expect(screen.getAllByRole('link')).toHaveLength(2))
    const links = screen.getAllByRole('link')
    expect(links[0]).toHaveTextContent('legacy-pg')
    expect(links[1]).toHaveTextContent('prod-postgres-1')
  })

  it('shows the onboarding empty state when no sources are connected', async () => {
    getSourcesStatusMock.mockResolvedValue({ data_planes: [] })
    renderAtRoute(<SourceConnectionListPage />, '/sources', '/sources')

    await waitFor(() => expect(screen.getByText('No sources connected yet.')).toBeInTheDocument())
    expect(screen.getByText(/Install the data-plane connector/)).toBeInTheDocument()
  })

  it('shows a distinct generic error banner (not a status dot) when status data itself fails to load', async () => {
    getSourcesStatusMock.mockRejectedValue(new Error('boom'))
    renderAtRoute(<SourceConnectionListPage />, '/sources', '/sources')

    await waitFor(() => expect(screen.getByText('Could not load source connection status.')).toBeInTheDocument())
  })
})
