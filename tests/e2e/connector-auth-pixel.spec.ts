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

// Open the 2FA auth modal for the disconnected 国际区 card.
async function openAuthModal(page: Page) {
  const globalCard = page.getByTestId('connector-card').filter({ hasText: '佳明国际区' })
  await globalCard.getByTestId('connector-action').click()
  await expect(page.locator('[data-vc="modal-connector-auth"]')).toBeVisible()
}

// ── C-11 AC-011c-1: modal-connector-auth desktop 居中定宽 vs mobile 全屏 + modal-overlay
//    scrim contract. Hard req: data-vc anchors mirror the component roots. ─────────────
test('AC-011c-1: modal-connector-auth desktop centered 390 / mobile fullscreen + overlay scrim', async ({
  page,
}) => {
  // Desktop: centered fixed 390px card, panel visual contract.
  await page.setViewportSize(DESKTOP)
  await page.goto('/connectors')
  await openAuthModal(page)

  const modal = page.locator('[data-vc="modal-connector-auth"]')
  const d = await computed(modal, [
    'width',
    'border-top-width',
    'border-top-style',
    'border-top-color',
    'border-radius',
    'padding-top',
    'padding-right',
    'padding-bottom',
    'padding-left',
    'background-color',
  ])
  expect(d['width']).toBe('390px') // border-box outer (global box-sizing: border-box)
  expect(d['border-top-width']).toBe('1px')
  expect(d['border-top-style']).toBe('solid')
  expect(d['border-top-color']).toBe('rgb(42, 58, 85)') // borderInput
  expect(d['border-radius']).toBe('14px') // radiusLg
  expect(d['padding-top']).toBe('24px')
  expect(d['padding-right']).toBe('24px')
  expect(d['padding-bottom']).toBe('24px')
  expect(d['padding-left']).toBe('24px')
  expect(d['background-color']).toBe('rgb(18, 26, 40)') // panel

  // modal-overlay: fixed full-viewport scrim rgba(4,8,14,0.72).
  const overlay = page.locator('[data-vc="modal-overlay"]')
  const o = await computed(overlay, ['position', 'background-color'])
  expect(o['position']).toBe('fixed')
  expect(o['background-color']).toBe('rgba(4, 8, 14, 0.72)')

  // Mobile: fullscreen takeover — panel fills the viewport width, square corners,
  // no border, vertically scrollable.
  await page.setViewportSize(MOBILE)
  await page.goto('/connectors')
  await openAuthModal(page)

  const m = await computed(modal, ['width', 'border-radius', 'border-top-style', 'overflow-y'])
  expect(m['width']).toBe('390px') // fills the mobile viewport
  expect(m['border-radius']).toBe('0px')
  expect(m['border-top-style']).toBe('none')
  expect(m['overflow-y']).toBe('auto')
})
