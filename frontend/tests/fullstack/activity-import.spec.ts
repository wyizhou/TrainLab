import { expect, test } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const username = process.env.TRAINLAB_E2E_USERNAME ?? 'useradmin'
const password = process.env.TRAINLAB_E2E_PASSWORD ?? 'useradmin'
const peerUsername = process.env.TRAINLAB_E2E_PEER_USERNAME ?? 'peer-user'
const peerPassword = process.env.TRAINLAB_E2E_PEER_PASSWORD ?? 'correct-password'
const fullstackOrigin = process.env.TRAINLAB_FULLSTACK_URL ?? 'http://localhost:8000'
const fitPath = fileURLToPath(new URL('../../../data/617273913_ACTIVITY.fit', import.meta.url))
const fitFileName = '617273913_ACTIVITY.fit'

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

test('real FIT data completes the v3.5 upload, management, isolation, and deletion lifecycle', async ({
  page,
}) => {
  await login(page)

  await page.goto('/settings')
  const initialStorage = page.getByTestId('settings-data-storage')
  await expect(initialStorage).toContainText('暂无服务器文件')
  await expect(initialStorage).toContainText('0 / 10000')
  const initialUsage = await page.context().request.get('/api/v1/storage/usage')
  expect(initialUsage.status()).toBe(200)
  expect(await initialUsage.json()).toMatchObject({ usedBytes: 0, fileCount: 0 })

  await page.goto('/connectors')
  const uploadResponsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/v1/imports/fit') && response.request().method() === 'POST',
  )
  await page.getByTestId('file-upload-input').setInputFiles(fitPath)
  const uploadResponse = await uploadResponsePromise
  expect([200, 201]).toContain(uploadResponse.status())
  const uploadResult = (await uploadResponse.json()) as {
    activity: { id: string; name: string; originalFileName: string }
  }
  const importedFile = page.getByTestId('parsed-file').filter({ hasText: fitFileName })
  await expect(importedFile).toBeVisible()
  await expect(importedFile.getByTestId('parsed-stored')).toHaveText('已入库')
  const importRecord = page.getByTestId('import-record-row').filter({ hasText: fitFileName })
  await expect(importRecord).toBeVisible()
  await expect(importRecord).toContainText(/处理完成|部分完成/)
  await expect(importRecord.getByRole('link', { name: '查看运动' })).toBeVisible()

  const storedUsage = await page.context().request.get('/api/v1/storage/usage')
  expect(storedUsage.status()).toBe(200)
  expect(await storedUsage.json()).toMatchObject({ usedBytes: 270427, fileCount: 1 })

  await page.goto('/settings')
  const populatedStorage = page.getByTestId('settings-data-storage')
  await expect(populatedStorage).toContainText('存储状态正常')
  await expect(populatedStorage).toContainText('1 / 10000')
  await expect(populatedStorage).not.toContainText('暂无服务器文件')

  await page.goto('/activities')
  const importedRow = page
    .getByTestId('activity-row')
    .filter({ hasText: uploadResult.activity.name })
    .filter({ hasText: 'FIT上传' })
    .first()
  await expect(importedRow).toBeVisible()

  await page.reload()
  await expect(importedRow).toBeVisible()
  await page.goto(`/activities/${uploadResult.activity.id}`)
  await expect(page).toHaveURL(
    /\/activities\/[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
  )
  await expect(page.getByTestId('page-activity-detail')).toBeVisible()
  await expect(page.getByText('此页面来自登录用户私有 FIT 文件')).toBeVisible()
  const ownerActivityId = new URL(page.url()).pathname.split('/').at(-1)
  expect(ownerActivityId).toMatch(/^[0-9a-f-]{36}$/i)

  const detailActions = page.locator('[data-vc="activity-detail-more"]')
  await detailActions.click()
  await page.getByRole('menuitem', { name: '重命名' }).click()
  await page.getByLabel('运动名称').fill('真实 FIT 验收运动')
  await page.getByRole('button', { name: '保存名称' }).click()
  await expect(page.getByRole('heading', { name: '真实 FIT 验收运动' })).toBeVisible()

  await detailActions.click()
  await page.getByRole('menuitem', { name: '恢复解析标题' }).click()
  await page.getByRole('button', { name: '确认恢复' }).click()
  await expect(page.getByRole('heading', { name: uploadResult.activity.name })).toBeVisible()

  const downloadPromise = page.waitForEvent('download')
  await detailActions.click()
  await page.getByRole('menuitem', { name: '下载原始 FIT' }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toBe(uploadResult.activity.originalFileName)

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

  await page.goto('/activities')
  await page.getByRole('button', { name: '退出' }).click()
  await expect(page).toHaveURL(/\/login$/)
  await login(page)
  await page.goto(ownerDetailUrl)
  await expect(page.getByRole('heading', { name: uploadResult.activity.name })).toBeVisible()

  await page.locator('[data-vc="activity-detail-more"]').click()
  await page.getByRole('menuitem', { name: '删除运动' }).click()
  await page.getByRole('button', { name: '确认删除' }).click()
  await expect(page).toHaveURL(/\/activities$/)
  await expect(page.getByText('运动、导入记录和原始文件已删除')).toBeVisible()
  await expect(
    page.getByTestId('activity-row').filter({ hasText: uploadResult.activity.name }),
  ).toHaveCount(0)

  const ownerDetailAfterDelete = await page
    .context()
    .request.get(`/api/v1/activities/${ownerActivityId}`)
  expect(ownerDetailAfterDelete.status()).toBe(404)
  expect((await ownerDetailAfterDelete.json()).code).toBe('activity_not_found')
  const ownerSourceAfterDelete = await page
    .context()
    .request.get(`/api/v1/activities/${ownerActivityId}/source`)
  expect(ownerSourceAfterDelete.status()).toBe(404)
  expect((await ownerSourceAfterDelete.json()).code).toBe('activity_not_found')

  await page.goto('/connectors')
  await expect(page.getByText('暂无 FIT 导入记录')).toBeVisible()

  await page.goto('/settings')
  const clearedStorage = page.getByTestId('settings-data-storage')
  await expect(clearedStorage).toContainText('暂无服务器文件')
  await expect(clearedStorage).toContainText('0 / 10000')
  const clearedUsage = await page.context().request.get('/api/v1/storage/usage')
  expect(clearedUsage.status()).toBe(200)
  expect(await clearedUsage.json()).toMatchObject({ usedBytes: 0, fileCount: 0 })
})
