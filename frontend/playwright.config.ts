import { defineConfig, devices } from '@playwright/test'

/**
 * Focused browser acceptance journeys (guide 07 §6.4) against an isolated stack:
 * API on :8100 over the disposable `cognuance_test_e2e` database (provisioned by
 * `tests.e2e.serve_api`), production build served by `vite preview` on :4180.
 * Evidence is minimal: no traces/videos (they could capture credentials or tokens); failure
 * screenshots only, kept in test-results/ until inspected (delete after review).
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1, // one shared, stateful E2E database
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  reporter: [['list'], ['json', { outputFile: 'test-results/e2e-results.json' }]],
  use: {
    baseURL: 'http://127.0.0.1:4180',
    trace: 'off',
    video: 'off',
    screenshot: 'only-on-failure',
    colorScheme: 'light',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } }],
  webServer: [
    {
      command: 'uv run --extra ml python -m tests.e2e.serve_api',
      cwd: '../backend',
      url: 'http://127.0.0.1:8100/api/v1/ready',
      timeout: 240_000,
      reuseExistingServer: !process.env.CI,
    },
    {
      command: 'npm run build && npx vite preview --host 127.0.0.1 --port 4180 --strictPort',
      url: 'http://127.0.0.1:4180',
      env: { API_PROXY_TARGET: 'http://127.0.0.1:8100' },
      timeout: 180_000,
      reuseExistingServer: !process.env.CI,
    },
  ],
})
