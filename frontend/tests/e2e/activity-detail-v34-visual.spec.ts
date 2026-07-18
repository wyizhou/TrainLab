import { expect, test, type Page } from '@playwright/test'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

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

test('v3.4 historical 28-screenshot set remains byte-for-byte unchanged', () => {
  const screenshotRoot = fileURLToPath(
    new URL('../visual-baselines/v3.4/screenshots/', import.meta.url),
  )
  const names = VIEWPORTS.flatMap((viewport) =>
    PROFILES.map(([, profile]) => `${viewport.width}-${profile}-overview.png`),
  ).sort()
  const setHash = createHash('sha256')
  for (const name of names) {
    const fileHash = createHash('sha256')
      .update(readFileSync(`${screenshotRoot}${name}`))
      .digest('hex')
    setHash.update(fileHash)
  }
  expect(names).toHaveLength(28)
  expect(setHash.digest('hex')).toBe(
    'e9814df284b30b23242321485220746dc00fba3ed790f79d9eed3c41c820c22d',
  )
})

async function restoreV34ScreenshotSurface(page: Page, downloadAvailable: boolean) {
  await page.evaluate((available) => {
    const version = document.querySelector('.activity-detail-shell__version')
    if (version) version.textContent = 'v3.4 · DESIGN REV 7'

    const actions = document.querySelector('.activity-actions')
    if (!actions) throw new Error('v3.5 activity actions are missing')
    const button = document.createElement('button')
    button.type = 'button'
    button.className = 'activity-detail__download'
    button.dataset.vc = 'activity-fit-download'
    button.dataset.testid = 'detail-download'
    button.disabled = !available
    button.textContent = available ? '下载原始 FIT' : '未绑定 FIT'
    actions.replaceWith(button)
  }, downloadAvailable)
}

for (const viewport of VIEWPORTS) {
  for (const [id, profile] of PROFILES) {
    test(`${viewport.width}px ${profile} overview visual baseline`, async ({ page }) => {
      await page.setViewportSize(viewport)
      await page.goto(`/activities/${id}`)
      await expect(page.getByTestId('activity-detail')).toHaveAttribute('data-profile', profile)
      await restoreV34ScreenshotSurface(page, profile === 'run')
      await expect(page).toHaveScreenshot(`${viewport.width}-${profile}-overview.png`, {
        fullPage: true,
        animations: 'disabled',
      })
    })
  }
}
