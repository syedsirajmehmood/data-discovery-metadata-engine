import { describe, expect, it } from 'vitest'
import { computeFreshness } from './freshness'
import type { FreshnessContext } from '../types/catalog'

const NOW = new Date('2026-09-02T12:00:00Z')
const SIX_HOUR_INTERVAL = 6 * 3600
const THRESHOLD = SIX_HOUR_INTERVAL * 2 // 12h, design.md §3.3

function ctx(overrides: Partial<FreshnessContext>): FreshnessContext {
  return {
    stale_threshold_seconds: THRESHOLD,
    latest_scrape_run_status: 'success',
    last_successful_scrape_at: null,
    has_any_scrape_run: true,
    ...overrides,
  }
}

describe('computeFreshness', () => {
  it('is fresh when last_scraped_at is within the threshold and the latest run succeeded', () => {
    const lastScrapedAt = new Date(NOW.getTime() - 20 * 60 * 1000).toISOString() // 20 min ago
    const result = computeFreshness(lastScrapedAt, ctx({ latest_scrape_run_status: 'success' }), NOW)
    expect(result.kind).toBe('fresh')
  })

  it('is stale when last_scraped_at is past the 2x-interval threshold', () => {
    const lastScrapedAt = new Date(NOW.getTime() - 9 * 24 * 3600 * 1000).toISOString() // 9 days ago
    const result = computeFreshness(lastScrapedAt, ctx({ latest_scrape_run_status: 'success' }), NOW)
    expect(result.kind).toBe('stale')
    expect(result.label).toContain('>12h')
  })

  it('is exactly at the threshold boundary: not yet stale', () => {
    const lastScrapedAt = new Date(NOW.getTime() - THRESHOLD * 1000 + 1000).toISOString() // 1s inside threshold
    const result = computeFreshness(lastScrapedAt, ctx({ latest_scrape_run_status: 'success' }), NOW)
    expect(result.kind).toBe('fresh')
  })

  it('is scrape_issue when the latest attempt failed, even if last_scraped_at is still within the fresh window', () => {
    const lastScrapedAt = new Date(NOW.getTime() - 20 * 60 * 1000).toISOString() // fresh by age
    const result = computeFreshness(
      lastScrapedAt,
      ctx({ latest_scrape_run_status: 'failed', last_successful_scrape_at: lastScrapedAt }),
      NOW,
    )
    expect(result.kind).toBe('scrape_issue')
    expect(result.detail).toContain('last successful scrape:')
    expect(result.detail).toContain('most recent attempt failed')
  })

  it('is scrape_issue (not merely stale) when both stale and failed conditions hold — AC-5 precedence', () => {
    const lastScrapedAt = new Date(NOW.getTime() - 9 * 24 * 3600 * 1000).toISOString() // stale by age too
    const result = computeFreshness(
      lastScrapedAt,
      ctx({ latest_scrape_run_status: 'failed', last_successful_scrape_at: lastScrapedAt }),
      NOW,
    )
    expect(result.kind).toBe('scrape_issue')
  })

  it('treats partial_failure as a scrape issue with distinct wording', () => {
    const lastScrapedAt = new Date(NOW.getTime() - 20 * 60 * 1000).toISOString()
    const result = computeFreshness(
      lastScrapedAt,
      ctx({ latest_scrape_run_status: 'partial_failure', last_successful_scrape_at: lastScrapedAt }),
      NOW,
    )
    expect(result.kind).toBe('scrape_issue')
    expect(result.detail).toContain('partially failed')
  })

  it('is never when there is no successful scrape run on record', () => {
    const result = computeFreshness(null, ctx({ has_any_scrape_run: false }), NOW)
    expect(result.kind).toBe('never')
  })

  it('is never when has_any_scrape_run is true but last_scraped_at is null (defensive)', () => {
    const result = computeFreshness(null, ctx({ has_any_scrape_run: true }), NOW)
    expect(result.kind).toBe('never')
  })

  it('respects a per-source-connection configured interval rather than a hardcoded 12h', () => {
    // 30 min interval -> 1h stale threshold; 90 min ago is stale under this
    // threshold even though it would be "fresh" under the 12h default.
    const lastScrapedAt = new Date(NOW.getTime() - 90 * 60 * 1000).toISOString()
    const result = computeFreshness(
      lastScrapedAt,
      ctx({ stale_threshold_seconds: 3600, latest_scrape_run_status: 'success' }),
      NOW,
    )
    expect(result.kind).toBe('stale')
  })
})
