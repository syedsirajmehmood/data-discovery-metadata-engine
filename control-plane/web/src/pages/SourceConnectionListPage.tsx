import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getSourcesStatus } from '../api/catalog'
import type { SourceConnectionSummary, SourcesStatusResponse } from '../types/catalog'
import { StatusDot } from '../components/sources/StatusDot'
import { ErrorBanner } from '../components/ErrorBanner'
import { formatClockTime, formatRelativeTime } from '../lib/format'

type Status = 'loading' | 'success' | 'error'

const STATUS_SORT_ORDER: Record<SourceConnectionSummary['status'], number> = {
  failed: 0,
  stale: 1,
  never: 2,
  ok: 3,
}

function lastScrapeText(sc: SourceConnectionSummary): string {
  if (sc.last_scrape_at) return formatRelativeTime(sc.last_scrape_at)
  if (sc.last_attempt_at) return `attempt ${formatClockTime(sc.last_attempt_at)}`
  return 'never'
}

/** Source Connection List (design.md §4.1), grouped by Data Plane, worst-status-first within each group. */
export function SourceConnectionListPage() {
  const [status, setStatus] = useState<Status>('loading')
  const [data, setData] = useState<SourcesStatusResponse | null>(null)

  function load() {
    setStatus('loading')
    getSourcesStatus()
      .then((res) => {
        setData(res)
        setStatus('success')
      })
      .catch(() => setStatus('error'))
  }

  useEffect(load, [])

  if (status === 'loading') {
    return (
      <div className="sources-page">
        <h1>Sources</h1>
        <div className="skeleton-line skeleton-line--long" />
        <div className="skeleton-line skeleton-line--long" />
        <div className="skeleton-line skeleton-line--long" />
      </div>
    )
  }

  if (status === 'error' || !data) {
    return (
      <div className="sources-page">
        <h1>Sources</h1>
        <ErrorBanner message="Could not load source connection status." onRetry={load} />
      </div>
    )
  }

  const totalConnections = data.data_planes.reduce((sum, dp) => sum + dp.source_connections.length, 0)

  if (totalConnections === 0) {
    return (
      <div className="sources-page">
        <h1>Sources</h1>
        <div className="empty-state">
          <p>No sources connected yet.</p>
          <p className="muted">Install the data-plane connector in your environment to get started.</p>
          <p>
            <a href="#setup">Setup instructions →</a>
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="sources-page">
      <h1>Sources</h1>
      {data.data_planes.map((dp) => {
        const rows = [...dp.source_connections].sort(
          (a, b) => STATUS_SORT_ORDER[a.status] - STATUS_SORT_ORDER[b.status],
        )
        return (
          <section key={dp.id} className="data-plane-group">
            <h2>▾ Data plane: {dp.name}</h2>
            <table className="sources-table">
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Connection</th>
                  <th>Type</th>
                  <th>Assets</th>
                  <th>Last scrape</th>
                  <th>Errors</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((sc) => (
                  <tr key={sc.id}>
                    <td>
                      <StatusDot status={sc.status} />
                    </td>
                    <td>
                      <Link to={`/sources/${sc.id}`}>{sc.name}</Link>
                    </td>
                    <td>{sc.type}</td>
                    <td>{sc.asset_count}</td>
                    <td>{lastScrapeText(sc)}</td>
                    <td>{sc.status === 'never' ? '—' : sc.consecutive_failure_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )
      })}
    </div>
  )
}
