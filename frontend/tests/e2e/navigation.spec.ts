import { test, expect } from '@playwright/test'

const ROUTES = [
  { label: '分析', testid: 'page-analysis' },
  { label: '运动记录', testid: 'page-activities' },
  { label: '健康记录', testid: 'page-health' },
  { label: '连接器', testid: 'page-connectors' },
  { label: '设置', testid: 'page-settings' },
] as const

test('lands on the analysis page by default', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByTestId('page-analysis')).toBeVisible()
})

test('navigates to all five routes from the top nav', async ({ page }) => {
  await page.goto('/')
  const nav = page.getByRole('navigation', { name: '主导航' })
  for (const route of ROUTES) {
    await nav.getByRole('link', { name: route.label, exact: true }).click()
    await expect(page.getByTestId(route.testid)).toBeVisible()
  }
})
