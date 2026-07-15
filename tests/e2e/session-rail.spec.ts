import { test, expect, type Locator } from '@playwright/test'

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

// C-3 e2e: new -> rename -> delete-to-empty auto-create, full chain.
test('creates, renames, and deletes sessions until empty auto-creates one', async ({ page }) => {
  await page.goto('/')
  const rail = page.getByTestId('session-rail-desktop')
  await expect(rail.getByTestId('session-item')).toHaveCount(1)

  // New session becomes active.
  await rail.getByRole('button', { name: '新建会话' }).click()
  await expect(rail.getByTestId('session-item')).toHaveCount(2)

  // Inline rename: Enter confirms.
  await rail.getByRole('button', { name: '重命名 会话 2' }).click()
  const input = rail.getByLabel('会话名称')
  await input.fill('训练分析')
  await input.press('Enter')
  await expect(rail.getByText('训练分析')).toBeVisible()

  // Delete the active session -> falls back to the first remaining.
  await rail.getByRole('button', { name: '删除 训练分析' }).click()
  await expect(rail.getByTestId('session-item')).toHaveCount(1)
  await expect(rail.getByText('会话 1')).toBeVisible()

  // Delete the last session -> a fresh one is auto-created.
  await rail.getByRole('button', { name: '删除 会话 1' }).click()
  await expect(rail.getByTestId('session-item')).toHaveCount(1)
  await expect(rail.getByText('会话 1')).toHaveCount(0)
})

// AC-003b-1 (C-3): desktop keeps a 212px session aside; mobile/tablet drop the
// aside from the DOM entirely and expose a session dropdown + new button instead.
test('desktop shows a 212px session aside; mobile/tablet degrade to a dropdown', async ({
  page,
}) => {
  // Desktop: the aside exists and is ~212px wide.
  await page.setViewportSize(DESKTOP)
  await page.goto('/')
  const rail = page.getByTestId('session-rail-desktop')
  await expect(rail).toBeVisible()
  expect(await rail.evaluate((el) => (el as HTMLElement).offsetWidth)).toBe(212)
  await expect(page.getByTestId('session-rail-mobile')).toHaveCount(0)

  // Mobile and tablet: the aside is absent from the DOM, the dropdown + new
  // button take its place.
  for (const vp of [MOBILE, TABLET]) {
    await page.setViewportSize(vp)
    await page.goto('/')
    await expect(page.getByTestId('page-analysis')).toBeVisible()
    await expect(page.getByTestId('session-rail-desktop')).toHaveCount(0)
    const compact = page.getByTestId('session-rail-mobile')
    await expect(compact).toBeVisible()
    await expect(compact.getByLabel('选择会话')).toBeVisible()
    await expect(compact.getByRole('button', { name: '新建会话' })).toBeVisible()
  }
})

// ── pixel-contract (design_rev 3/4, C-3 AC-003c-1..4). Colour zero-tolerance;
//    px exact (±1 per 验法细则). Desktop-only anchors. ──────────────────────────

