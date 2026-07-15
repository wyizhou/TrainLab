import { test, expect } from '@playwright/test'

// Baseline mobile viewport (contract G-resp): 390 wide.
const MOBILE = { width: 390, height: 844 }

// A real FIT so the 已解析文件 list renders a data row to measure (same fixture
// the FileUpload unit test parses).
const FIT_FIXTURE = 'tests/fixtures/614797758_ACTIVITY.fit'

// AC-013b-1 (C-13): on mobile the 文件上传 area and the 已解析文件 list stack into a
// single column and the page does not overflow horizontally.
test('file upload: single-column stack, no horizontal overflow on mobile', async ({ page }) => {
  await page.setViewportSize(MOBILE)
  await page.goto('/connectors')

  // Import a FIT so a parsed row exists to inspect the list layout.
  await page.getByTestId('file-upload-input').setInputFiles(FIT_FIXTURE)
  const row = page.getByTestId('parsed-file').first()
  await expect(row).toBeVisible()

  // The parsed row collapses to a single grid track on mobile (vs the desktop
  // 4-column grid).
  const tracks = await row.evaluate(
    (el) => getComputedStyle(el).gridTemplateColumns.split(' ').filter(Boolean).length,
  )
  expect(tracks, 'parsed row is a single column on mobile').toBe(1)

  // Its 名称 and 大小 cells share a left edge and stack top-to-bottom.
  const nameBox = await row.locator('[data-label="名称"]').boundingBox()
  const sizeBox = await row.locator('[data-label="大小"]').boundingBox()
  expect(nameBox, '名称 cell rendered').not.toBeNull()
  expect(sizeBox, '大小 cell rendered').not.toBeNull()
  expect(Math.abs(nameBox!.x - sizeBox!.x), 'cells share a left edge').toBeLessThanOrEqual(1)
  expect(sizeBox!.y, '大小 stacks below 名称').toBeGreaterThan(nameBox!.y)

  // No horizontal overflow at 390px.
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth)
  expect(scrollWidth, 'page does not overflow 390px').toBeLessThanOrEqual(390)
})
