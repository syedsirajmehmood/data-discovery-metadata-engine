/** Skeleton rows for the search-loading state (design.md §2 — skeleton, not spinner, so layout doesn't jump). */
export function SearchResultsSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <ul className="result-list" aria-busy="true" aria-label="Loading results">
      {Array.from({ length: rows }).map((_, i) => (
        <li key={i} className="result-row result-row--skeleton">
          <div className="skeleton-line skeleton-line--short" />
          <div className="skeleton-line skeleton-line--medium" />
          <div className="skeleton-line skeleton-line--long" />
          <div className="skeleton-line skeleton-line--short" />
        </li>
      ))}
    </ul>
  )
}
