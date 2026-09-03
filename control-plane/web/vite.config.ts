/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
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
})
