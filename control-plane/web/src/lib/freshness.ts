import type { FreshnessContext } from '../types/catalog'
import { formatRelativeTime } from './format'

/**
 * Single shared freshness computation, per design.md §3.3 and §5:
 * "compute it once against last_scraped_at + configured interval + latest
 * Scrape Run status, in one place." Every screen (Search Results, Asset
 * Detail, Source Connection list/detail) must go through this function —
 * do not re-implement the threshold math per screen.
 */
export type FreshnessKind = 'fresh' | 'stale' | 'scrape_issue' | 'never'

export interface FreshnessResult {
  kind: FreshnessKind
  /** Short badge label, e.g. "fresh", "stale, >12h", "scrape issue", "never scraped". */
  label: string
  /** Icon glyph per design.md (✓ / ⚠ / ✗). */
  icon: string
  /** Longer text for hover/detail — required verbatim wording for scrape_issue per AC-5. */
  detail: string
}

export function computeFreshness(
  lastScrapedAt: string | null,
  ctx: FreshnessContext,
  now: Date = new Date(),
): FreshnessResult {
  const thresholdHours = Math.round(ctx.stale_threshold_seconds / 3600)

  if (!ctx.has_any_scrape_run || !lastScrapedAt) {
    return {
      kind: 'never',
      label: 'never scraped',
      icon: '✗',
      detail: 'This entity has no successful scrape on record yet.',
    }
  }

  const attemptFailed =
    ctx.latest_scrape_run_status === 'failed' || ctx.latest_scrape_run_status === 'partial_failure'

  // Per design.md §3.3: if both stale and scrape-issue conditions hold,
  // scrape_issue wins — it's the more specific, more actionable message.
  if (attemptFailed) {
    const lastSuccess = ctx.last_successful_scrape_at
      ? formatRelativeTime(ctx.last_successful_scrape_at, now)
      : 'never'
    const attemptWord = ctx.latest_scrape_run_status === 'failed' ? 'failed' : 'partially failed'
    return {
      kind: 'scrape_issue',
      label: 'scrape issue',
      icon: '⚠',
      detail: `last successful scrape: ${lastSuccess}, most recent attempt ${attemptWord}`,
    }
  }

  const ageMs = now.getTime() - new Date(lastScrapedAt).getTime()
  const isStale = ageMs > ctx.stale_threshold_seconds * 1000

  if (isStale) {
    return {
      kind: 'stale',
      label: `stale, >${thresholdHours}h`,
      icon: '⚠',
      detail: `Last scraped ${formatRelativeTime(lastScrapedAt, now)}, which is past the ${thresholdHours}h stale threshold for this source connection.`,
    }
  }

  return {
    kind: 'fresh',
    label: 'fresh',
    icon: '✓',
    detail: `Last scraped ${formatRelativeTime(lastScrapedAt, now)}.`,
  }
}
