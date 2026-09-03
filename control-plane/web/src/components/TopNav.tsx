import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams, useLocation } from 'react-router-dom'

/**
 * Persistent top nav (design.md §1.2): Logo/Home, search input, Browse,
 * Sources, ?. Present on every screen. No tenant picker/switcher anywhere
 * (design.md §2 — NFR-2, tenant scoping is server-side only).
 *
 * JUDGMENT CALL: design.md's IA describes "Browse" as a secondary,
 * pre-filtered path down to Data Plane -> Source Connection ->
 * Database/Bucket -> Schema/Prefix -> Asset list, explicitly reusing the
 * Search Results component. That drill-down hierarchy isn't one of the 3
 * screens this task scoped ("Search Results", "Asset Detail", "Source
 * Connection Status"), and design.md itself says it just reuses the
 * Search Results list, pre-filtered. Browse here routes to the same
 * /search screen unfiltered rather than building a separate multi-level
 * drill-down UI — the facet filters already on that screen are the
 * pre-filtering mechanism.
 */
export function TopNav() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const location = useLocation()
  const [query, setQuery] = useState(searchParams.get('q') ?? '')

  useEffect(() => {
    if (location.pathname === '/search') {
      setQuery(searchParams.get('q') ?? '')
    }
  }, [location.pathname, searchParams])

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const next = new URLSearchParams()
    if (query) next.set('q', query)
    navigate(`/search?${next.toString()}`)
  }

  return (
    <header className="top-nav">
      <Link to="/search" className="top-nav__logo">
        Catalog
      </Link>
      <form className="top-nav__search" role="search" onSubmit={handleSubmit}>
        <input
          type="search"
          aria-label="Search the catalog"
          placeholder="Search tables, datasets, columns, tags…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </form>
      <nav className="top-nav__links">
        <Link to="/search">Browse</Link>
        <Link to="/sources">Sources</Link>
        <button type="button" className="top-nav__help" title="Search matches entity name, column name, tags, or description.">
          ?
        </button>
      </nav>
    </header>
  )
}
