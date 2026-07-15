import { test, expect, type Locator, type Page } from '@playwright/test'

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

// Send an analysis question so both a user bubble and an AI bubble land in the DOM.
async function sendMessage(page: Page) {
  await page.goto('/')
  await page.getByTestId('chat-input').fill('分析我最近的心率趋势')
  await page.getByRole('button', { name: '发送' }).click()
  await expect(page.getByTestId('msg-ai').last()).toBeVisible()
}

function corners(el: Element) {
  const s = getComputedStyle(el)
  return {
    tl: s.borderTopLeftRadius,
    tr: s.borderTopRightRadius,
    br: s.borderBottomRightRadius,
    bl: s.borderBottomLeftRadius,
  }
}

// AC-006b-1 (C-6): the tail corner is asymmetric — 4px on the sender-facing
// bottom corner, 14px on the other three. User points bottom-right, AI bottom-left.
test('user / AI bubbles carry the 4px asymmetric tail corner (desktop)', async ({ page }) => {
  await page.setViewportSize(DESKTOP)
  await sendMessage(page)

  const user = await page.getByTestId('msg-user').evaluate(corners)
  expect(user.br).toBe('4px')
  expect(user.tl).toBe('14px')
  expect(user.tr).toBe('14px')
  expect(user.bl).toBe('14px')

  const ai = await page.getByTestId('msg-ai').last().evaluate(corners)
  expect(ai.bl).toBe('4px')
  expect(ai.tl).toBe('14px')
  expect(ai.tr).toBe('14px')
  expect(ai.br).toBe('14px')
})

// AC-006b-2 (C-6): the AI bubble no longer carries the 46% min-width floor — it
// hugs its content on every viewport — and its max-width fills the container on
// mobile. Both are read from computed style, independent of reply length.
test('AI bubble has no min-width floor; max-width fills the container on mobile', async ({
  page,
}) => {
  for (const vp of [MOBILE, DESKTOP]) {
    await page.setViewportSize(vp)
    await sendMessage(page)
    const minWidth = await page
      .getByTestId('msg-ai')
      .last()
      .evaluate((el) => getComputedStyle(el).minWidth)
    // No 46% floor: resolves to the content-hugging default (auto / 0).
    expect(minWidth).toMatch(/^(auto|0px)$/)
  }

  // Mobile: max-width resolves to the thread container's full width (100%).
  await page.setViewportSize(MOBILE)
  await sendMessage(page)
  const maxWidth = await page
    .getByTestId('msg-ai')
    .last()
    .evaluate((el) => getComputedStyle(el).maxWidth)
  const containerWidth = await page.getByTestId('analysis-thread').evaluate((el) => el.clientWidth)
  if (maxWidth.endsWith('%')) {
    expect(maxWidth).toBe('100%')
  } else {
    // Browser resolved the percentage to px — must equal the container width.
    expect(Math.abs(parseFloat(maxWidth) - containerWidth)).toBeLessThanOrEqual(0.5)
  }
})

// ── pixel-contract (design_rev 3/4, C-6 AC-006c-1/2/3). data-vc mirrored onto the
//    bubble roots; colour zero-tolerance, px exact. Desktop anchor for the visual
//    contracts; all three breakpoints for the graded max-width. ─────────────────

// AC-006c-1 (C-6): the AI bubble is a standalone panel — panel bg · borderPanel
// 1px · radius 14/14/14/4 · pad 13/16 · text colour (not bare text).
test('AC-006c-1: AI bubble full visual contract (desktop)', async ({ page }) => {
  await page.setViewportSize(DESKTOP)
  await sendMessage(page)

  const ai = page.locator('[data-vc="chat-bubble-ai"]').last()
  const c = await computed(ai, [
    'background-color',
    'border-top-width',
    'border-top-style',
    'border-top-color',
    'padding-top',
    'padding-right',
    'padding-bottom',
    'padding-left',
    'color',
  ])
  expect(c['background-color']).toBe('rgb(18, 26, 40)')
  expect(c['border-top-width']).toBe('1px')
  expect(c['border-top-style']).toBe('solid')
  expect(c['border-top-color']).toBe('rgb(34, 48, 73)')
  // padding 13px 16px.
  expect(c['padding-top']).toBe('13px')
  expect(c['padding-right']).toBe('16px')
  expect(c['padding-bottom']).toBe('13px')
  expect(c['padding-left']).toBe('16px')
  expect(c['color']).toBe('rgb(230, 235, 244)')
  // border-radius 14px 14px 14px 4px (bottom-left tail).
  const r = await ai.evaluate(corners)
  expect(r).toEqual({ tl: '14px', tr: '14px', br: '14px', bl: '4px' })
})

// AC-006c-2 (C-6): the user bubble is solid accentDeep blue with no border —
// bg rgb(46,92,158) · border none · radius 14/14/4/14 · pad 12/14 · text colour.
test('AC-006c-2: user bubble full visual contract (desktop)', async ({ page }) => {
  await page.setViewportSize(DESKTOP)
  await sendMessage(page)

  const user = page.locator('[data-vc="chat-bubble-user"]')
  const c = await computed(user, [
    'background-color',
    'border-top-style',
    'padding-top',
    'padding-right',
    'padding-bottom',
    'padding-left',
    'color',
  ])
  expect(c['background-color']).toBe('rgb(46, 92, 158)')
  expect(c['border-top-style']).toBe('none')
  // padding 12px 14px.
  expect(c['padding-top']).toBe('12px')
  expect(c['padding-right']).toBe('14px')
  expect(c['padding-bottom']).toBe('12px')
  expect(c['padding-left']).toBe('14px')
  expect(c['color']).toBe('rgb(230, 235, 244)')
  // border-radius 14px 14px 4px 14px (bottom-right tail).
  const r = await user.evaluate(corners)
  expect(r).toEqual({ tl: '14px', tr: '14px', br: '4px', bl: '14px' })
})

// Assert the bubble's computed max-width resolves to `pct`% of the thread
// container — whether the browser keeps the percentage or resolves it to px
// (承接 §7.3 max-width 细则: computed_px == round(容器内容宽 × pct) ±1px).
async function expectMaxWidth(page: Page, selector: string, pct: number) {
  const maxWidth = await page
    .locator(selector)
    .last()
    .evaluate((el) => getComputedStyle(el).maxWidth)
  const containerWidth = await page.getByTestId('analysis-thread').evaluate((el) => el.clientWidth)
  if (maxWidth.endsWith('%')) {
    expect(maxWidth).toBe(`${pct}%`)
  } else {
    expect(
      Math.abs(parseFloat(maxWidth) - Math.round((containerWidth * pct) / 100)),
    ).toBeLessThanOrEqual(1)
  }
}

// AC-006c-3 (C-6): bubble max-width graded per G-resp breakpoint —
// AI 82/92/100%, user 68/80/94% across desktop / tablet / mobile.
test('AC-006c-3: bubble max-width graded per breakpoint', async ({ page }) => {
  const cases = [
    { vp: DESKTOP, ai: 82, user: 68 },
    { vp: TABLET, ai: 92, user: 80 },
    { vp: MOBILE, ai: 100, user: 94 },
  ]
  for (const { vp, ai, user } of cases) {
    await page.setViewportSize(vp)
    await sendMessage(page)
    await expectMaxWidth(page, '[data-vc="chat-bubble-ai"]', ai)
    await expectMaxWidth(page, '[data-vc="chat-bubble-user"]', user)
  }
})
