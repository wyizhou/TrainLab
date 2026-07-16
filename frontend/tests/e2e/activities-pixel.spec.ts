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

// ── C-7 AC-007c-1: activities-table / card-list 断点重排 (display 契约). Desktop
//    shows the bordered scrollable table (card list absent from the DOM); mobile
//    hides the table and mounts the card list. ────────────────────────────────
test('AC-007c-1: activities-table / card-list breakpoint reflow (mobile + desktop)', async ({
  page,
}) => {
  // Desktop: table is the bordered panel; card list is not in the DOM.
  await page.setViewportSize(DESKTOP)
  await page.goto('/activities')

  const table = page.locator('[data-vc="activities-table"]')
  await expect(table).toHaveCount(1)

  const t = await computed(table, [
    'display',
    'background-color',
    'border-top-width',
    'border-top-style',
    'border-top-color',
    'border-radius',
    'overflow-x',
  ])
  expect(t['display']).not.toBe('none') // block
  expect(t['background-color']).toBe('rgb(18, 26, 40)') // panel
  expect(t['border-top-width']).toBe('1px')
  expect(t['border-top-style']).toBe('solid')
  expect(t['border-top-color']).toBe('rgb(34, 48, 73)') // borderPanel
  expect(t['border-radius']).toBe('12px') // radiusCard
  expect(t['overflow-x']).toBe('auto')

  // Inner track holds the fixed min-width:960px column grid.
  const inner = table.locator('> div').first()
  const i = await computed(inner, ['min-width'])
  expect(i['min-width']).toBe('960px')

  // Card list is absent from the DOM on desktop.
  await expect(page.locator('[data-vc="activities-card-list"]')).toHaveCount(0)

  // Mobile: the table is unmounted and the card list takes over.
  await page.setViewportSize(MOBILE)
  await page.goto('/activities')

  await expect(page.locator('[data-vc="activities-table"]')).toHaveCount(0)

  const cardList = page.locator('[data-vc="activities-card-list"]')
  await expect(cardList).toHaveCount(1)
  const c = await computed(cardList, ['display', 'flex-direction', 'gap'])
  expect(c['display']).toBe('flex')
  expect(c['flex-direction']).toBe('column')
  expect(c['gap']).toBe('10px') // gapCardMobile
})

// ── C-7 AC-007c-2: type-chip selected vs normal colour contract. Desktop anchor.
//    Default load: filter=全部 selected, the rest normal — both anchors hittable. ─
test('AC-007c-2: type-chip selected vs normal visual contract (desktop)', async ({ page }) => {
  await page.setViewportSize(DESKTOP)
  await page.goto('/activities')

  const selected = page.locator('[data-vc="type-chip-selected"]')
  const normal = page.locator('[data-vc="type-chip"]').first()
  await expect(selected).toHaveCount(1)
  await expect(normal).toBeVisible()

  // Selected: accent@0.16 fill · accent border · accentText color · pill · padChipType.
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
  expect(s['background-color']).toBe('rgba(66, 146, 224, 0.16)')
  expect(s['border-top-width']).toBe('1px')
  expect(s['border-top-style']).toBe('solid')
  expect(s['border-top-color']).toBe('rgb(66, 146, 224)')
  expect(s['color']).toBe('rgb(94, 163, 232)')
  expect(s['border-radius']).toBe('99px')
  expect(s['padding-top']).toBe('6px')
  expect(s['padding-bottom']).toBe('6px')
  expect(s['padding-left']).toBe('14px')
  expect(s['padding-right']).toBe('14px')

  // Normal: panel fill · borderPanel border · textMuted color.
  const n = await computed(normal, [
    'background-color',
    'border-top-width',
    'border-top-style',
    'border-top-color',
    'color',
  ])
  expect(n['background-color']).toBe('rgb(18, 26, 40)')
  expect(n['border-top-width']).toBe('1px')
  expect(n['border-top-style']).toBe('solid')
  expect(n['border-top-color']).toBe('rgb(34, 48, 73)')
  expect(n['color']).toBe('rgb(138, 148, 168)')
})
