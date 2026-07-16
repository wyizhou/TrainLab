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

// Parse `rgb(r, g, b)` into a channel triple for layer-depth comparison.
function rgbChannels(value: string): [number, number, number] {
  const m = value.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/)
  if (!m) throw new Error(`not an rgb() value: ${value}`)
  return [Number(m[1]), Number(m[2]), Number(m[3])]
}

// Send an analysis question and expand the resulting chart card. Returns the
// card locator, sitting in the expanded state.
async function expandChartCard(page: import('@playwright/test').Page) {
  await page.goto('/')
  await page.getByTestId('chat-input').fill('分析我最近的心率趋势')
  await page.getByRole('button', { name: '发送' }).click()

  const card = page.getByTestId('chart-card')
  await expect(card).toHaveAttribute('data-state', 'collapsed')
  await page.getByRole('button', { name: '展开 ▼' }).click()
  await expect(card).toHaveAttribute('data-state', 'expanded')
  return card
}

// E2E 门禁#5 (C-5 ＋ C-6 联合流): 发送分析提问 → AI 气泡文本先到 →
// 卡片加载 → 折叠就绪 → 展开显示折线图。追溯覆盖 005 延后的 C-5 e2e。
test('analysis question -> AI text first -> card loads -> collapsed -> expand shows line chart', async ({
  page,
}) => {
  await page.goto('/')

  await page.getByTestId('chat-input').fill('分析我最近的心率趋势')
  await page.getByRole('button', { name: '发送' }).click()

  // AI bubble text lands first — the HTML reply (table) is visible immediately.
  const bubble = page.getByTestId('msg-ai').last()
  await expect(bubble).toBeVisible()
  await expect(bubble.getByRole('table')).toBeVisible()

  // The chart card starts in the loading state, then resolves to collapsed.
  const card = page.getByTestId('chart-card')
  await expect(card).toHaveAttribute('data-state', 'loading')
  await expect(card).toHaveAttribute('data-state', 'collapsed')

  // Expanding reveals the line chart.
  await page.getByRole('button', { name: '展开 ▼' }).click()
  await expect(page.getByTestId('chart-svg')).toBeVisible()
  await expect(card).toHaveAttribute('data-state', 'expanded')
})

// ── pixel-contract (C-5 AC-005c-1). Colour zero-tolerance; px exact. Desktop
//    anchor; card in the collapsed (ready) state. The chart card uses the
//    deeper panel surface inside the outer AI bubble. ─────────────────────────
test('AC-005c-1: chart-card container visual contract + deeper than AI bubble (desktop)', async ({
  page,
}) => {
  await page.setViewportSize(DESKTOP)
  await page.goto('/')
  await page.getByTestId('chat-input').fill('分析我最近的心率趋势')
  await page.getByRole('button', { name: '发送' }).click()

  const card = page.locator('[data-vc="chart-card"]')
  await expect(card).toHaveAttribute('data-state', 'collapsed')

  // panelDeep fill · borderInput border · radius-md 10px · overflow hidden.
  const c = await computed(card, [
    'background-color',
    'border-top-width',
    'border-top-style',
    'border-top-color',
    'border-radius',
    'overflow-x',
    'overflow-y',
  ])
  expect(c['background-color']).toBe('rgb(244, 247, 250)')
  expect(c['border-top-width']).toBe('1px')
  expect(c['border-top-style']).toBe('solid')
  expect(c['border-top-color']).toBe('rgb(183, 196, 210)')
  expect(c['border-radius']).toBe('10px')
  expect(c['overflow-x']).toBe('hidden')
  expect(c['overflow-y']).toBe('hidden')

  // Layer check: the card is strictly deeper than the outer AI bubble.
  const bubbleBg = (await computed(page.getByTestId('msg-ai').last(), ['background-color']))[
    'background-color'
  ]
  expect(bubbleBg).toBe('rgb(255, 255, 255)')
  const cardCh = rgbChannels(c['background-color'])
  const bubbleCh = rgbChannels(bubbleBg)
  for (let i = 0; i < 3; i++) expect(cardCh[i]).toBeLessThan(bubbleCh[i])
})

// AC-005b-1 (C-5): the expanded per-activity data rows render on desktop only —
// tablet drops the rows container from the DOM, keeping only the axis note + svg.
test('desktop shows the data rows; tablet drops them, keeping only the chart', async ({ page }) => {
  // Tablet: the rows container is absent from the DOM; axis note + chart remain.
  await page.setViewportSize(TABLET)
  const tabletCard = await expandChartCard(page)
  await expect(tabletCard.getByTestId('chart-rows')).toHaveCount(0)
  await expect(tabletCard.getByText('Y:bpm · X:日期')).toBeVisible()
  await expect(tabletCard.getByTestId('chart-svg')).toBeVisible()

  // Desktop: the rows exist; each row is 12px and its values are mono.
  await page.setViewportSize(DESKTOP)
  const desktopCard = await expandChartCard(page)
  const rows = desktopCard.getByTestId('chart-rows')
  await expect(rows).toBeVisible()
  const row = rows.locator('.chart-card__row').first()
  expect(await row.evaluate((el) => getComputedStyle(el).fontSize)).toBe('12px')
  const value = row.locator('.chart-card__row-value')
  expect(await value.evaluate((el) => getComputedStyle(el).fontFamily)).toMatch(/mono/)
})

// AC-005b-2 (C-5): the expanded chart svg keeps its 340×112 viewBox and its
// rendered width never overflows the container, across mobile and desktop.
test('expanded chart svg fits its container without overflowing', async ({ page }) => {
  for (const vp of [MOBILE, DESKTOP]) {
    await page.setViewportSize(vp)
    const card = await expandChartCard(page)
    const svg = card.getByTestId('chart-svg')
    await expect(svg).toHaveAttribute('viewBox', '0 0 340 112')

    const svgWidth = await svg.evaluate((el) => el.getBoundingClientRect().width)
    const containerWidth = await card
      .locator('.chart-card__expanded')
      .evaluate((el) => el.getBoundingClientRect().width)
    // Sub-pixel tolerance for fractional layout widths.
    expect(svgWidth).toBeLessThanOrEqual(containerWidth + 0.5)
  }
})
