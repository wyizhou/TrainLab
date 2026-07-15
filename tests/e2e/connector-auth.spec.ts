import { test, expect, type Page } from '@playwright/test'

// Baseline viewports (contract G-resp): mobile 390 / desktop 1280.
const MOBILE = { width: 390, height: 844 }
const DESKTOP = { width: 1280, height: 800 }

// Gate smoke #2 (C-11): the 2FA two-stage authorization flow runs until the
// connector is connected. 国际区 starts disconnected in the demo initial state.
test('connects a Garmin account through the 2FA two-stage flow', async ({ page }) => {
  await page.goto('/connectors')

  // Open the auth modal for the disconnected 国际区 card.
  const globalCard = page.getByTestId('connector-card').filter({ hasText: '佳明国际区' })
  await expect(globalCard.getByTestId('connector-pill')).toHaveText('未连接')
  await globalCard.getByTestId('connector-action').click()

  const modal = page.getByRole('dialog')
  await expect(modal).toBeVisible()

  // Stage 1: credentials + enable 2FA.
  await modal.getByLabel('账号').fill('alice')
  await modal.getByLabel('密码').fill('secret')
  await modal.getByLabel('启用了 2FA').check()
  await modal.getByTestId('auth-submit').click()

  // Stage 2: the 6-digit code area appears and the checkbox is locked.
  await expect(modal.getByLabel('6 位验证码')).toBeVisible()
  await expect(modal.getByLabel('启用了 2FA')).toBeDisabled()

  await modal.getByLabel('6 位验证码').fill('123456')
  await modal.getByTestId('auth-submit').click()

  // The modal closes and the card is now connected.
  await expect(modal).toBeHidden()
  await expect(globalCard.getByTestId('connector-pill')).toHaveText('已连接')
})

// Panel geometry: rendered width, its top-left corner radius, and the left/right
// gaps to the viewport edges (equal gaps ⇒ horizontally centered).
async function panelMetrics(page: Page) {
  return page.getByTestId('auth-modal').evaluate((el: HTMLElement) => {
    const style = getComputedStyle(el)
    const rect = el.getBoundingClientRect()
    return {
      offsetWidth: el.offsetWidth,
      borderRadius: style.borderTopLeftRadius,
      left: Math.round(rect.left),
      right: Math.round(window.innerWidth - rect.right),
    }
  })
}

// AC-011b-1 (C-11): the auth modal is fullscreen on mobile (panel fills the
// viewport width, square corners) and a centered fixed 390px card on desktop.
test('auth modal: fullscreen on mobile, centered 390px on desktop', async ({ page }) => {
  await page.setViewportSize(MOBILE)
  await page.goto('/connectors')

  // Precondition: open the 2FA auth modal (国际区 starts disconnected).
  const globalCard = page.getByTestId('connector-card').filter({ hasText: '佳明国际区' })
  await globalCard.getByTestId('connector-action').click()
  await expect(page.getByTestId('auth-modal')).toBeVisible()

  const mobile = await panelMetrics(page)
  expect(mobile.offsetWidth, 'panel fills the mobile viewport width').toBe(MOBILE.width)
  expect(mobile.borderRadius, 'square corners on mobile').toBe('0px')

  await page.setViewportSize(DESKTOP)
  const desktop = await panelMetrics(page)
  expect(desktop.offsetWidth, 'fixed 390px card on desktop').toBe(390)
  expect(desktop.borderRadius, 'rounded corners on desktop').toBe('14px')
  expect(
    Math.abs(desktop.left - desktop.right),
    'panel is horizontally centered on desktop',
  ).toBeLessThanOrEqual(2)
})
