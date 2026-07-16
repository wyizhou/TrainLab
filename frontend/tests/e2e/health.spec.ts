import { test, expect, type Locator, type Page } from '@playwright/test'
import { generateSleep } from '../../src/health/healthData'

// Baseline viewports (contract G-resp): mobile 390 / tablet 768 / desktop 1280.
const MOBILE = { width: 390, height: 844 }
const TABLET = { width: 768, height: 1024 }
const DESKTOP = { width: 1280, height: 800 }

// Read individual computed longhands (shorthand serialization is unstable — 验法细则).
async function computed(locator: Locator, props: string[]): Promise<Record<string, string>> {
  return locator.evaluate((el, keys) => {
    const s = getComputedStyle(el)
    const out: Record<string, string> = {}
    for (const k of keys) out[k] = s.getPropertyValue(k)
    return out
  }, props)
}

const RADIUS_CORNERS = [
  'border-top-left-radius',
  'border-top-right-radius',
  'border-bottom-right-radius',
  'border-bottom-left-radius',
]

// The four health tabs that carry a paginated detail table (习惯 has none).
const TABLE_TABS = ['睡眠', '体重', '静息心率', 'HRV'] as const

// True if any *visible* element carries min-width:420px — the detail table's wide
// grid, which must be display:none once the card list takes over (AC-009b-2).
async function hasWideGrid(page: Page): Promise<boolean> {
  return page.evaluate(() =>
    [...document.querySelectorAll('*')].some(
      (el) => getComputedStyle(el).minWidth === '420px' && el.getClientRects().length > 0,
    ),
  )
}

// AC-009b-1 (C-9): the sleep bar count bins by breakpoint — mobile 7 (近 7 天),
// tablet 14 (近 14 天) — and the title stays in sync with the count.
test('sleep bars bin by breakpoint: mobile 7 / tablet 14 with matching title', async ({ page }) => {
  // Mobile: 7 bars, title 含「近 7 天」.
  await page.setViewportSize(MOBILE)
  await page.goto('/health')
  await expect(page.getByTestId('page-health')).toBeVisible()
  await expect(page.getByTestId('sleep-stack')).toBeVisible()

  await expect(page.getByTestId('sleep-bar')).toHaveCount(7)
  await expect(page.getByTestId('sleep-title')).toContainText('近 7 天')

  // Tablet: 14 bars, title 含「近 14 天」.
  await page.setViewportSize(TABLET)
  await expect(page.getByTestId('sleep-bar')).toHaveCount(14)
  await expect(page.getByTestId('sleep-title')).toContainText('近 14 天')
})

// AC-009b-2 (C-9): on mobile all four detail tables drop their min-width grid for
// a card list — no min-width:420px element is visible and the page does not
// overflow the 390px viewport, on every table tab.
test('mobile: four detail tables render as cards with no wide-grid overflow', async ({ page }) => {
  await page.setViewportSize(MOBILE)
  await page.goto('/health')
  await expect(page.getByTestId('page-health')).toBeVisible()

  for (const label of TABLE_TABS) {
    await page.getByRole('tab', { name: label }).click()
    await expect(page.getByTestId('metric-table')).toBeVisible()

    // The min-width:420px grid is hidden; the card list takes over.
    const gridDisplay = await page
      .locator('.metric-table__scroll')
      .evaluate((el) => getComputedStyle(el).display)
    expect(gridDisplay, `grid hidden on ${label}`).toBe('none')
    await expect(page.getByTestId('metric-card').first()).toBeVisible()

    // No *visible* element carries min-width:420px in card mode.
    expect(await hasWideGrid(page), `wide grid visible on ${label}`).toBe(false)

    // The document does not overflow the 390px viewport.
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth)
    expect(scrollWidth, `overflow on ${label}`).toBeLessThanOrEqual(390)
  }
})

