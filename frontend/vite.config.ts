import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // API_PROXY_TARGET is deliberately not VITE_-prefixed so it never reaches the browser bundle.
  const env = loadEnv(mode, process.cwd(), '')
  const apiProxyTarget = env.API_PROXY_TARGET || 'http://127.0.0.1:8000'

  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: 5173,
      strictPort: true,
      // Development-only proxy. Deployment needs an /api reverse proxy or an explicit API base URL.
      proxy: {
        '/api': { target: apiProxyTarget, changeOrigin: false },
      },
    },
    test: {
      environment: 'jsdom',
      // Playwright journeys (frontend/e2e) run with `npx playwright test`, not Vitest.
      exclude: ['e2e/**', 'node_modules/**', 'dist/**'],
      setupFiles: ['./src/test/setup.ts'],
    },
  }
})
