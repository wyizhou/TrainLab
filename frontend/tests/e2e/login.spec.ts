import { test, expect } from '@playwright/test'

// Gate smoke #1 (C-2): wrong captcha is rejected, then a correct login lands on
// the analysis page.
test('rejects a wrong captcha, then logs in and lands on the analysis page', async ({ page }) => {
  await page.goto('/login')

  await page.getByLabel('用户名').fill('alice123')
  await page.getByLabel('密码').fill('secret1')

  // The displayed code is always 1000-9999, so 0000 is guaranteed wrong.
  const code = (await page.getByTestId('captcha-code').textContent())?.trim() ?? ''
  await page.getByLabel('验证码', { exact: true }).fill('0000')
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page).toHaveURL(/\/login$/)

  await page.getByLabel('验证码', { exact: true }).fill(code)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page.getByTestId('page-analysis')).toBeVisible()
})

// AC-002b-1 (C-2): on mobile the login card is narrowed by its outer padding
// (390 − 24×2 = 342) and the page has no horizontal overflow. Rev 1 shipped the
// same geometry but was only ever run at desktop widths; this locks it at 390.
test('mobile login card is 342px wide with no horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/login')

  const card = page.locator('.login__card')
  await expect(card).toBeVisible()
  expect(await card.evaluate((el) => (el as HTMLElement).offsetWidth)).toBe(342)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
})
