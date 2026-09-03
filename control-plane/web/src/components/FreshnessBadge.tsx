import type { FreshnessContext } from '../types/catalog'
import { computeFreshness } from '../lib/freshness'

/**
 * The one shared freshness-badge component (design.md §5) — reused by
 * Search Results, Asset Detail, and Source Connection list/detail. Do not
 * reimplement badge text/threshold logic in a screen; add a prop here
 * instead.
 */
export function FreshnessBadge({
  lastScrapedAt,
  freshness,
}: {
  lastScrapedAt: string | null
  freshness: FreshnessContext
}) {
  const result = computeFreshness(lastScrapedAt, freshness)
  return (
    <span className={`freshness-badge freshness-badge--${result.kind}`} title={result.detail}>
      {result.icon} {result.label}
    </span>
  )
}
