/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  // Local-dev-only proxy: the app (src/api/client.ts) never attaches an
  // Authorization header — there's no login flow in MVP scope (design.md).
  // FE2's real catalog API requires one on every request (api/catalog/deps.py).
  // Rather than adding a fake auth flow to the app itself, the dev server
  // injects a fixed local API key when proxying to a real backend — set via
  // VITE_LOCAL_PROXY_TARGET / VITE_LOCAL_API_KEY (see RUNBOOK.md). Leave
  // both unset for the normal mock-fetch dev flow (npm run dev with no env).
  const proxyTarget = env.VITE_LOCAL_PROXY_TARGET
  const localApiKey = env.VITE_LOCAL_API_KEY

  return {
    plugins: [react()],
    server: proxyTarget
      ? {
          proxy: {
            '/v1': {
              target: proxyTarget,
              changeOrigin: true,
              configure: (proxy) => {
                proxy.on('proxyReq', (proxyReq) => {
                  if (localApiKey) {
                    proxyReq.setHeader('Authorization', `Bearer ${localApiKey}`)
                  }
                })
              },
            },
          },
        }
      : undefined,
    test: {
      environment: 'jsdom',
      environmentOptions: {
        jsdom: {
          // localStorage throws for jsdom's default opaque "about:blank" origin
          // (used by recentlyViewed.ts) — give tests a real origin.
          url: 'http://localhost:3000',
        },
      },
      globals: true,
      setupFiles: ['./src/test/setup.ts'],
      css: true,
    },
  }
})
