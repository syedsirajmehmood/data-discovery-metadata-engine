import { Link } from 'react-router-dom'
import type { SearchResultItem } from '../../types/catalog'
import { EntityIcon, EntityTypeBadge } from '../EntityIcon'
import { FreshnessBadge } from '../FreshnessBadge'
import { formatRelativeTime } from '../../lib/format'

/**
 * One search-result row. Table and Dataset rows share this exact shape —
 * same fields, same order, same typography (design.md §2 / US-8) — only
 * the icon, type badge, and location-string format differ.
 */
export function ResultRow({ result }: { result: SearchResultItem }) {
  return (
    <li className="result-row">
      <Link to={`/asset/${encodeURIComponent(result.urn)}`} className="result-row__link">
        <div className="result-row__header">
          <EntityIcon sourceType={result.source_type} />
          <EntityTypeBadge entityType={result.entity_type} fileFormat={result.file_format} />
          <span className="result-row__source-connection">· {result.source_connection_name}</span>
        </div>
        <div className="result-row__location">{result.fully_qualified_name}</div>
        <div className="result-row__description">{result.description || 'No description'}</div>
        <div className="result-row__owner">Owner: {result.owner ? `${result.owner}${result.owner_source ? ` (${result.owner_source})` : ''}` : 'no owner set'}</div>
        <div className="result-row__footer">
          <span className="result-row__scraped">
            {result.last_scraped_at ? `scraped ${formatRelativeTime(result.last_scraped_at)}` : 'never scraped'}
          </span>
          <FreshnessBadge lastScrapedAt={result.last_scraped_at} freshness={result.freshness} />
        </div>
      </Link>
    </li>
  )
}
