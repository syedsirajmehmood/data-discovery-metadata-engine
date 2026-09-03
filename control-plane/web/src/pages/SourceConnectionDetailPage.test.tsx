import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { renderAtRoute } from '../test/renderWithRouter'
import { SourceConnectionDetailPage } from './SourceConnectionDetailPage'
import * as catalogApi from '../api/catalog'
import { ApiError } from '../api/client'
import type { SourceConnectionSummary, SourcesStatusResponse } from '../types/catalog'

vi.mock('../api/catalog', () => ({
  getSourcesStatus: vi.fn(),
  triggerScrapeNow: vi.fn(),
}))

const getSourcesStatusMock = vi.mocked(catalogApi.getSourcesStatus)
const triggerScrapeNowMock = vi.mocked(catalogApi.triggerScrapeNow)

function wrap(sc: SourceConnectionSummary): SourcesStatusResponse {
  return { data_planes: [{ id: 'dp-1', name: 'customer-prod-vpc', source_connections: [sc] }] }
}

const okConnection: SourceConnectionSummary = {
  id: 'sc-prod-postgres-1',
  name: 'prod-postgres-1',
  type: 'postgres',
  data_plane_id: 'dp-1',
  data_plane_name: 'customer-prod-vpc',
  status: 'ok',
  asset_count: 2,
  tombstoned_count: 1,
  scrape_interval_seconds: 6 * 3600,
  last_scrape_at: new Date().toISOString(),
  last_scrape_status: 'success',
  last_attempt_at: new Date().toISOString(),
  consecutive_failure_count: 0,
  error_summary: null,
  scrape_runs: [
    { id: 'run-1', source_connection_id: 'sc-prod-postgres-1', started_at: new Date().toISOString(), completed_at: new Date().toISOString(), status: 'success', entities_seen_count: 2, entities_created_count: 0, entities_tombstoned_count: 0, error_summary: null },
  ],
  tombstoned_entities: [{ urn: 'urn:postgres:x', name: 'legacy_customers_bak', entity_type: 'table', last_scraped_at: new Date().toISOString() }],
}

function renderDetail(id: string) {
  return renderAtRoute(<SourceConnectionDetailPage />, '/sources/:id', `/sources/${id}`)
}

describe('SourceConnectionDetailPage', () => {
  beforeEach(() => {
    getSourcesStatusMock.mockReset()
    triggerScrapeNowMock.mockReset()
  })

  it('renders header, scrape interval, assets line, and scrape run history', async () => {
    getSourcesStatusMock.mockResolvedValue(wrap(okConnection))
    renderDetail('sc-prod-postgres-1')

    await waitFor(() => expect(screen.getByRole('heading', { name: 'prod-postgres-1' })).toBeInTheDocument())
    expect(screen.getByText('Scrape interval: every 6h (configured)')).toBeInTheDocument()
    expect(screen.getByText(/Assets: 2 tables \(1 tombstoned\)/)).toBeInTheDocument()
    expect(screen.getByText('Scrape run history')).toBeInTheDocument()
  })

  it('toggling "Show tombstoned" reveals the tombstoned entity list', async () => {
    const user = userEvent.setup()
    getSourcesStatusMock.mockResolvedValue(wrap(okConnection))
    renderDetail('sc-prod-postgres-1')

    await waitFor(() => expect(screen.getByRole('heading', { name: 'prod-postgres-1' })).toBeInTheDocument())
    expect(screen.queryByText('legacy_customers_bak')).not.toBeInTheDocument()

    await user.click(screen.getByLabelText('Show tombstoned'))
    expect(screen.getByText('legacy_customers_bak')).toBeInTheDocument()
  })

  it('calls triggerScrapeNow and shows a queued confirmation, documenting the not-yet-existing endpoint', async () => {
    const user = userEvent.setup()
    getSourcesStatusMock.mockResolvedValue(wrap(okConnection))
    triggerScrapeNowMock.mockResolvedValue({ queued: true, source_connection_id: 'sc-prod-postgres-1' })
    renderDetail('sc-prod-postgres-1')

    await waitFor(() => expect(screen.getByRole('heading', { name: 'prod-postgres-1' })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Scrape now' }))

    expect(triggerScrapeNowMock).toHaveBeenCalledWith('sc-prod-postgres-1')
    await waitFor(() => expect(screen.getByText(/Scrape queued/)).toBeInTheDocument())
  })

  it('shows a graceful message when the scrape-now endpoint does not exist yet (404)', async () => {
    const user = userEvent.setup()
    getSourcesStatusMock.mockResolvedValue(wrap(okConnection))
    triggerScrapeNowMock.mockRejectedValue(new ApiError('not found', 404))
    renderDetail('sc-prod-postgres-1')

    await waitFor(() => expect(screen.getByRole('heading', { name: 'prod-postgres-1' })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Scrape now' }))

    await waitFor(() => expect(screen.getByText(/isn't available from this control plane yet/)).toBeInTheDocument())
  })

  it('surfaces error_summary prominently for a failed connection', async () => {
    getSourcesStatusMock.mockResolvedValue(
      wrap({ ...okConnection, status: 'failed', error_summary: 'connection refused to source DB' }),
    )
    renderDetail('sc-prod-postgres-1')

    await waitFor(() => expect(screen.getByText('connection refused to source DB')).toBeInTheDocument())
  })

  it('shows the never-scraped state prominently', async () => {
    getSourcesStatusMock.mockResolvedValue(
      wrap({ ...okConnection, status: 'never', last_scrape_at: null, scrape_runs: [] }),
    )
    renderDetail('sc-prod-postgres-1')

    await waitFor(() => expect(screen.getByText("This connection hasn't completed a scrape yet.")).toBeInTheDocument())
  })
})
