import { expect, test } from '@playwright/test'

const PROFILES = [
  ['a0', 'run'],
  ['profile-hike', 'hike'],
  ['profile-strength', 'strength'],
  ['profile-lead', 'lead'],
  ['profile-boulder', 'boulder'],
  ['profile-cycling', 'cycling'],
  ['profile-generic', 'generic'],
] as const

const VIEWPORTS = [
  { width: 390, height: 844 },
  { width: 768, height: 1024 },
  { width: 1280, height: 800 },
  { width: 1536, height: 900 },
]

for (const viewport of VIEWPORTS) {
  for (const [id, profile] of PROFILES) {
    test(`${viewport.width}px ${profile} overview visual baseline`, async ({ page }) => {
      await page.setViewportSize(viewport)
      await page.goto(`/activities/${id}`)
      await expect(page.getByTestId('activity-detail')).toHaveAttribute('data-profile', profile)
      await expect(page).toHaveScreenshot(`${viewport.width}-${profile}-overview.png`, {
        fullPage: true,
        animations: 'disabled',
      })
    })
  }
}
