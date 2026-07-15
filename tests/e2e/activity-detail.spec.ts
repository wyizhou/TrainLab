import { test, expect, type Page } from '@playwright/test'

// Baseline viewports (contract G-resp): mobile 390 / desktop 1280.
const MOBILE = { width: 390, height: 844 }
const DESKTOP = { width: 1280, height: 800 }

// The real FIT-backed 晨间轻松跑 detail. Contract paths say /activities/1 (the
// first / real-FIT activity); its route id is a0.
const FIT_DETAIL_URL = '/activities/a0'

// Fails the assertion if any downsampled chart's SVG renders wider than the
// .ts-chart container that holds it (AC-008b-2, svg 渲染宽 ≤ 容器宽).
async function expectSvgsFitContainer(page: Page) {
  const overflowing = await page.evaluate(
    () =>
      [...document.querySelectorAll('[data-testid="ts-svg"]')].filter((svg) => {
        const parent = svg.parentElement
        if (!parent) return false
        return svg.getBoundingClientRect().width > parent.getBoundingClientRect().width + 0.5
      }).length,
  )
  expect(overflowing).toBe(0)
}

// C-8 e2e (gate #4): open the real FIT-backed activity and switch between the
// downsampled curve view and the per-second data table.
test('opens the FIT activity detail and toggles curve ⇄ per-second table', async ({ page }) => {
  await page.goto('/activities')
  await expect(page.getByTestId('page-activities')).toBeVisible()

  // The first row is the real FIT-backed 晨间轻松跑; open its detail.
  await page.getByTestId('activity-row').first().click()
  await expect(page).toHaveURL(/\/activities\/a0$/)
  await expect(page.getByTestId('page-activity-detail')).toBeVisible()

  // FIT parses in the browser; the detail (real stored values) then renders.
  await expect(page.getByText('晨间轻松跑')).toBeVisible()
  await expect(page.getByText('total_training_effect')).toBeVisible()
  await expect(page.getByTestId('hr-zone-row')).toHaveCount(5)

  // Default mode = downsampled curves (8 charts for a run).
  await expect(page.getByTestId('series-curve')).toBeVisible()
  await expect(page.getByTestId('ts-chart')).toHaveCount(8)
  await expect(page.getByTestId('series-table')).toHaveCount(0)

  // Switch to the per-second table.
  await page.getByTestId('mode-table').click()
  await expect(page.getByTestId('series-table')).toBeVisible()
  await expect(page.getByTestId('record-table')).toBeVisible()
  await expect(page.getByTestId('pager-info')).toContainText('1890')
  await expect(page.getByTestId('series-curve')).toHaveCount(0)

  // And back to the curve view.
  await page.getByTestId('mode-curve').click()
  await expect(page.getByTestId('series-curve')).toBeVisible()

  // Returning to the list works.
  await page.getByRole('link', { name: '← 返回运动记录' }).click()
  await expect(page.getByTestId('page-activities')).toBeVisible()
})

// AC-008b-1 (C-8): on mobile the per-second table and the laps table drop their
// wide grids for card lists — no min-width:820px element is visible and the page
// does not overflow the 390px viewport.
test('mobile: per-second table and laps render as cards with no wide-grid overflow', async ({
  page,
}) => {
  await page.setViewportSize(MOBILE)
  await page.goto(FIT_DETAIL_URL)
  await expect(page.getByTestId('page-activity-detail')).toBeVisible()
  await expect(page.getByText('晨间轻松跑')).toBeVisible()

  // Precondition: switch the time-series section to the per-second data table.
  await page.getByTestId('mode-table').click()
  await expect(page.getByTestId('record-table')).toBeVisible()

  // The min-width:820px grid is hidden; the card list takes over.
  const gridDisplay = await page
    .locator('.record-table__grid')
    .evaluate((el) => getComputedStyle(el).display)
  expect(gridDisplay).toBe('none')
  await expect(page.getByTestId('record-card').first()).toBeVisible()

  // No *visible* element carries min-width:820px in card mode.
  const hasWideGrid = await page.evaluate(() =>
    [...document.querySelectorAll('*')].some(
      (el) => getComputedStyle(el).minWidth === '820px' && el.getClientRects().length > 0,
    ),
  )
  expect(hasWideGrid).toBe(false)

  // Laps: one card per lap (the desktop grid rows are hidden).
  const lapRows = await page.getByTestId('lap-row').count()
  expect(lapRows).toBeGreaterThan(0)
  await expect(page.getByTestId('lap-card')).toHaveCount(lapRows)
  const lapsGridDisplay = await page
    .getByTestId('laps-table')
    .evaluate((el) => getComputedStyle(el).display)
  expect(lapsGridDisplay).toBe('none')

  // The document does not overflow the 390px viewport.
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth)
  expect(scrollWidth).toBeLessThanOrEqual(390)
})

// AC-008b-2 (C-8): X-axis ticks bin by breakpoint (desktop 5 / mobile 3), the Y
// axis stays 3, and every chart SVG renders no wider than its container.
test('chart X ticks bin by breakpoint; svg never exceeds its container', async ({ page }) => {
  await page.setViewportSize(DESKTOP)
  await page.goto(FIT_DETAIL_URL)
  await expect(page.getByTestId('series-curve')).toBeVisible()

  // Desktop: 5 X ticks + 3 Y ticks on the first chart; no SVG overflows.
  const firstChart = page.getByTestId('ts-svg').first()
  await expect(firstChart.getByTestId('ts-xtick')).toHaveCount(5)
  await expect(firstChart.getByTestId('ts-ytick')).toHaveCount(3)
  await expectSvgsFitContainer(page)

  // Mobile: 3 X ticks (first/middle/last), Y axis still 3; no SVG overflows.
  await page.setViewportSize(MOBILE)
  await expect(firstChart.getByTestId('ts-xtick')).toHaveCount(3)
  await expect(firstChart.getByTestId('ts-ytick')).toHaveCount(3)
  await expectSvgsFitContainer(page)
})
