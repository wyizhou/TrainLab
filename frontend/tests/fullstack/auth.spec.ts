import { expect, test } from '@playwright/test'

const username = process.env.TRAINLAB_E2E_USERNAME ?? 'owner-user'
const password = process.env.TRAINLAB_E2E_PASSWORD ?? 'correct-password'

async function fillCaptcha(page: import('@playwright/test').Page) {
  const code = (await page.getByTestId('captcha-code').textContent())?.trim() ?? ''
  await page.getByLabel('验证码', { exact: true }).fill(code)
}

test('server login persists across reload and logout revokes the old cookie', async ({
  page,
  context,
}) => {
  await page.goto('/activities')
  await expect(page).toHaveURL(/\/login$/)

  await page.getByLabel('用户名').fill(username)
  await page.getByLabel('密码').fill('wrong-password')
  await fillCaptcha(page)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page.getByRole('alert')).toContainText('账号或密码错误')

  await page.getByLabel('密码').fill(password)
  await fillCaptcha(page)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).toHaveURL(/\/activities$/)
  await expect(page.getByTestId('page-activities')).toBeVisible()

  await page.reload()
  await expect(page.getByTestId('page-activities')).toBeVisible()
  const oldSession = (await context.cookies()).find((cookie) => cookie.name === 'trainlab_session')
  expect(oldSession).toBeDefined()

  await page.getByRole('button', { name: '退出' }).click()
  await expect(page).toHaveURL(/\/login$/)
  if (oldSession) await context.addCookies([oldSession])
  await page.goto('/activities')
  await expect(page).toHaveURL(/\/login$/)
})
