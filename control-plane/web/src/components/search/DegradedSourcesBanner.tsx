import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { DegradedSourceConnection } from '../../types/catalog'

/**
 * "One or more source connections degraded/down" banner (design.md §2).
 * Dismissible for the current page view; source health is context, not a
 * gate — results stay visible underneath regardless.
 */
export function DegradedSourcesBanner({ sources }: { sources: DegradedSourceConnection[] }) {
  const [dismissed, setDismissed] = useState(false)
  if (dismissed || sources.length === 0) return null

  return (
    <div className="degraded-banner" role="status">
      <span>
        {sources.length} source connection{sources.length === 1 ? '' : 's'} haven&apos;t completed a scrape
        recently — results from those may be incomplete or stale. <Link to="/sources">View sources</Link>
      </span>
      <button type="button" aria-label="Dismiss" onClick={() => setDismissed(true)}>
        ×
      </button>
    </div>
  )
}
