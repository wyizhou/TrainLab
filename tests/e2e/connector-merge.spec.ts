import { test, expect, type Page } from '@playwright/test'

// Baseline viewports (contract G-resp): mobile 390 / desktop 1280.
const MOBILE = { width: 390, height: 844 }
const DESKTOP = { width: 1280, height: 800 }

// Panel geometry: rendered width, its top-left corner radius, and the left/right
// gaps to the viewport edges (equal gaps ⇒ horizontally centered).
async function panelMetrics(page: Page) {
  return page.getByTestId('conflict-modal').evaluate((el: HTMLElement) => {
    const style = getComputedStyle(el)
    const rect = el.getBoundingClientRect()
    return {
      offsetWidth: el.offsetWidth,
      borderRadius: style.borderTopLeftRadius,
      overflowY: style.overflowY,
      left: Math.round(rect.left),
      right: Math.round(window.innerWidth - rect.right),
    }
  })
}

// Connect the disconnected 国际区 account (no 2FA) and open the merge modal.
async function openMergeModal(page: Page) {
  const globalCard = page.getByTestId('connector-card').filter({ hasText: '佳明国际区' })
  await globalCard.getByTestId('connector-action').click()

  const authModal = page.getByTestId('auth-modal')
  await authModal.getByLabel('账号').fill('alice')
  await authModal.getByLabel('密码').fill('secret')
  await authModal.getByTestId('auth-submit').click()
  await expect(authModal).toBeHidden()

  await page.getByTestId('conflict-banner').getByTestId('conflict-resolve').click()
  await expect(page.getByTestId('conflict-modal')).toBeVisible()
}

// AC-012b-1 (C-12): the merge modal is fullscreen on mobile (panel fills the
// viewport width, square corners, internal overflow-y scroll) and a centered
// fixed 620px card on desktop.
test('merge modal: fullscreen on mobile, centered 620px on desktop', async ({ page }) => {
  await page.setViewportSize(MOBILE)
  await page.goto('/connectors')
  await openMergeModal(page)

  const mobile = await panelMetrics(page)
  expect(mobile.offsetWidth, 'panel fills the mobile viewport width').toBe(MOBILE.width)
  expect(mobile.borderRadius, 'square corners on mobile').toBe('0px')
  expect(mobile.overflowY, 'panel scrolls internally on mobile').toBe('auto')

  await page.setViewportSize(DESKTOP)
  const desktop = await panelMetrics(page)
  expect(desktop.offsetWidth, 'fixed 620px card on desktop').toBe(620)
  expect(desktop.borderRadius, 'rounded corners on desktop').toBe('14px')
  expect(
    Math.abs(desktop.left - desktop.right),
    'panel is horizontally centered on desktop',
  ).toBeLessThanOrEqual(2)
})

// Gate smoke #3 (C-12): the double-account merge flow — connecting 国际区
// surfaces suspected duplicates, the user resolves each group, and the banner
// disappears after confirming the merge.
test('resolves the double-account merge conflict and dismisses the banner', async ({ page }) => {
  await page.goto('/connectors')

  // Connect the disconnected 国际区 account (no 2FA) to trigger reconciliation.
  const globalCard = page.getByTestId('connector-card').filter({ hasText: '佳明国际区' })
  await globalCard.getByTestId('connector-action').click()

  const authModal = page.getByTestId('auth-modal')
  await authModal.getByLabel('账号').fill('alice')
  await authModal.getByLabel('密码').fill('secret')
  await authModal.getByTestId('auth-submit').click()
  await expect(authModal).toBeHidden()
  await expect(globalCard.getByTestId('connector-pill')).toHaveText('已连接')

  // The banner reports the two suspected duplicate groups.
  const banner = page.getByTestId('conflict-banner')
  await expect(banner).toBeVisible()
  await expect(banner).toContainText('2 组疑似重复运动')

  // Open the resolution modal and choose one region per group.
  await banner.getByTestId('conflict-resolve').click()
  const modal = page.getByTestId('conflict-modal')
  await expect(modal).toBeVisible()

  const groups = modal.getByTestId('conflict-group')
  await expect(groups).toHaveCount(2)

  const confirm = modal.getByTestId('conflict-confirm')
  await expect(confirm).toBeDisabled()
  await groups.nth(0).getByTestId('conflict-choice-cn').check()
  await groups.nth(1).getByTestId('conflict-choice-global').check()
  await expect(confirm).toBeEnabled()
  await confirm.click()

  // Merge applied: the modal closes and the banner is gone.
  await expect(modal).toBeHidden()
  await expect(page.getByTestId('conflict-banner')).toBeHidden()
})
