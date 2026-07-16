import { defineConfig } from '@playwright/test'
import baseConfig from './playwright.config'

export default defineConfig(baseConfig, {
  // The exact geometry contract was captured on macOS and depends on native
  // font metrics. Cross-platform functional and screenshot coverage stays on
  // Linux; the geometry contract runs in the dedicated macOS visual job.
  testIgnore: 'visual-baseline.spec.ts',
})
