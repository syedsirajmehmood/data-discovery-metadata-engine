import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getSourcesStatus, triggerScrapeNow } from '../api/catalog'
import type { ScrapeRun, SourceConnectionSummary } from '../types/catalog'
import { StatusDot } from '../components/sources/StatusDot'
import { ErrorBanner } from '../components/ErrorBanner'
import { formatClockTime, formatRelativeTime } from '../lib/format'

type Status = 'loading' | 'success' | 'error'
type ScrapeNowState = 'idle' | 'sending' | 'queued' | 'error'

const RUN_STATUS_ICON: Record<ScrapeRun['status'], string> = {
  success: '✓',
  partial_failure: '⚠',
  failed: '✗',
  running: '…',
}

/**
 * Source Connection Detail (design.md §4.2). `[Scrape now]` calls
 * POST /v1/catalog/sources/{id}/scrape — this endpoint is NOT part of
 * architecture.md's documented catalog read API and does not exist on
 * the backend yet (see src/api/catalog.ts triggerScrapeNow doc comment
 * and README "API assumptions"). The call is made anyway per this
 * screen's requirement; a 404/501 is surfaced as "not available yet"
 * rather than a generic failure, so the button is honest about backend
 * readiness without crashing.
 */
export function SourceConnectionDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [status, setStatus] = useState<Status>('loading')
  const [connection, setConnection] = useState<SourceConnectionSummary | null>(null)
  const [showTombstoned, setShowTombstoned] = useState(false)
  const [scrapeNow, setScrapeNow] = useState<ScrapeNowState>('idle')

  function load() {
    if (!id) return
    setStatus('loading')
    getSourcesStatus(id)
      .then((res) => {
        const found = res.data_planes.flatMap((dp) => dp.source_connections).find((sc) => sc.id === id)
        if (!found) {
          setStatus('error')
          return
        }
        setConnection(found)
        setStatus('success')
      })
      .catch(() => setStatus('error'))
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [id])

  async function handleScrapeNow() {
    if (!id) return
    setScrapeNow('sending')
    try {
      await triggerScrapeNow(id)
      setScrapeNow('queued')
    } catch {
      // 404/501 (endpoint not yet built) and any other failure both render
      // as "not available yet" — see doc comment above.
      setScrapeNow('error')
    }
  }

  if (status === 'loading') {
    return (
      <div className="source-detail-page">
        <div className="skeleton-line skeleton-line--medium" />
        <div className="skeleton-line skeleton-line--long" />
        <div className="skeleton-line skeleton-line--long" />
      </div>
    )
  }

  if (status === 'error' || !connection) {
    return (
      <div className="source-detail-page">
        <ErrorBanner message="Could not load this source connection." onRetry={load} />
      </div>
    )
  }

  const assetNoun = connection.type === 'postgres' ? 'tables' : 'datasets'
  const intervalHours = Math.round(connection.scrape_interval_seconds / 3600)
  const staleThresholdHours = intervalHours * 2

  return (
    <div className="source-detail-page">
      <header className="source-detail-header">
        <h1>{connection.name}</h1>
        <StatusDot status={connection.status} />
        <button type="button" onClick={handleScrapeNow} disabled={scrapeNow === 'sending'}>
          {scrapeNow === 'sending' ? 'Queuing…' : 'Scrape now'}
        </button>
      </header>
      {scrapeNow === 'queued' && <p className="muted">Scrape queued — the connector will pick it up on its next outbound poll.</p>}
      {scrapeNow === 'error' && <p className="muted">Scrape-now isn&apos;t available from this control plane yet.</p>}

      <p>
        Type: {connection.type} · Data plane: {connection.data_plane_name}
      </p>
      <p>Scrape interval: every {intervalHours}h (configured)</p>
      <p className="source-detail-assets">
        Assets: {connection.asset_count} {assetNoun} ({connection.tombstoned_count} tombstoned)
        <label className="tombstoned-toggle">
          <input type="checkbox" checked={showTombstoned} onChange={(e) => setShowTombstoned(e.target.checked)} />
          Show tombstoned
        </label>
      </p>

      {showTombstoned && (
        <div className="tombstoned-list">
          {connection.tombstoned_entities && connection.tombstoned_entities.length > 0 ? (
            <ul>
              {connection.tombstoned_entities.map((t) => (
                <li key={t.urn}>
                  <Link to={`/asset/${encodeURIComponent(t.urn)}`}>{t.name}</Link>
                  {t.last_scraped_at && <span className="muted"> — last seen {formatRelativeTime(t.last_scraped_at)}</span>}
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">No tombstoned entities for this connection.</p>
          )}
        </div>
      )}

      {connection.status === 'stale' && (
        <div className="warning-banner" role="status">
          No successful scrape in over {staleThresholdHours}h — expected every {intervalHours}h. The connector may
          be down, or network egress may be blocked. Troubleshooting is customer-side: the control plane cannot
          reach into your data-plane environment to fix it.
        </div>
      )}
      {connection.status === 'failed' && connection.error_summary && (
        <div className="error-banner" role="alert">
          {connection.error_summary}
        </div>
      )}
      {connection.status === 'never' && (
        <div className="warning-banner" role="status">
          This connection hasn&apos;t completed a scrape yet.
        </div>
      )}

      <section>
        <h2>Scrape run history</h2>
        {connection.scrape_runs && connection.scrape_runs.length > 0 ? (
          <ul className="scrape-run-list">
            {connection.scrape_runs.map((run) => (
              <li key={run.id}>
                <span>{RUN_STATUS_ICON[run.status]}</span>{' '}
                <span>{run.completed_at ? formatClockTime(run.completed_at) : formatClockTime(run.started_at)}</span>{' '}
                <span>{run.status}</span>{' '}
                {run.status === 'failed' || run.status === 'partial_failure' ? (
                  <span className="muted">{run.error_summary}</span>
                ) : (
                  <span className="muted">
                    {run.entities_seen_count} seen · {run.entities_created_count} created ·{' '}
                    {run.entities_tombstoned_count} tombstoned
                  </span>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">No scrape runs yet.</p>
        )}
      </section>

      <p>
        <Link to={`/search?source_connection_id=${encodeURIComponent(connection.id)}`}>
          View assets from this connection →
        </Link>
      </p>
    </div>
  )
}
