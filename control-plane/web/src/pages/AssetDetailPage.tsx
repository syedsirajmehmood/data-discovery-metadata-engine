import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getAsset } from '../api/catalog'
import { ApiError } from '../api/client'
import type { AssetEntity } from '../types/catalog'
import { EntityIcon, EntityTypeBadge } from '../components/EntityIcon'
import { ErrorBanner } from '../components/ErrorBanner'
import { FreshnessBadge } from '../components/FreshnessBadge'
import { computeFreshness } from '../lib/freshness'
import { formatBytesEstimate, formatCountEstimate, formatRelativeTime } from '../lib/format'
import { ColumnTable } from '../components/asset/ColumnTable'
import { NoSchemaInferredBlock } from '../components/asset/NoSchemaInferredBlock'
import { recordRecentlyViewed } from '../lib/recentlyViewed'

type Status = 'loading' | 'success' | 'not_found' | 'error'

/** Asset Detail View (design.md §3). One page, no tabs — lineage/usage are cut from MVP. */
export function AssetDetailPage() {
  const { urn: encodedUrn } = useParams<{ urn: string }>()
  const urn = encodedUrn ? decodeURIComponent(encodedUrn) : ''
  const [status, setStatus] = useState<Status>('loading')
  const [asset, setAsset] = useState<AssetEntity | null>(null)

  function load() {
    setStatus('loading')
    getAsset(urn)
      .then((res) => {
        setAsset(res)
        setStatus(res.is_deleted ? 'not_found' : 'success')
        if (!res.is_deleted) {
          recordRecentlyViewed({
            urn: res.urn,
            entity_type: res.entity_type,
            name: res.entity_type === 'table' ? res.table_name : res.prefix.replace(/\/$/, ''),
            fully_qualified_name: res.fully_qualified_name,
            source_type: res.source_type,
            source_connection_name: res.source_connection_name,
          })
        }
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 404) {
          setStatus('not_found')
        } else {
          setStatus('error')
        }
      })
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [urn])

  if (status === 'loading') {
    return (
      <div className="asset-page">
        <div className="skeleton-line skeleton-line--short" />
        <div className="skeleton-line skeleton-line--medium" />
        <div className="skeleton-line skeleton-line--long" />
      </div>
    )
  }

  if (status === 'not_found') {
    return (
      <div className="asset-page">
        <div className="empty-state">
          <p>This asset is no longer reported by its source connection.</p>
          <p className="muted">
            It may have been removed, renamed, or the connector may be misconfigured.{' '}
            {asset ? (
              <Link to={`/sources/${asset.source_connection_id}`}>View source status</Link>
            ) : (
              <Link to="/sources">View source status</Link>
            )}
          </p>
        </div>
      </div>
    )
  }

  if (status === 'error' || !asset) {
    return (
      <div className="asset-page">
        <ErrorBanner message="Could not load this asset." onRetry={load} />
      </div>
    )
  }

  const isTable = asset.entity_type === 'table'
  const name = isTable ? asset.table_name : asset.prefix.replace(/\/$/, '')
  const locationParts = isTable
    ? [asset.source_connection_name, asset.database_name, asset.schema_name]
    : [asset.source_connection_name, asset.bucket, asset.prefix.replace(/\/$/, '')]

  const freshness = computeFreshness(asset.last_scraped_at, asset.freshness)
  const showStaleBanner = freshness.kind === 'stale' || freshness.kind === 'scrape_issue'

  return (
    <div className="asset-page">
      <nav className="breadcrumb" aria-label="Breadcrumb">
        <Link to="/sources">Sources</Link> /{' '}
        <Link to={`/sources/${asset.source_connection_id}`}>{locationParts[0]}</Link> / {locationParts[1]} /{' '}
        {locationParts[2]} / {name}
      </nav>

      <header className="asset-header">
        <div className="asset-header__title">
          <EntityIcon sourceType={asset.source_type} />
          <EntityTypeBadge entityType={asset.entity_type} fileFormat={!isTable ? asset.file_format : undefined} />
          <h1>{name}</h1>
          <FreshnessBadge lastScrapedAt={asset.last_scraped_at} freshness={asset.freshness} />
        </div>

        <CopyableFqn value={asset.fully_qualified_name} />

        <p className="asset-header__description">
          {asset.description ? (
            <>
              {asset.description}
              {asset.description_source && (
                <span className="muted"> (description from: {asset.description_source === 'source_comment' ? 'source comment' : 'manual'})</span>
              )}
            </>
          ) : (
            <span className="muted">No description</span>
          )}
        </p>

        <div className="asset-header__meta">
          <span>
            Owner: {asset.owner ? `${asset.owner}${asset.owner_source ? ` (${asset.owner_source})` : ''}` : <span className="muted">no owner set</span>}
          </span>
          <span>Tags: {asset.tags.length > 0 ? asset.tags.join(', ') : '—'}</span>
        </div>

        {isTable ? (
          <div className="asset-header__stats">
            <span>Rows: {formatCountEstimate(asset.row_count_estimate)} (estimate)</span>
            <span>Size: {formatBytesEstimate(asset.size_bytes_estimate)} (estimate)</span>
          </div>
        ) : asset.schema_inferred ? (
          <div className="asset-header__stats">
            <span>Object count: {formatCountEstimate(asset.object_count_estimate)} (estimate)</span>
            <span>Total size: {formatBytesEstimate(asset.total_size_bytes_estimate)} (estimate)</span>
          </div>
        ) : null}

        <div className="asset-header__freshness-line">
          Last scraped: {asset.last_scraped_at ? formatRelativeTime(asset.last_scraped_at) : 'never'}
          {isTable && asset.source_last_modified_at && (
            <> · Source last modified: {formatRelativeTime(asset.source_last_modified_at)}</>
          )}
        </div>
      </header>

      {showStaleBanner && (
        <div className="stale-banner" role="status">
          Metadata may be out of date — {freshness.detail}. <Link to={`/sources/${asset.source_connection_id}`}>Check source status</Link>
        </div>
      )}

      <section className="asset-content">
        {isTable ? (
          <ColumnTable columns={asset.columns} />
        ) : asset.schema_inferred ? (
          <ColumnTable columns={asset.fields ?? []} />
        ) : (
          <NoSchemaInferredBlock dataset={asset} />
        )}
      </section>
    </div>
  )
}

function CopyableFqn({ value }: { value: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      className="copyable-fqn"
      onClick={() => {
        navigator.clipboard?.writeText(value).catch(() => {})
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
      }}
      title="Copy fully-qualified name"
    >
      {value} {copied ? '(copied)' : ''}
    </button>
  )
}
