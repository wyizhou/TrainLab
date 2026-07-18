import { expect, test } from '@playwright/test'

test('v3.5 activity list management covers rename, restore, download and delete', async ({
  page,
}) => {
  await page.goto('/activities')
  const rows = page.getByTestId('activity-row')
  const initialTotal = Number((await page.locator('.activities__count .num').textContent())?.trim())
  const firstAction = page.locator('[data-vc="activity-more-button"]').first()

  await firstAction.click()
  await page.getByRole('menuitem', { name: '重命名' }).click()
  await page.getByLabel('运动名称').fill('周六耐力跑')
  await page.getByRole('button', { name: '保存名称' }).click()
  await expect(page.getByText('周六耐力跑').first()).toBeVisible()
  await expect(firstAction).toBeFocused()

  await firstAction.click()
  await page.getByRole('menuitem', { name: '恢复解析标题' }).click()
  await page.getByRole('button', { name: '确认恢复' }).click()
  await expect(page.getByText('晨间轻松跑').first()).toBeVisible()

  await firstAction.click()
  await page.getByRole('menuitem', { name: '下载原始 FIT' }).click()
  await expect(page.getByText(/已开始下载.*模拟/)).toBeVisible()

  await firstAction.click()
  await page.getByRole('menuitem', { name: '删除运动' }).click()
  await page.getByRole('button', { name: '确认删除' }).click()
  await expect(page.locator('.activities__count .num')).toHaveText(String(initialTotal - 1))
  await expect(rows.first()).not.toContainText('晨间轻松跑')
  await expect(page.getByText('运动、导入记录和原始文件已删除')).toBeVisible()
})

test('v3.5 detail management and source capability stay truthful', async ({ page }) => {
  await page.goto('/activities/a0')
  const trigger = page.locator('[data-vc="activity-detail-more"]')
  await trigger.click()
  await page.getByRole('menuitem', { name: '重命名' }).click()
  await page.getByLabel('运动名称').fill('详情页新名称')
  await page.getByRole('button', { name: '保存名称' }).click()
  await expect(page.getByRole('heading', { name: '详情页新名称' })).toBeVisible()

  await trigger.click()
  await page.getByRole('menuitem', { name: '恢复解析标题' }).click()
  await page.getByRole('button', { name: '确认恢复' }).click()
  await expect(page.getByRole('heading', { name: '晨间轻松跑' })).toBeVisible()

  await trigger.click()
  await page.getByRole('menuitem', { name: '下载原始 FIT' }).click()
  await expect(page.getByText(/已开始下载.*模拟/)).toBeVisible()

  await page.goto('/activities/profile-cycling')
  await page.locator('[data-vc="activity-detail-more"]').click()
  await expect(page.getByRole('menuitem', { name: '原始 FIT 不可用' })).toBeDisabled()

  await page.goto('/activities/a0')
  await page.locator('[data-vc="activity-detail-more"]').click()
  await page.getByRole('menuitem', { name: '删除运动' }).click()
  await page.getByRole('button', { name: '确认删除' }).click()
  await expect(page).toHaveURL(/\/activities$/)
  await expect(page.getByText('运动、导入记录和原始文件已删除')).toBeVisible()
})

test('v3.5 import records expose seven states, cursor append and permission actions', async ({
  page,
}) => {
  await page.goto('/connectors')
  const records = page.getByTestId('import-record-row')
  await expect(records).toHaveCount(4)
  for (const label of ['处理完成', '部分完成', '等待处理', '处理中']) {
    await expect(page.getByText(label).first()).toBeVisible()
  }
  await page.getByRole('button', { name: '加载更多' }).click()
  await expect(records).toHaveCount(7)
  for (const label of ['处理失败', '正在删除', '删除未完成']) {
    await expect(page.getByText(label).first()).toBeVisible()
  }
  await expect(page.getByRole('button', { name: '重新处理' }).first()).toBeVisible()
  await expect(page.getByRole('button', { name: '继续删除' })).toBeVisible()
  await page.getByRole('button', { name: '重试删除' }).click()
  await expect(records).toHaveCount(6)
  await expect(page.getByText('导入记录已删除')).toBeVisible()
})

test('v3.5 storage snapshot and responsive dialogs cover authoritative widths', async ({
  page,
}) => {
  await page.goto('/settings')
  const storage = page.locator('[data-vc="settings-data-storage"]')
  await expect(storage).toContainText('3.20 GB')
  await expect(storage).toContainText('10.00 GB')
  await expect(storage).toContainText('186 / 500')
  await expect(page.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '32')

  for (const width of [390, 768, 1280, 1536]) {
    await page.setViewportSize({ width, height: width < 1000 ? 900 : 800 })
    await page.goto('/activities')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  }

  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/activities')
  const trigger = page.locator('[data-vc="activity-more-button"]').first()
  await trigger.focus()
  await trigger.press('Enter')
  const menu = page.locator('[data-vc="activity-actions-menu"]')
  const menuBox = await menu.boundingBox()
  expect(menuBox?.height).toBeLessThan(260)
  expect((menuBox?.y ?? 0) + (menuBox?.height ?? 0)).toBeLessThanOrEqual(844)
  await page.getByRole('menuitem', { name: '重命名' }).press('Enter')
  const dialog = page.locator('[data-vc="activity-management-dialog"]')
  const box = await dialog.boundingBox()
  expect(box?.width).toBe(390)
  expect(box?.height).toBe(844)
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(trigger).toBeFocused()
})
