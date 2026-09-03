/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL for the control-plane catalog read API. Empty = relative paths. Never hardcode a host in source. */
  readonly VITE_API_BASE_URL?: string
  /** "false" disables the dev-mode fetch mock (src/api/mocks/mockFetch.ts). Default: mocks on. */
  readonly VITE_USE_MOCKS?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
