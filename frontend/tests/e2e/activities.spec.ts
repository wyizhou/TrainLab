import { test, expect } from '@playwright/test'

// Baseline viewports (contract G-resp): mobile 390 / desktop 1280.
const MOBILE = { width: 390, height: 844 }
const DESKTOP = { width: 1280, height: 800 }

// C-7 e2e (gate): type filter + paging + batch checkbox count.
test('filters by type, pages through the list, and counts batch selections', async ({ page }) => {
  await page.goto('/activities')
  await expect(page.getByTestId('page-activities')).toBeVisible()

  // Default page shows 20 rows and starts on page 1.
  await expect(page.getByTestId('activity-row')).toHaveCount(20)
  await expect(page.getByTestId('pager-page')).toContainText('1 /')

  // Type filter narrows the list in real time (力量 is a strict subset).
  const totalAll = await page.getByTestId('pager-info').textContent()
  await page.getByRole('button', { name: '力量', exact: true }).click()
  await expect(page.getByRole('button', { name: '力量', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  const totalStrength = await page.getByTestId('pager-info').textContent()
  expect(totalStrength).not.toBe(totalAll)
  await expect(page.getByTestId('pager-page')).toContainText('1 /')

  // Back to 全部, then page forward.
  await page.getByRole('button', { name: '全部', exact: true }).click()
  await page.getByRole('button', { name: '下一页 →' }).click()
  await expect(page.getByTestId('pager-page')).toContainText('2 /')
  await expect(page.getByTestId('activity-row')).toHaveCount(20)

  // Batch counter tracks checkbox selections.
  const batch = page.getByTestId('batch-download')
  await expect(batch).toContainText('下载选中 FIT (0)')
  await expect(batch).toBeDisabled()

  const checks = page.getByTestId('activity-row').getByRole('checkbox')
  await checks.nth(0).check()
  await checks.nth(1).check()
  await expect(batch).toContainText('下载选中 FIT (2)')
  await expect(batch).toBeEnabled()

  // Selection persists across a page change (state lives above the table).
  await page.getByRole('button', { name: '← 上一页' }).click()
  await expect(batch).toContainText('下载选中 FIT (2)')
})

// AC-007b-1 (C-7): mobile mounts the card list instead of the min-width:960px
// table; desktop mounts the table instead of the card list. Neither viewport
// overflows horizontally (the table's in-panel scroll must not escape the page).
test('mobile shows the activity card list; desktop shows the table', async ({ page }) => {
  await page.setViewportSize(MOBILE)
  await page.goto('/activities')
  await expect(page.getByTestId('page-activities')).toBeVisible()

  // Mobile: only the card surface is mounted.
  await expect(page.getByTestId('activity-table')).toHaveCount(0)

  // Card count equals the page slice = min(page size 20, remaining rows).
  await expect(page.getByTestId('activity-card')).toHaveCount(20)

  // No horizontal page overflow on mobile.
  const mobileOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  )
  expect(mobileOverflow).toBe(false)

  // Desktop: only the table surface is mounted.
  await page.setViewportSize(DESKTOP)
  await expect(page.getByTestId('activity-table')).toBeVisible()
  await expect(page.getByTestId('activity-card-list')).toHaveCount(0)

  // No horizontal page overflow on desktop (table scrolls inside its panel).
  const desktopOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  )
  expect(desktopOverflow).toBe(false)
})
