import { test, expect, type Locator, type Page } from '@playwright/test'

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

// Top-left corner of each connector card, in document coords, in DOM order.
async function cardRects(page: Page): Promise<Array<{ top: number; left: number }>> {
  return page.locator('[data-vc="connector-card"]').evaluateAll((els) =>
    els.map((el) => {
      const r = el.getBoundingClientRect()
      return { top: Math.round(r.top), left: Math.round(r.left) }
    }),
  )
}

// ── C-10 AC-010c-1: connectors-grid column breakpoints + connector-card visual
//    contract. Desktop = 2 cols side by side / mobile = 1 col stacked (filled-
//    column geometry, auto-fit 验法细则); gap 16; card panel bg / borderPanel /
//    radiusCard 12 / padConnectorCard 20. ─────────────────────────────────────
test('AC-010c-1: connectors-grid columns + connector-card contract (mobile + desktop)', async ({
  page,
}) => {
  // Desktop: grid display, gap 16, two cards share a row (2 filled columns).
  await page.setViewportSize(DESKTOP)
  await page.goto('/connectors')

  const grid = page.locator('[data-vc="connectors-grid"]')
  await expect(grid).toHaveCount(1)
  const g = await computed(grid, ['display', 'gap'])
  expect(g['display']).toBe('grid')
  expect(g['gap']).toBe('16px')

  const desktop = await cardRects(page)
  expect(desktop, 'demo renders exactly two connector cards').toHaveLength(2)
  expect(desktop[1].top, 'cards share a row on desktop (2 cols)').toBe(desktop[0].top)
  expect(desktop[1].left, 'cards occupy different columns on desktop').not.toBe(desktop[0].left)

  // connector-card panel contract.
  const card = page.locator('[data-vc="connector-card"]').first()
  const c = await computed(card, [
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
  expect(c['background-color']).toBe('rgb(255, 255, 255)') // panel
  expect(c['border-top-width']).toBe('1px')
  expect(c['border-top-style']).toBe('solid')
  expect(c['border-top-color']).toBe('rgb(203, 213, 225)') // borderPanel
  expect(c['border-radius']).toBe('12px') // radiusCard
  expect(c['padding-top']).toBe('20px')
  expect(c['padding-right']).toBe('20px')
  expect(c['padding-bottom']).toBe('20px')
  expect(c['padding-left']).toBe('20px')

  // Mobile: single column — the second card stacks below the first.
  await page.setViewportSize(MOBILE)
  await page.goto('/connectors')
  const mobile = await cardRects(page)
  expect(mobile[1].top, 'second card stacks below first on mobile (1 col)').toBeGreaterThan(
    mobile[0].top,
  )
})

// ── C-10 AC-010c-2: status-pill three-state colour contract (desktop). Demo
//    initial state = 中国区 failed / 国际区 disconnected; connected is captured
//    after triggering one successful sync. Common: pill 圆角 99 / padding 4 12 /
//    font-size 11 / border-width 1. ──────────────────────────────────────────
test('AC-010c-2: status-pill three-state visual contract (desktop)', async ({ page }) => {
  await page.setViewportSize(DESKTOP)
  await page.goto('/connectors')

  const common = [
    'border-radius',
    'padding-top',
    'padding-right',
    'padding-bottom',
    'padding-left',
    'font-size',
    'border-top-width',
  ]
  const expectCommon = (v: Record<string, string>) => {
    expect(v['border-radius']).toBe('99px')
    expect(v['padding-top']).toBe('4px')
    expect(v['padding-bottom']).toBe('4px')
    expect(v['padding-left']).toBe('12px')
    expect(v['padding-right']).toBe('12px')
    expect(v['font-size']).toBe('11px')
    expect(v['border-top-width']).toBe('1px')
  }

  // failed (中国区, demo initial): danger 字 · danger@0.10 底 · danger@0.40 边框.
  const failed = page.locator('[data-vc="status-pill-failed"]')
  await expect(failed).toHaveCount(1)
  const f = await computed(failed, [...common, 'color', 'background-color', 'border-top-color'])
  expectCommon(f)
  expect(f['color']).toBe('rgb(194, 65, 65)')
  expect(f['background-color']).toBe('rgba(194, 65, 65, 0.1)')
  expect(f['border-top-color']).toBe('rgba(194, 65, 65, 0.4)')

  // disconnected (国际区, demo initial): textMuted 字 · textMuted@0.10 底 · borderInput 边框.
  const disconnected = page.locator('[data-vc="status-pill-disconnected"]')
  await expect(disconnected).toHaveCount(1)
  const d = await computed(disconnected, [
    ...common,
    'color',
    'background-color',
    'border-top-color',
  ])
  expectCommon(d)
  expect(d['color']).toBe('rgb(91, 107, 126)')
  expect(d['background-color']).toBe('rgba(91, 107, 126, 0.1)')
  expect(d['border-top-color']).toBe('rgb(183, 196, 210)') // borderInput

  // connected: trigger one successful sync on the failed (中国区) card → 已连接.
  await page.locator('[data-status="failed"] [data-testid="connector-action"]').click()
  const connected = page.locator('[data-vc="status-pill-connected"]')
  await expect(connected).toHaveCount(1)
  const cc = await computed(connected, [...common, 'color', 'background-color', 'border-top-color'])
  expectCommon(cc)
  expect(cc['color']).toBe('rgb(22, 128, 93)')
  expect(cc['background-color']).toBe('rgba(22, 128, 93, 0.12)')
  expect(cc['border-top-color']).toBe('rgba(22, 128, 93, 0.35)')
})
