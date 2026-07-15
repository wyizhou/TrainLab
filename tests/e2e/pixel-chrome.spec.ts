import { test, expect, type Locator } from '@playwright/test'

// Global chrome pixel-contract (contract C-1, AC-001c-1..5; design_rev 3/4 §A20).
// Each anchor's computed contract properties must equal the §A rgb/px values
// exactly (colour zero-tolerance, px ±1 per pixel-contract 验法细则). We read
// individual computed longhands (shorthand serialization is unstable — 验法细则).

const MOBILE = { width: 390, height: 844 }
const DESKTOP = { width: 1280, height: 800 }

async function computed(locator: Locator, props: string[]): Promise<Record<string, string>> {
  return locator.evaluate((el, keys) => {
    const s = getComputedStyle(el)
    const out: Record<string, string> = {}
    for (const k of keys) out[k] = s.getPropertyValue(k)
    return out
  }, props)
}

// AC-001c-1 — top-nav active item selected-state palette (§A20).
test('AC-001c-1: top-nav-item-active visual contract (desktop)', async ({ page }) => {
  await page.setViewportSize(DESKTOP)
  await page.goto('/')
  const active = page.locator('[data-vc="top-nav-item-active"]')
  await expect(active).toBeVisible()

  const c = await computed(active, [
    'background-color',
    'color',
    'font-weight',
    'border-radius',
    'padding-top',
    'padding-right',
    'padding-bottom',
    'padding-left',
  ])
  expect(c['background-color']).toBe('rgba(66, 146, 224, 0.16)')
  expect(c['color']).toBe('rgb(230, 235, 244)')
  expect(c['font-weight']).toBe('600')
  expect(c['border-radius']).toBe('8px')
  expect(c['padding-top']).toBe('8px')
  expect(c['padding-bottom']).toBe('8px')
  expect(c['padding-left']).toBe('13px')
  expect(c['padding-right']).toBe('13px')
})

// AC-001c-2 — sync-chip visual contract (desktop/wide only).
test('AC-001c-2: sync-chip visual contract (desktop)', async ({ page }) => {
  await page.setViewportSize(DESKTOP)
  await page.goto('/')
  const chip = page.locator('[data-vc="sync-chip"]')
  await expect(chip).toBeVisible()

  const c = await computed(chip, [
    'background-color',
    'border-top-width',
    'border-top-style',
    'border-top-color',
    'border-radius',
    'padding-top',
    'padding-right',
    'padding-bottom',
    'padding-left',
  ])
  expect(c['background-color']).toBe('rgb(18, 26, 40)')
  expect(c['border-top-width']).toBe('1px')
  expect(c['border-top-style']).toBe('solid')
  expect(c['border-top-color']).toBe('rgb(34, 48, 73)')
  expect(c['border-radius']).toBe('99px')
  expect(c['padding-top']).toBe('6px')
  expect(c['padding-bottom']).toBe('6px')
  expect(c['padding-left']).toBe('14px')
  expect(c['padding-right']).toBe('14px')
})

// AC-001c-3 — bottom-nav + active tab visual contract (mobile only).
test('AC-001c-3: bottom-nav visual contract (mobile)', async ({ page }) => {
  await page.setViewportSize(MOBILE)
  await page.goto('/')
  const bar = page.locator('[data-vc="bottom-nav"]')
  await expect(bar).toBeVisible()

  const nav = await computed(bar, [
    'position',
    'bottom',
    'height',
    'background-color',
    'border-top-width',
    'border-top-style',
    'border-top-color',
  ])
  expect(nav['position']).toBe('fixed')
  expect(nav['bottom']).toBe('0px')
  expect(nav['height']).toBe('60px')
  expect(nav['background-color']).toBe('rgb(13, 20, 32)')
  expect(nav['border-top-width']).toBe('1px')
  expect(nav['border-top-style']).toBe('solid')
  expect(nav['border-top-color']).toBe('rgb(28, 39, 57)')

  const active = page.locator('[data-vc="bottom-nav-item-active"]')
  const item = await computed(active, [
    'color',
    'border-top-width',
    'border-top-style',
    'border-top-color',
  ])
  expect(item['color']).toBe('rgb(94, 163, 232)')
  expect(item['border-top-width']).toBe('2px')
  expect(item['border-top-style']).toBe('solid')
  expect(item['border-top-color']).toBe('rgb(66, 146, 224)')
})

// AC-001c-4 — toast visual contract after a mock sync success (/connectors).
test('AC-001c-4: toast visual contract (desktop)', async ({ page }) => {
  await page.setViewportSize(DESKTOP)
  await page.goto('/connectors')

  // Trigger one sync success (中国区 starts 同步失败 → 重试同步) and wait for the toast.
  await page
    .getByTestId('connector-card')
    .filter({ hasText: '佳明中国区' })
    .getByTestId('connector-action')
    .click()
  const toast = page.locator('[data-vc="toast"]')
  await expect(toast).toBeVisible()

  const c = await computed(toast, [
    'position',
    'bottom',
    'background-color',
    'border-top-width',
    'border-top-style',
    'border-top-color',
    'border-radius',
    'padding-top',
    'padding-right',
    'padding-bottom',
    'padding-left',
    'font-size',
  ])
  expect(c['position']).toBe('fixed')
  expect(c['bottom']).toBe('28px')
  expect(c['background-color']).toBe('rgb(26, 36, 54)')
  expect(c['border-top-width']).toBe('1px')
  expect(c['border-top-style']).toBe('solid')
  expect(c['border-top-color']).toBe('rgb(58, 78, 112)')
  expect(c['border-radius']).toBe('10px')
  expect(c['padding-top']).toBe('11px')
  expect(c['padding-bottom']).toBe('11px')
  expect(c['padding-left']).toBe('22px')
  expect(c['padding-right']).toBe('22px')
  expect(c['font-size']).toBe('13px')
})

// AC-001c-5 — btn-primary (send button) visual contract.
test('AC-001c-5: btn-primary visual contract (desktop)', async ({ page }) => {
  await page.setViewportSize(DESKTOP)
  await page.goto('/')
  const btn = page.locator('[data-vc="btn-primary"]')
  await expect(btn).toBeVisible()

  const c = await computed(btn, [
    'background-color',
    'color',
    'border-top-style',
    'border-radius',
    'padding-top',
    'padding-right',
    'padding-bottom',
    'padding-left',
    'font-weight',
  ])
  expect(c['background-color']).toBe('rgb(66, 146, 224)')
  expect(c['color']).toBe('rgb(6, 16, 30)')
  expect(c['border-top-style']).toBe('none')
  expect(c['border-radius']).toBe('10px')
  expect(c['padding-top']).toBe('11px')
  expect(c['padding-bottom']).toBe('11px')
  expect(c['padding-left']).toBe('22px')
  expect(c['padding-right']).toBe('22px')
  expect(c['font-weight']).toBe('700')
})
