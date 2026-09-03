import type { SourceConnectionStatus } from '../../types/catalog'

const STATUS_META: Record<SourceConnectionStatus, { dot: string; label: string }> = {
  ok: { dot: '🟢', label: 'OK' },
  stale: { dot: '🟡', label: 'STALE' },
  failed: { dot: '🔴', label: 'FAIL' },
  never: { dot: '⚪', label: 'NEW' },
}

export function StatusDot({ status }: { status: SourceConnectionStatus }) {
  const meta = STATUS_META[status]
  return (
    <span className={`status-dot status-dot--${status}`}>
      {meta.dot} {meta.label}
    </span>
  )
}
