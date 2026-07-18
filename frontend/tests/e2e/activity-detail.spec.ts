import { expect, test, type Page } from '@playwright/test'

const VIEWPORTS = [
  { width: 390, height: 844 },
  { width: 768, height: 1024 },
  { width: 1280, height: 800 },
  { width: 1536, height: 900 },
]

const PROFILES = [
  ['a0', 'run'],
  ['profile-hike', 'hike'],
  ['profile-strength', 'strength'],
  ['profile-lead', 'lead'],
  ['profile-boulder', 'boulder'],
  ['profile-cycling', 'cycling'],
  ['profile-generic', 'generic'],
] as const

async function openProfile(page: Page, id: string, profile: string) {
  await page.goto(`/activities/${id}`)
  const detail = page.getByTestId('activity-detail')
  await expect(detail).toBeVisible()
  await expect(detail).toHaveAttribute('data-profile', profile)
  return detail
}

test('all seven profiles use the shared five-tab detail contract', async ({ page }) => {
  for (const [id, profile] of PROFILES) {
    const detail = await openProfile(page, id, profile)
    await expect(detail.locator('[data-vc="activity-detail-tab"]')).toHaveCount(5)
    await expect(detail.locator('[data-vc="activity-summary-metric"]')).toHaveCount(6)
    await expect(page.locator('header [data-vc="activity-detail-tab"]')).toHaveCount(0)
  }
})

test('segments, charts, devices and raw records keep their linked interactions', async ({
  page,
}) => {
  await openProfile(page, 'a0', 'run')

  await page.getByRole('button', { name: '分段 / 训练组' }).click()
  const segment = page.locator('[data-vc="activity-lap-row"]').first()
  await expect(segment).toBeVisible()
  await segment.click()
  await expect(page.getByTestId('detail-panel-charts')).toBeVisible()
  await expect(page.locator('.ts-chart__selection')).toHaveCount(1)

  const chart = page.getByTestId('ts-chart')
  const box = await chart.boundingBox()
  expect(box).not.toBeNull()
  await page.mouse.move(box!.x + box!.width * 0.55, box!.y + box!.height * 0.55)
  await expect(page.getByTestId('chart-crosshair')).toHaveCount(1)
  await expect(page.getByTestId('chart-tooltip')).toContainText('bpm')

  await page.getByRole('button', { name: '设备与指标' }).click()
  await expect(page.getByRole('button', { name: /跑步动态/ })).toHaveAttribute(
    'aria-expanded',
    'true',
  )
  await page.getByRole('button', { name: '传感器' }).click()
  await expect(page.locator('[data-vc="activity-device-card"]')).toHaveCount(1)

  await page.getByRole('button', { name: '原始数据' }).click()
  await expect(page.locator('.detail-raw-table tbody tr')).toHaveCount(10)
  await expect(page.getByTestId('raw-page-info')).toContainText('1 /')
  await page.getByRole('button', { name: '加载长数据' }).click()
  await expect(page.getByText('正在分批载入，概览仍可使用…')).toBeVisible()
  await expect(page.getByText('可用记录已载入；表格仍按 10 条分页。')).toBeVisible()
  await page.getByRole('button', { name: '重试解析' }).click()
  await expect(page.getByText('正在重新读取 FIT 消息定义…')).toBeVisible()
  await expect(page.getByText('重试完成；未映射字段继续标记为来源未明确。')).toBeVisible()
})

for (const viewport of VIEWPORTS) {
  test(`${viewport.width}px: responsive chart ticks and document geometry`, async ({ page }) => {
    await page.setViewportSize(viewport)
    await openProfile(page, 'a0', 'run')

    const chart = page.getByTestId('ts-chart')
    const width = await chart.evaluate((element) => element.getBoundingClientRect().width)
    const expectedTicks = Math.max(4, Math.min(12, Math.floor(width / 82)))
    await expect(chart.getByTestId('ts-xtick')).toHaveCount(expectedTicks)
    await expect(chart.getByTestId('ts-ytick')).toHaveCount(3)

    const geometry = await page.evaluate(() => ({
      viewport: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
      detailWidth: document.querySelector('[data-vc="activity-detail"]')!.getBoundingClientRect()
        .width,
    }))
    expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.viewport)
    expect(geometry.detailWidth).toBeLessThanOrEqual(1240)

    if (viewport.width === 390) {
      await page.getByRole('button', { name: '原始数据' }).click()
      await expect(page.locator('.detail-raw-table')).toBeHidden()
      await expect(page.locator('.detail-raw-cards article')).toHaveCount(10)
      await expect(page.locator('.detail-raw-cards article').first()).toBeVisible()
    }
  })
}

test('profiles without bound FIT data explain absence instead of fabricating rows', async ({
  page,
}) => {
  await openProfile(page, 'profile-generic', 'generic')
  await page.locator('[data-vc="activity-detail-more"]').click()
  await expect(page.getByRole('menuitem', { name: '原始 FIT 不可用' })).toBeDisabled()
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: '分段 / 训练组' }).click()
  await expect(page.getByText('当前没有可验证的分段数据')).toBeVisible()
  await page.getByRole('button', { name: '原始数据' }).click()
  await expect(page.getByText('等待真实 FIT 数据')).toBeVisible()
  await expect(page.locator('.detail-raw-table tbody tr')).toHaveCount(0)
})