// AC-009c-1 (C-9): the sleep stacked-bar three segments carry pixel-contract
// colours + asymmetric radii — deep (accentDeep, bottom-rounded 0 0 3 3), light
// (accent, square), rem (sleepRem, top-rounded 3 3 0 0). Desktop, 睡眠 sub-tab.
test('AC-009c-1: sleep stacked-bar segment colours + radii (desktop)', async ({ page }) => {
  await page.setViewportSize(DESKTOP)
  await page.goto('/health')
  await expect(page.getByTestId('page-health')).toBeVisible()
  // 睡眠 is the default sub-tab; click it to satisfy the 前置数据 explicitly.
  await page.getByRole('tab', { name: '睡眠' }).click()

  const deep = page.locator('[data-vc="sleep-chart-bar-deep"]')
  const light = page.locator('[data-vc="sleep-chart-bar-light"]')
  const rem = page.locator('[data-vc="sleep-chart-bar-rem"]')
  await expect(deep).toHaveCount(14)
  await expect(light).toHaveCount(14)
  await expect(rem).toHaveCount(14)

  const deepC = await computed(deep.first(), ['background-color', ...RADIUS_CORNERS])
  expect(deepC['background-color']).toBe('rgb(49, 95, 154)') // accentDeep
  expect(deepC['border-top-left-radius']).toBe('0px')
  expect(deepC['border-top-right-radius']).toBe('0px')
  expect(deepC['border-bottom-right-radius']).toBe('3px')
  expect(deepC['border-bottom-left-radius']).toBe('3px')

  const lightC = await computed(light.first(), ['background-color', ...RADIUS_CORNERS])
  expect(lightC['background-color']).toBe('rgb(47, 127, 196)') // accent
  for (const corner of RADIUS_CORNERS) expect(lightC[corner]).toBe('0px')

  const remC = await computed(rem.first(), ['background-color', ...RADIUS_CORNERS])
  expect(remC['background-color']).toBe('rgb(106, 166, 221)') // sleepRem
  expect(remC['border-top-left-radius']).toBe('3px')
  expect(remC['border-top-right-radius']).toBe('3px')
  expect(remC['border-bottom-right-radius']).toBe('0px')
  expect(remC['border-bottom-left-radius']).toBe('0px')
})

test('sleep segment geometry uses the fixed 15px-per-hour scale', async ({ page }) => {
  await page.setViewportSize(DESKTOP)
  await page.goto('/health')
  await expect(page.getByTestId('sleep-bar')).toHaveCount(14)

  const firstRecord = generateSleep().slice(0, 14).reverse()[0]
  const expectedHeights = {
    rem: firstRecord.remMin / 4,
    light: firstRecord.lightMin / 4,
    deep: firstRecord.deepMin / 4,
  }
  const actualHeights = await page
    .getByTestId('sleep-bar')
    .first()
    .evaluate((bar) => ({
      rem: (
        bar.querySelector('[data-vc="sleep-chart-bar-rem"]') as HTMLElement
      ).getBoundingClientRect().height,
      light: (
        bar.querySelector('[data-vc="sleep-chart-bar-light"]') as HTMLElement
      ).getBoundingClientRect().height,
      deep: (
        bar.querySelector('[data-vc="sleep-chart-bar-deep"]') as HTMLElement
      ).getBoundingClientRect().height,
    }))

  expect(actualHeights.rem).toBeCloseTo(expectedHeights.rem, 1)
  expect(actualHeights.light).toBeCloseTo(expectedHeights.light, 1)
  expect(actualHeights.deep).toBeCloseTo(expectedHeights.deep, 1)
})

// AC-009c-2 (C-9): health-tab selected vs 常态 visual contract. Desktop.
test('AC-009c-2: health-tab selected vs 常态 contract (desktop)', async ({ page }) => {
  await page.setViewportSize(DESKTOP)
  await page.goto('/health')
  await expect(page.getByTestId('page-health')).toBeVisible()

  const selected = page.locator('[data-vc="health-tab-selected"]')
  const normal = page.locator('[data-vc="health-tab"]').first()
  await expect(selected).toHaveCount(1)
  await expect(normal).toBeVisible()

  const s = await computed(selected, [
    'background-color',
    'border-top-width',
    'border-top-style',
    'border-top-color',
    'color',
    'border-top-left-radius',
    'padding-top',
    'padding-right',
    'padding-bottom',
    'padding-left',
    'font-size',
  ])
  expect(s['background-color']).toBe('rgba(47, 127, 196, 0.16)') // accent@0.16
  expect(s['border-top-width']).toBe('1px')
  expect(s['border-top-style']).toBe('solid')
  expect(s['border-top-color']).toBe('rgb(47, 127, 196)') // accent
  expect(s['color']).toBe('rgb(37, 110, 168)') // accentText
  expect(s['border-top-left-radius']).toBe('8px') // radiusInput
  expect(s['padding-top']).toBe('7px') // padTab
  expect(s['padding-right']).toBe('18px')
  expect(s['padding-bottom']).toBe('7px')
  expect(s['padding-left']).toBe('18px')
  expect(s['font-size']).toBe('13px')

  const n = await computed(normal, [
    'background-color',
    'border-top-width',
    'border-top-style',
    'border-top-color',
    'color',
  ])
  expect(n['background-color']).toBe('rgb(255, 255, 255)') // panel
  expect(n['border-top-width']).toBe('1px')
  expect(n['border-top-style']).toBe('solid')
  expect(n['border-top-color']).toBe('rgb(203, 213, 225)') // borderPanel
  expect(n['color']).toBe('rgb(91, 107, 126)') // textMuted
})
