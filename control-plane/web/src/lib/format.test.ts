import { describe, expect, it } from 'vitest'
import { formatBytesEstimate, formatClockTime, formatCountEstimate, formatRelativeTime } from './format'

describe('formatRelativeTime', () => {
  const now = new Date('2026-09-02T12:00:00Z')

  it('formats minutes', () => {
    expect(formatRelativeTime(new Date(now.getTime() - 20 * 60 * 1000).toISOString(), now)).toBe('20 min ago')
  })

  it('formats hours', () => {
    expect(formatRelativeTime(new Date(now.getTime() - 2 * 3600 * 1000).toISOString(), now)).toBe('2h ago')
  })

  it('formats days', () => {
    expect(formatRelativeTime(new Date(now.getTime() - 9 * 24 * 3600 * 1000).toISOString(), now)).toBe('9d ago')
  })

  it('formats just now for sub-minute', () => {
    expect(formatRelativeTime(new Date(now.getTime() - 5000).toISOString(), now)).toBe('just now')
  })
})

describe('formatClockTime', () => {
  it('formats HH:MM', () => {
    const d = new Date('2026-09-02T09:11:00')
    expect(formatClockTime(d.toISOString())).toBe('09:11')
  })
})

describe('formatCountEstimate', () => {
  it('formats sub-thousand as-is', () => {
    expect(formatCountEstimate(12)).toBe('~12')
  })
  it('formats millions', () => {
    expect(formatCountEstimate(1_200_000)).toBe('~1.2M')
  })
  it('formats null as unknown', () => {
    expect(formatCountEstimate(null)).toBe('unknown')
  })
})

describe('formatBytesEstimate', () => {
  it('formats MB', () => {
    expect(formatBytesEstimate(340 * 1024 * 1024)).toBe('~340 MB')
  })
  it('formats GB', () => {
    expect(formatBytesEstimate(Math.round(18.4 * 1024 * 1024 * 1024))).toBe('~18.4 GB')
  })
})
