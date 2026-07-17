import { defineConfig, devices } from '@playwright/test'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const PORT = 5173
const BASE_URL = `http://localhost:${PORT}`
const FRONTEND_ROOT = fileURLToPath(new URL('.', import.meta.url))

export default defineConfig({
  testDir: './tests/e2e',
  testIgnore: 'activity-detail-v34-visual.spec.ts',
  // Named screenshot assertions use checked-in implementation-regression
  // assets. External prototypes remain read-only inputs outside the repository.
  snapshotPathTemplate: join(FRONTEND_ROOT, 'tests/visual-baselines/v3.3/screenshots/{arg}{ext}'),
  timeout: 30_000,
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  reporter: 'list',
  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 } },
    },
  ],
  webServer: {
    command: `VITE_AUTH_MODE=demo npm run dev -- --port ${PORT} --strictPort`,
    cwd: FRONTEND_ROOT,
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
