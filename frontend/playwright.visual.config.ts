import { defineConfig } from '@playwright/test'
import baseConfig from './playwright.config'

export default defineConfig(baseConfig, {
  testMatch: 'visual-baseline.spec.ts',
  workers: 1,
})
