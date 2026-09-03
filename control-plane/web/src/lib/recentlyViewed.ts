import type { SearchResultItem } from '../types/catalog'

const STORAGE_KEY = 'catalog.recentlyViewed.v1'
const MAX_ENTRIES = 10

export type RecentlyViewedEntry = Pick<
  SearchResultItem,
  'urn' | 'entity_type' | 'name' | 'fully_qualified_name' | 'source_type' | 'source_connection_name'
> & { viewedAt: string }

function safeParse(raw: string | null): RecentlyViewedEntry[] {
  if (!raw) return []
  try {
    const parsed: unknown = JSON.parse(raw)
    return Array.isArray(parsed) ? (parsed as RecentlyViewedEntry[]) : []
  } catch {
    return []
  }
}

export function getRecentlyViewed(): RecentlyViewedEntry[] {
  if (typeof window === 'undefined') return []
  return safeParse(window.localStorage.getItem(STORAGE_KEY))
}

export function recordRecentlyViewed(entry: Omit<RecentlyViewedEntry, 'viewedAt'>): void {
  if (typeof window === 'undefined') return
  const existing = getRecentlyViewed().filter((e) => e.urn !== entry.urn)
  const next = [{ ...entry, viewedAt: new Date().toISOString() }, ...existing].slice(0, MAX_ENTRIES)
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
}
