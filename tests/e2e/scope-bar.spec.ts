import { test, expect, type Locator } from '@playwright/test'

// Baseline viewports (contract G-resp): mobile 390 / desktop 1280.
const MOBILE = { width: 390, height: 844 }
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

// AC-004b-1 (C-4): on mobile the two companion toggles「附带健康记录」「附带习惯记录」
// flex-wrap onto separate rows and the page has no horizontal overflow.
test('mobile stacks the health/habit toggles onto separate rows without overflow', async ({
  page,
}) => {
  await page.setViewportSize(MOBILE)
  await page.goto('/')

  const bar = page.getByTestId('scope-bar')
  await expect(bar).toBeVisible()

  const health = bar.getByText('附带健康记录')
  const habit = bar.getByText('附带习惯记录')
  const healthBox = await health.boundingBox()
  const habitBox = await habit.boundingBox()
  expect(healthBox).not.toBeNull()
  expect(habitBox).not.toBeNull()

  // The second toggle sits on a lower row than the first (not the same line).
  expect(habitBox!.y).toBeGreaterThan(healthBox!.y)

  // No horizontal overflow at the mobile viewport.
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth)
  expect(scrollWidth).toBeLessThanOrEqual(390)
})

// ── pixel-contract (design_rev 3/4, C-4 AC-004c-1). Colour zero-tolerance; px
//    exact. Desktop anchor. Default load: range=3 → one selected chip + three
//    normal chips coexist, so both anchors are hittable. ──────────────────────
test('AC-004c-1: scope-chip selected vs normal visual contract (desktop)', async ({ page }) => {
  await page.setViewportSize(DESKTOP)
  await page.goto('/')

  const selected = page.locator('[data-vc="scope-chip-selected"]')
  const normal = page.locator('[data-vc="scope-chip"]').first()
  await expect(selected).toHaveCount(1)
  await expect(normal).toBeVisible()

  // Selected: accent@0.18 fill · accent border · accentText color · pill · padChip.
  const s = await computed(selected, [
    'background-color',
    'border-top-width',
    'border-top-style',
    'border-top-color',
    'color',
    'border-radius',
    'padding-top',
    'padding-right',
    'padding-bottom',
    'padding-left',
  ])
  expect(s['background-color']).toBe('rgba(66, 146, 224, 0.18)')
  expect(s['border-top-width']).toBe('1px')
  expect(s['border-top-style']).toBe('solid')
  expect(s['border-top-color']).toBe('rgb(66, 146, 224)')
  expect(s['color']).toBe('rgb(94, 163, 232)')
  expect(s['border-radius']).toBe('99px')
  expect(s['padding-top']).toBe('5px')
  expect(s['padding-bottom']).toBe('5px')
  expect(s['padding-left']).toBe('13px')
  expect(s['padding-right']).toBe('13px')

  // Normal: panelDeep fill · borderInput border · textMuted color.
  const n = await computed(normal, [
    'background-color',
    'border-top-width',
    'border-top-style',
    'border-top-color',
    'color',
  ])
  expect(n['background-color']).toBe('rgb(11, 18, 32)')
  expect(n['border-top-width']).toBe('1px')
  expect(n['border-top-style']).toBe('solid')
  expect(n['border-top-color']).toBe('rgb(42, 58, 85)')
  expect(n['color']).toBe('rgb(138, 148, 168)')
})
