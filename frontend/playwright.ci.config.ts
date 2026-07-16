import { defineConfig } from '@playwright/test'
import baseConfig from './playwright.config'

process.env.TRAINLAB_PORTABLE_FONT_METRICS = '1'

export default defineConfig(baseConfig, {
  // Linux exercises the complete functional, computed-style, typography, and
  // geometry contract. Only an explicit closed list of font-metric-driven
  // vertical fields uses relational checks; all other geometry stays exact.
  // The 64 bitmap comparisons run once in the dedicated macOS job.
  grepInvert: /matches the v3\.3 (full-page|interaction) baseline/,
})
