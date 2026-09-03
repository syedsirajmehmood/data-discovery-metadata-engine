import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './styles/app.css'
import { App } from './App'

// FE2's real backend (control-plane/api/catalog/) does not exist in this
// worktree yet. Default to a mock fetch layer so `npm run dev` is usable
// standalone; set VITE_USE_MOCKS=false once a real API is reachable (and
// point VITE_API_BASE_URL at it — see src/api/client.ts).
if (import.meta.env.VITE_USE_MOCKS !== 'false') {
  const { installMockFetch } = await import('./api/mocks/mockFetch')
  installMockFetch()
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
)
