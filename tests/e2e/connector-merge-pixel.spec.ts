import { test, expect, type Locator, type Page } from '@playwright/test'

// Baseline viewports (contract G-resp): mobile 390 / desktop 1280×800.
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

// Left/right gaps to the viewport edges (equal gaps ⇒ horizontally centered).
async function centering(locator: Locator): Promise<{ left: number; right: number }> {
  return locator.evaluate((el) => {
    const rect = el.getBoundingClientRect()
    return { left: Math.round(rect.left), right: Math.round(window.innerWidth - rect.right) }
  })
}

// Connect the disconnected 国际区 account (no 2FA) and open the merge modal.
async function openMergeModal(page: Page) {
  const globalCard = page.getByTestId('connector-card').filter({ hasText: '佳明 Connect 国际区' })
  await globalCard.getByTestId('connector-action').click()

  const authModal = page.getByTestId('auth-modal')
  await authModal.getByLabel('账号').fill('alice')
  await authModal.getByLabel('密码').fill('secret')
  await authModal.getByTestId('auth-submit').click()
  await expect(authModal).toBeHidden()

  await page.getByTestId('conflict-banner').getByTestId('conflict-resolve').click()
  await expect(page.locator('[data-vc="modal-conflict"]')).toBeVisible()
}

// ── C-12 AC-012c-1: modal-conflict desktop 620px 居中 vs mobile 全屏 + modal-overlay
//    scrim contract. Hard req: data-vc anchors mirror the component roots. ────────────
test('AC-012c-1: modal-conflict desktop centered 620 / mobile fullscreen + overlay scrim', async ({
  page,
}) => {
  // Desktop: centered fixed 620px card, radius/padding/max-height contract.
  await page.setViewportSize(DESKTOP)
  await page.goto('/connectors')
  await openMergeModal(page)

  const modal = page.locator('[data-vc="modal-conflict"]')
  const d = await computed(modal, [
    'width',
    'border-radius',
    'padding-top',
    'padding-right',
    'padding-bottom',
    'padding-left',
    'max-height',
  ])
  expect(d['width']).toBe('620px') // border-box outer (global box-sizing: border-box)
  expect(d['border-radius']).toBe('14px') // radiusLg
  expect(d['padding-top']).toBe('24px')
  expect(d['padding-right']).toBe('24px')
  expect(d['padding-bottom']).toBe('24px')
  expect(d['padding-left']).toBe('24px')
  // max-height = round(0.86 × innerHeight) — desktop 800 → 688px, ±1px (亚像素舍入).
  expect(Math.abs(parseFloat(d['max-height']) - 688)).toBeLessThanOrEqual(1)

  const center = await centering(modal)
  const offset = Math.abs(center.left - center.right)
  expect(offset, 'panel is horizontally centered').toBeLessThanOrEqual(2)

  // modal-overlay: fixed full-viewport scrim rgba(4,8,14,0.72) (shared anchor with C-11).
  const overlay = page.locator('[data-vc="modal-overlay"]')
  const o = await computed(overlay, ['position', 'background-color'])
  expect(o['position']).toBe('fixed')
  expect(o['background-color']).toBe('rgba(4, 8, 14, 0.72)')

  // Mobile: fullscreen takeover — panel fills the viewport width, square corners,
  // vertically scrollable.
  await page.setViewportSize(MOBILE)
  await page.goto('/connectors')
  await openMergeModal(page)

  const m = await computed(modal, ['width', 'border-radius', 'overflow-y'])
  expect(m['width']).toBe('390px') // fills the mobile viewport
  expect(m['border-radius']).toBe('0px')
  expect(m['overflow-y']).toBe('auto')
})