// AC-003c-1 — session-rail layout contract (desktop).
test('AC-003c-1: session-rail visual contract (desktop)', async ({ page }) => {
  await page.setViewportSize(DESKTOP)
  await page.goto('/')
  const rail = page.locator('[data-vc="session-rail"]')
  await expect(rail).toBeVisible()

  // width==212 is the border-box outer measure (global box-sizing: border-box),
  // matching AC-003b-1's offsetWidth==212 — the same box, two probes.
  expect(await rail.evaluate((el) => (el as HTMLElement).offsetWidth)).toBe(212)

  const c = await computed(rail, [
    'width',
    'flex-shrink',
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
  expect(c['width']).toBe('212px')
  expect(c['flex-shrink']).toBe('0')
  expect(c['background-color']).toBe('rgb(13, 20, 32)')
  expect(c['border-top-width']).toBe('1px')
  expect(c['border-top-style']).toBe('solid')
  expect(c['border-top-color']).toBe('rgb(28, 39, 57)')
  expect(c['border-radius']).toBe('12px')
  expect(c['padding-top']).toBe('12px')
  expect(c['padding-bottom']).toBe('12px')
  expect(c['padding-left']).toBe('10px')
  expect(c['padding-right']).toBe('10px')
})

// AC-003c-2 — session-rail-item selected vs normal contract (desktop).
// Precondition: ≥2 sessions so the active item and a normal item coexist on
// screen (承接 §7.4 可命中性补丁).
test('AC-003c-2: session-rail-item active/normal visual contract (desktop)', async ({ page }) => {
  await page.setViewportSize(DESKTOP)
  await page.goto('/')
  const rail = page.getByTestId('session-rail-desktop')
  // Seed a second session; the new one becomes active, 会话 1 becomes normal.
  await rail.getByRole('button', { name: '新建会话' }).click()
  await expect(rail.getByTestId('session-item')).toHaveCount(2)

  const active = page.locator('[data-vc="session-rail-item-active"]')
  const normal = page.locator('[data-vc="session-rail-item"]')
  await expect(active).toHaveCount(1)
  await expect(normal).toHaveCount(1)

  const a = await computed(active, [
    'background-color',
    'border-left-width',
    'border-left-style',
    'border-left-color',
    'border-radius',
    'padding-top',
    'padding-right',
    'padding-bottom',
    'padding-left',
  ])
  expect(a['background-color']).toBe('rgba(66, 146, 224, 0.12)')
  expect(a['border-left-width']).toBe('3px')
  expect(a['border-left-style']).toBe('solid')
  expect(a['border-left-color']).toBe('rgb(66, 146, 224)')
  expect(a['border-radius']).toBe('8px')
  expect(a['padding-top']).toBe('9px')
  expect(a['padding-bottom']).toBe('9px')
  expect(a['padding-left']).toBe('10px')
  expect(a['padding-right']).toBe('10px')

  // Normal item: transparent 3px placeholder (no jump) + transparent fill.
  const n = await computed(normal, [
    'border-left-width',
    'border-left-style',
    'border-left-color',
    'background-color',
  ])
  expect(n['border-left-width']).toBe('3px')
  expect(n['border-left-style']).toBe('solid')
  expect(n['border-left-color']).toBe('rgba(0, 0, 0, 0)')
  expect(n['background-color']).toBe('rgba(0, 0, 0, 0)')
})

// AC-003c-3 — analysis-main layout contract (desktop).
test('AC-003c-3: analysis-main visual contract (desktop)', async ({ page }) => {
  await page.setViewportSize(DESKTOP)
  await page.goto('/')
  const main = page.locator('[data-vc="analysis-main"]')
  await expect(main).toBeVisible()

  const c = await computed(main, [
    'display',
    'column-gap',
    'max-width',
    'margin-left',
    'margin-right',
  ])
  expect(c['display']).toBe('flex')
  expect(c['column-gap']).toBe('18px')
  expect(c['max-width']).toBe('1200px')
  // Centered: equal left/right margins.
  expect(c['margin-left']).toBe(c['margin-right'])
})

// AC-003c-4 — analysis-input contract + in-flow (non-fixed) (desktop).
test('AC-003c-4: analysis-input visual contract (desktop)', async ({ page }) => {
  await page.setViewportSize(DESKTOP)
  await page.goto('/')
  const input = page.locator('[data-vc="analysis-input"]')
  await expect(input).toBeVisible()

  const c = await computed(input, [
    'background-color',
    'border-top-width',
    'border-top-style',
    'border-top-color',
    'border-radius',
    'padding-top',
    'padding-right',
    'padding-bottom',
    'padding-left',
    'position',
  ])
  expect(c['background-color']).toBe('rgb(18, 26, 40)')
  expect(c['border-top-width']).toBe('1px')
  expect(c['border-top-style']).toBe('solid')
  expect(c['border-top-color']).toBe('rgb(34, 48, 73)')
  expect(c['border-radius']).toBe('14px')
  expect(c['padding-top']).toBe('12px')
  expect(c['padding-bottom']).toBe('12px')
  expect(c['padding-left']).toBe('14px')
  expect(c['padding-right']).toBe('14px')
  expect(c['position']).not.toBe('fixed')
})
