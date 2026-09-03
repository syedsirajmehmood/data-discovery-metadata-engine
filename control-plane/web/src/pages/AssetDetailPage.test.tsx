import { screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { renderAtRoute } from '../test/renderWithRouter'
import { AssetDetailPage } from './AssetDetailPage'
import * as catalogApi from '../api/catalog'
import { ApiError } from '../api/client'
import type { DatasetEntity, TableEntity } from '../types/catalog'

vi.mock('../api/catalog', () => ({
  getAsset: vi.fn(),
}))

const getAssetMock = vi.mocked(catalogApi.getAsset)

const freshness = {
  stale_threshold_seconds: 12 * 3600,
  latest_scrape_run_status: 'success' as const,
  last_successful_scrape_at: new Date().toISOString(),
  has_any_scrape_run: true,
}

const tableFixture: TableEntity = {
  id: 'ent-1',
  urn: 'urn:postgres:prod-db-1:analytics:public.customers',
  entity_type: 'table',
  source_type: 'postgres',
  data_plane_id: 'dp-1',
  data_plane_name: 'customer-prod-vpc',
  source_connection_id: 'sc-1',
  source_connection_name: 'prod-postgres-1',
  first_seen_at: new Date().toISOString(),
  last_scraped_at: new Date().toISOString(),
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
  source_created_at: null,
  source_last_modified_at: new Date().toISOString(),
  columns: [
    { name: 'id', ordinal_position: 1, native_data_type: 'bigint', normalized_data_type: 'integer', is_nullable: false, is_primary_key: true, is_foreign_key: false, foreign_key_ref: null, description: null, tags: [] },
    { name: 'plan_id', ordinal_position: 2, native_data_type: 'bigint', normalized_data_type: 'integer', is_nullable: true, is_primary_key: false, is_foreign_key: true, foreign_key_ref: 'plans.id', description: null, tags: [] },
  ],
  freshness,
}

const noSchemaDataset: DatasetEntity = {
  id: 'ent-2',
  urn: 'urn:s3:raw-events/customers_snapshot',
  entity_type: 'dataset',
  source_type: 's3',
  data_plane_id: 'dp-1',
  data_plane_name: 'customer-prod-vpc',
  source_connection_id: 'sc-2',
  source_connection_name: 'raw-events-s3',
  first_seen_at: new Date().toISOString(),
  last_scraped_at: new Date().toISOString(),
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
  sample_key_prefixes: ['customers_snapshot/2026-08-30/'],
  freshness,
}

function renderAsset(urn: string) {
  return renderAtRoute(<AssetDetailPage />, '/asset/:urn', `/asset/${encodeURIComponent(urn)}`)
}

describe('AssetDetailPage', () => {
  beforeEach(() => {
    getAssetMock.mockReset()
  })

  it('renders the Table layout with columns, PK/FK flags, and provenance', async () => {
    getAssetMock.mockResolvedValue(tableFixture)
    renderAsset(tableFixture.urn)

    await waitFor(() => expect(screen.getByRole('heading', { name: 'customers' })).toBeInTheDocument())
    expect(screen.getByText(/description from: source comment/)).toBeInTheDocument()
    expect(screen.getByText('PK')).toBeInTheDocument()
    expect(screen.getByText('FK→plans.id')).toBeInTheDocument()
    expect(screen.getByText(/jane@co/)).toBeInTheDocument()
    expect(screen.getByText(/Rows: ~1.2M \(estimate\)/)).toBeInTheDocument()
  })

  it('renders the AC-2a "schema not inferred" state, not an empty column table', async () => {
    getAssetMock.mockResolvedValue(noSchemaDataset)
    renderAsset(noSchemaDataset.urn)

    await waitFor(() => expect(screen.getByText('No schema could be inferred for this dataset.')).toBeInTheDocument())
    expect(screen.getByText('Sample key prefixes:')).toBeInTheDocument()
    expect(screen.getByText('no owner set')).toBeInTheDocument()
    expect(screen.getByText('No description')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('renders the not-found state for a tombstoned entity', async () => {
    getAssetMock.mockResolvedValue({ ...tableFixture, is_deleted: true })
    renderAsset(tableFixture.urn)

    await waitFor(() => expect(screen.getByText(/no longer reported by its source connection/)).toBeInTheDocument())
  })

  it('renders the not-found state for a 404', async () => {
    getAssetMock.mockRejectedValue(new ApiError('not found', 404))
    renderAsset('urn:postgres:missing')

    await waitFor(() => expect(screen.getByText(/no longer reported by its source connection/)).toBeInTheDocument())
  })

  it('renders a fetch-error banner with retry for a non-404 failure', async () => {
    getAssetMock.mockRejectedValue(new ApiError('boom', 500))
    renderAsset('urn:postgres:whatever')

    await waitFor(() => expect(screen.getByText('Could not load this asset.')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })

  it('shows the stale banner and "Check source status" link when freshness is stale', async () => {
    getAssetMock.mockResolvedValue({
      ...tableFixture,
      last_scraped_at: new Date(Date.now() - 9 * 24 * 3600 * 1000).toISOString(),
    })
    renderAsset(tableFixture.urn)

    await waitFor(() => expect(screen.getByText(/Metadata may be out of date/)).toBeInTheDocument())
    expect(screen.getByRole('link', { name: 'Check source status' })).toHaveAttribute('href', '/sources/sc-1')
  })
})
