import { expect, test } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const username = process.env.TRAINLAB_E2E_USERNAME ?? 'useradmin'
const password = process.env.TRAINLAB_E2E_PASSWORD ?? 'useradmin'
const peerUsername = process.env.TRAINLAB_E2E_PEER_USERNAME ?? 'peer-user'
const peerPassword = process.env.TRAINLAB_E2E_PEER_PASSWORD ?? 'correct-password'
const fullstackOrigin = process.env.TRAINLAB_FULLSTACK_URL ?? 'http://localhost:8000'
const fitPath = fileURLToPath(new URL('../fixtures/614797758_ACTIVITY.fit', import.meta.url))

async function login(
  page: import('@playwright/test').Page,
  loginUsername = username,
  loginPassword = password,
) {
  await page.goto('/activities')
  await expect(page).toHaveURL(/\/login$/)
  const code = (await page.getByTestId('captcha-code').textContent())?.trim() ?? ''
  await page.getByLabel('用户名').fill(loginUsername)
  await page.getByLabel('密码').fill(loginPassword)
  await page.getByLabel('验证码', { exact: true }).fill(code)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).toHaveURL(/\/activities$/)
}

test('unauthenticated activity APIs reject private data access', async ({ request }) => {
  const listing = await request.get('/api/v1/activities')
  expect(listing.status()).toBe(401)

  const upload = await request.post('/api/v1/imports/fit', {
    headers: { Origin: fullstackOrigin },
    multipart: {
      file: {
        name: 'unauthenticated.fit',
        mimeType: 'application/vnd.ant.fit',
        buffer: await readFile(fitPath),
      },
    },
  })
  expect(upload.status()).toBe(401)
})

test('login, upload FIT, reload, open v3.4 detail, download source, and logout', async ({
  page,
}) => {
  await login(page)
  await page.goto('/connectors')
  await page.getByTestId('file-upload-input').setInputFiles(fitPath)
  const importedFile = page.getByTestId('parsed-file').filter({ hasText: '614797758_ACTIVITY.fit' })
  await expect(importedFile).toBeVisible()
  await expect(importedFile.getByTestId('parsed-stored')).toHaveText('已入库')

  await page.goto('/activities')
  const importedRow = page
    .getByTestId('activity-row')
    .filter({ hasText: 'Run' })
    .filter({ hasText: 'FIT上传' })
    .first()
  await expect(importedRow).toBeVisible()

  await page.reload()
  await expect(importedRow).toBeVisible()
  await importedRow.click()
  await expect(page).toHaveURL(
    /\/activities\/[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
  )
  await expect(page.getByTestId('page-activity-detail')).toBeVisible()
  await expect(page.getByText('此页面来自登录用户私有 FIT 文件')).toBeVisible()
  const ownerActivityId = new URL(page.url()).pathname.split('/').at(-1)
  expect(ownerActivityId).toMatch(/^[0-9a-f-]{36}$/i)

  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: '下载原始 FIT' }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toBe('614797758_ACTIVITY.fit')

  const ownerDetailUrl = page.url()
  await page.goto('/activities')
  await page.getByRole('button', { name: '退出' }).click()
  await expect(page).toHaveURL(/\/login$/)
  await page.goto(ownerDetailUrl)
  await expect(page).toHaveURL(/\/login$/)

  await login(page, peerUsername, peerPassword)
  const ownerDetailAsPeer = await page
    .context()
    .request.get(`/api/v1/activities/${ownerActivityId}`)
  expect(ownerDetailAsPeer.status()).toBe(404)
  expect((await ownerDetailAsPeer.json()).code).toBe('activity_not_found')
  const ownerSourceAsPeer = await page
    .context()
    .request.get(`/api/v1/activities/${ownerActivityId}/source`)
  expect(ownerSourceAsPeer.status()).toBe(404)
  expect((await ownerSourceAsPeer.json()).code).toBe('activity_not_found')
  expect(ownerSourceAsPeer.headers()['content-type']).toContain('application/json')
})
