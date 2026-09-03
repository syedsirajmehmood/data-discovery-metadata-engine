import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { FreshnessBadge } from './FreshnessBadge'
import type { FreshnessContext } from '../types/catalog'

describe('FreshnessBadge', () => {
  it('renders the fresh state', () => {
    const freshness: FreshnessContext = {
      stale_threshold_seconds: 12 * 3600,
      latest_scrape_run_status: 'success',
      last_successful_scrape_at: new Date().toISOString(),
      has_any_scrape_run: true,
    }
    render(<FreshnessBadge lastScrapedAt={new Date().toISOString()} freshness={freshness} />)
    expect(screen.getByText(/fresh/)).toBeInTheDocument()
  })

  it('renders scrape issue with hover detail text per AC-5', () => {
    const lastScrapedAt = new Date().toISOString()
    const freshness: FreshnessContext = {
      stale_threshold_seconds: 12 * 3600,
      latest_scrape_run_status: 'failed',
      last_successful_scrape_at: lastScrapedAt,
      has_any_scrape_run: true,
    }
    render(<FreshnessBadge lastScrapedAt={lastScrapedAt} freshness={freshness} />)
    const badge = screen.getByText(/scrape issue/)
    expect(badge).toBeInTheDocument()
    expect(badge).toHaveAttribute('title', expect.stringContaining('most recent attempt failed'))
  })

  it('renders never scraped when there is no scrape run', () => {
    const freshness: FreshnessContext = {
      stale_threshold_seconds: 12 * 3600,
      latest_scrape_run_status: null,
      last_successful_scrape_at: null,
      has_any_scrape_run: false,
    }
    render(<FreshnessBadge lastScrapedAt={null} freshness={freshness} />)
    expect(screen.getByText(/never scraped/)).toBeInTheDocument()
  })
})
