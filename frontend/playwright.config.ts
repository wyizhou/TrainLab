import { defineConfig, devices } from '@playwright/test'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const PORT = 5173
const BASE_URL = `http://localhost:${PORT}`
const FRONTEND_ROOT = fileURLToPath(new URL('.', import.meta.url))
const REPOSITORY_ROOT = fileURLToPath(new URL('..', import.meta.url))

export default defineConfig({
  testDir: './tests/e2e',
  // v3.2 screenshots are the checked-in visual source of truth. Named
  // toHaveScreenshot assertions resolve directly to that handoff directory.
  snapshotPathTemplate: join(REPOSITORY_ROOT, 'design/v3.2/交接/基线截图/{arg}{ext}'),
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
    command: `npm run dev -- --port ${PORT} --strictPort`,
    cwd: FRONTEND_ROOT,
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
