import { test, expect, type Page } from '@playwright/test'

// Baseline viewports (contract G-resp): mobile 390 / desktop 1280.
const MOBILE = { width: 390, height: 844 }
const DESKTOP = { width: 1280, height: 800 }

// Top-left corner of each connector card, in document coordinates, ordered by
// DOM order (中国区 then 国际区). The demo renders exactly two cards.
async function cardRects(page: Page): Promise<Array<{ top: number; left: number }>> {
  return page.getByTestId('connector-card').evaluateAll((els) =>
    els.map((el) => {
      const r = el.getBoundingClientRect()
      return { top: Math.round(r.top), left: Math.round(r.left) }
    }),
  )
}

// AC-010b-1 (C-10): the card grid is `minmax(min(320px,100%),1fr)` — two cards
// stack into a single column on mobile and sit side by side on desktop, with no
// horizontal overflow at either viewport.
test('connector cards: stack on mobile, share a row on desktop, never overflow', async ({
  page,
}) => {
  // Mobile: single column — the second card sits below the first.
  await page.setViewportSize(MOBILE)
  await page.goto('/connectors')
  await expect(page.getByTestId('page-connectors')).toBeVisible()
  await expect(page.getByTestId('connector-card')).toHaveCount(2)

  const mobile = await cardRects(page)
  expect(mobile[1].top, 'second card stacks below first on mobile').toBeGreaterThan(mobile[0].top)
  const mobileScroll = await page.evaluate(() => document.documentElement.scrollWidth)
  expect(mobileScroll, 'no horizontal overflow on mobile').toBeLessThanOrEqual(MOBILE.width)

  // Desktop: two columns — the cards align on the same row at different lefts.
  await page.setViewportSize(DESKTOP)
  const desktop = await cardRects(page)
  expect(desktop[1].top, 'cards share a row on desktop').toBe(desktop[0].top)
  expect(desktop[1].left, 'cards occupy different columns on desktop').not.toBe(desktop[0].left)
  const desktopScroll = await page.evaluate(() => document.documentElement.scrollWidth)
  expect(desktopScroll, 'no horizontal overflow on desktop').toBeLessThanOrEqual(DESKTOP.width)
})
