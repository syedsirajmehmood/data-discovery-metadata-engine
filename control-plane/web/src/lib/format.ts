/** Formats an ISO timestamp as "20 min ago" / "9d ago" style relative text. */
export function formatRelativeTime(iso: string, now: Date = new Date()): string {
  const then = new Date(iso).getTime()
  const diffMs = now.getTime() - then
  if (Number.isNaN(then)) return 'unknown'
  if (diffMs < 0) return 'just now'

  const sec = Math.round(diffMs / 1000)
  if (sec < 60) return 'just now'
  const min = Math.round(sec / 60)
  if (min < 60) return `${min} min ago`
  const hr = Math.round(min / 60)
  if (hr < 24) return `${hr}h ago`
  const day = Math.round(hr / 24)
  if (day < 30) return `${day}d ago`
  const month = Math.round(day / 30)
  if (month < 12) return `${month}mo ago`
  const year = Math.round(month / 12)
  return `${year}y ago`
}

/** Formats a HH:MM 24h clock string from an ISO timestamp, for "attempt 09:11" style display. */
export function formatClockTime(iso: string): string {
  const d = new Date(iso)
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${hh}:${mm}`
}

/** "~1.2M" style estimate formatting for row/object counts. Always caller-labeled "(estimate)". */
export function formatCountEstimate(n: number | null): string {
  if (n === null) return 'unknown'
  if (n < 1000) return `~${n}`
  if (n < 1_000_000) return `~${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}K`
  if (n < 1_000_000_000) return `~${(n / 1_000_000).toFixed(1)}M`
  return `~${(n / 1_000_000_000).toFixed(1)}B`
}

/** "~340 MB" / "~18.4 GB" style estimate formatting for byte sizes — one decimal, trimmed when it's a whole number. */
export function formatBytesEstimate(bytes: number | null): string {
  if (bytes === null) return 'unknown'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = bytes
  let unitIndex = 0
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024
    unitIndex += 1
  }
  if (unitIndex === 0) return `~${Math.round(value)} B`
  const rounded = Math.round(value * 10) / 10
  const text = Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1)
  return `~${text} ${units[unitIndex]}`
}
