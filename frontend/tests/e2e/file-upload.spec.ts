import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

// Baseline mobile viewport (contract G-resp): 390 wide.
const MOBILE = { width: 390, height: 844 }

// A real FIT so the 已解析文件 list renders a data row to measure (same fixture
// the FileUpload unit test parses).
const FIT_FIXTURE = fileURLToPath(new URL('../fixtures/614797758_ACTIVITY.fit', import.meta.url))

test('file upload: DataTransfer drop ingests multiple files and restores the dropzone', async ({
  page,
}) => {
  await page.goto('/connectors')
  const zone = page.getByTestId('file-upload-dropzone')
  const fitBase64 = readFileSync(FIT_FIXTURE).toString('base64')
  const dataTransfer = await page.evaluateHandle(
    ({ encodedFit }) => {
      const transfer = new DataTransfer()
      const fitBytes = Uint8Array.from(atob(encodedFit), (character) => character.charCodeAt(0))
      transfer.items.add(new File([fitBytes], 'dropped-run.fit'))
      transfer.items.add(
        new File(
          [
            '<gpx><trk><name>Dropped route</name><trkseg><trkpt lat="30" lon="104"><time>2026-01-01T00:00:00Z</time></trkpt><trkpt lat="30.001" lon="104.001"><time>2026-01-01T00:01:00Z</time></trkpt></trkseg></trk></gpx>',
          ],
          'dropped-route.gpx',
        ),
      )
      return transfer
    },
    { encodedFit: fitBase64 },
  )

  await zone.dispatchEvent('dragenter', { dataTransfer })
  await expect(zone).toHaveAttribute('data-drag-active', 'true')
  await zone.dispatchEvent('dragover', { dataTransfer })
  await zone.dispatchEvent('drop', { dataTransfer })

  await expect(page.getByTestId('parsed-file')).toHaveCount(2)
  await expect(page.getByText('dropped-run.fit')).toBeVisible()
  await expect(page.getByText('dropped-route.gpx')).toBeVisible()
  await expect(zone).toHaveAttribute('data-drag-active', 'false')
  expect(new URL(page.url()).pathname).toBe('/connectors')
})

// AC-013b-1 (C-13): on mobile the 文件上传 area and the 已解析文件 list stack into a
// single column and the page does not overflow horizontally.
test('file upload: single-column stack, no horizontal overflow on mobile', async ({ page }) => {
  await page.setViewportSize(MOBILE)
  await page.goto('/connectors')

  // Import a FIT so a parsed row exists to inspect the list layout.
  await page.getByTestId('file-upload-input').setInputFiles(FIT_FIXTURE)
  const row = page.getByTestId('parsed-file').first()
  await expect(row).toBeVisible()

  // v3.2 keeps each parsed entry as a compact flex row; the filename may shrink
  // and ellipsize while metadata remains visible.
  expect(await row.evaluate((el) => getComputedStyle(el).display)).toBe('flex')
  await expect(row.locator('.file-upload__name')).toBeVisible()
  await expect(row.locator('.file-upload__meta')).toHaveCount(2)
  await expect(row.locator('.file-upload__stored')).toBeVisible()

  // The upload zone and parsed list stack as two rows at the mobile breakpoint.
  const grid = page.locator('[data-vc="upload-grid"]')
  const children = grid.locator(':scope > *')
  const first = await children.nth(0).boundingBox()
  const second = await children.nth(1).boundingBox()
  expect(first).not.toBeNull()
  expect(second).not.toBeNull()
  expect(second!.y).toBeGreaterThan(first!.y)

  // No horizontal overflow at 390px.
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth)
  expect(scrollWidth, 'page does not overflow 390px').toBeLessThanOrEqual(390)
})
