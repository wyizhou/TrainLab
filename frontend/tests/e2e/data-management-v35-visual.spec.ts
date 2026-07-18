import { expect, test } from '@playwright/test'

const VIEWPORTS = [
  { width: 390, height: 844 },
  { width: 768, height: 1024 },
  { width: 1280, height: 800 },
  { width: 1536, height: 900 },
]

for (const viewport of VIEWPORTS) {
  test(`${viewport.width}px data management visual baseline`, async ({ page }) => {
    await page.setViewportSize(viewport)

    await page.goto('/activities')
    await expect(page.getByTestId('page-activities')).toBeVisible()
    await expect(page).toHaveScreenshot(`${viewport.width}-activities-management.png`, {
      fullPage: true,
      animations: 'disabled',
    })

    await page.locator('[data-vc="activity-more-button"]').first().click()
    await page.getByRole('menuitem', { name: '重命名' }).click()
    await expect(page).toHaveScreenshot(`${viewport.width}-activity-dialog.png`, {
      animations: 'disabled',
    })

    await page.goto('/connectors')
    const imports = page.locator('[data-vc="import-records"]')
    await expect(imports).toBeVisible()
    await page.getByRole('button', { name: '加载更多' }).click()
    await page.setViewportSize({ width: viewport.width, height: 2200 })
    const chromeStyle = await page.addStyleTag({
      content: '.top-nav,.bottom-tab-bar{display:none!important}',
    })
    await imports.scrollIntoViewIfNeeded()
    await expect(imports).toHaveScreenshot(`${viewport.width}-import-records.png`, {
      animations: 'disabled',
    })
    await chromeStyle.evaluate((element) => element.parentNode?.removeChild(element))
    await page.setViewportSize(viewport)

    await page.goto('/settings')
    await expect(page.locator('[data-vc="settings-data-storage"]')).toBeVisible()
    await expect(page).toHaveScreenshot(`${viewport.width}-storage-settings.png`, {
      fullPage: true,
      animations: 'disabled',
    })

    await page.goto('/activities/a0')
    await page.locator('[data-vc="activity-detail-more"]').click()
    await expect(page).toHaveScreenshot(`${viewport.width}-activity-detail-menu.png`, {
      animations: 'disabled',
    })
  })
}
