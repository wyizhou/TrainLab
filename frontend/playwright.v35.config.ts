import { defineConfig } from '@playwright/test'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import baseConfig from './playwright.config'

const FRONTEND_ROOT = fileURLToPath(new URL('.', import.meta.url))

export default defineConfig(baseConfig, {
  testMatch: 'data-management-v35-visual.spec.ts',
  testIgnore: [],
  workers: 1,
  snapshotPathTemplate: join(FRONTEND_ROOT, 'tests/visual-baselines/v3.5/screenshots/{arg}{ext}'),
})
