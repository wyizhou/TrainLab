import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests/fullstack',
  timeout: 30_000,
  fullyParallel: false,
  reporter: 'list',
  use: {
    baseURL: process.env.TRAINLAB_FULLSTACK_URL ?? 'http://localhost:8000',
    ...devices['Desktop Chrome'],
    viewport: { width: 1280, height: 800 },
  },
})
