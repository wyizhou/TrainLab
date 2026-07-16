import { defineConfig } from '@playwright/test'
import baseConfig from './playwright.config'

process.env.TRAINLAB_VISUAL_GEOMETRY = 'relational'

export default defineConfig(baseConfig, {
  // Linux exercises the complete functional, computed-style, typography, and
  // relational geometry contract. The 64 bitmap comparisons run once in the
  // dedicated macOS job instead of being duplicated here.
  grepInvert: /matches the v3\.3 (full-page|interaction) baseline/,
})
