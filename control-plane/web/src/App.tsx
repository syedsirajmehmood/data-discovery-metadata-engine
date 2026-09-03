import { Navigate, Route, Routes } from 'react-router-dom'
import { TopNav } from './components/TopNav'
import { SearchResultsPage } from './pages/SearchResultsPage'
import { AssetDetailPage } from './pages/AssetDetailPage'
import { SourceConnectionListPage } from './pages/SourceConnectionListPage'
import { SourceConnectionDetailPage } from './pages/SourceConnectionDetailPage'

/**
 * Routes for the 3 MVP screens (design.md). No Lineage/Usage routes —
 * explicitly cut from MVP, not stubbed.
 */
export function App() {
  return (
    <div className="app-shell">
      <TopNav />
      <main className="app-main">
        <Routes>
          <Route path="/" element={<Navigate to="/search" replace />} />
          <Route path="/search" element={<SearchResultsPage />} />
          <Route path="/asset/:urn" element={<AssetDetailPage />} />
          <Route path="/sources" element={<SourceConnectionListPage />} />
          <Route path="/sources/:id" element={<SourceConnectionDetailPage />} />
          <Route path="*" element={<Navigate to="/search" replace />} />
        </Routes>
      </main>
    </div>
  )
}
