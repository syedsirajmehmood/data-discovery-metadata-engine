import type { ReactElement } from 'react'
import type { SourceType } from '../types/catalog'

/**
 * Source-type icon. Table (postgres) and Dataset (s3) render as visual
 * peers everywhere this is used (design.md §5) — only this glyph and the
 * type badge text differ between them.
 */
export function EntityIcon({ sourceType }: { sourceType: SourceType }): ReactElement {
  const glyph = sourceType === 'postgres' ? '🐘' : '🪣'
  const label = sourceType === 'postgres' ? 'Postgres source' : 'S3 source'
  return (
    <span className="entity-icon" role="img" aria-label={label}>
      {glyph}
    </span>
  )
}

export function EntityTypeBadge({
  entityType,
  fileFormat,
}: {
  entityType: 'table' | 'dataset'
  fileFormat?: string | null
}): ReactElement {
  const text = entityType === 'table' ? 'TABLE' : 'DATASET'
  return (
    <span className={`entity-type-badge entity-type-badge--${entityType}`}>
      {text}
      {entityType === 'dataset' && fileFormat ? <span className="entity-type-badge__format"> · {fileFormat}</span> : null}
    </span>
  )
}
