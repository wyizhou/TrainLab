import { expect, test } from '@playwright/test'

const VIEWPORTS = [
  { width: 390, height: 844 },
  { width: 768, height: 1024 },
  { width: 1280, height: 800 },
  { width: 1536, height: 900 },
]

for (const viewport of VIEWPORTS) {
  test(`${viewport.width}px: v3.4 detail container and panel order stay intact`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport)
    await page.goto('/activities/profile-hike')
    await expect(page.getByTestId('activity-detail')).toBeVisible()

    const facts = await page.evaluate(() => {
      const detail = document.querySelector<HTMLElement>('[data-vc="activity-detail"]')!
      const header = document.querySelector<HTMLElement>('[data-vc="activity-detail-header"]')!
      const tabs = document.querySelector<HTMLElement>('[data-vc="activity-detail-tabs"]')!
      const overview = document.querySelector<HTMLElement>('[data-vc="activity-overview-panel"]')!
      const detailRect = detail.getBoundingClientRect()
      const shell = document.querySelector<HTMLElement>('.activity-detail-shell')!
      return {
        width: detailRect.width,
        left: detailRect.left,
        right: detailRect.right,
        viewport: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
        background: getComputedStyle(shell).backgroundColor,
        order: [header.offsetTop, tabs.offsetTop, overview.offsetTop],
      }
    })

    expect(facts.width).toBeLessThanOrEqual(1240)
    expect(facts.left).toBeGreaterThanOrEqual(0)
    expect(facts.right).toBeLessThanOrEqual(facts.viewport)
    expect(facts.scrollWidth).toBeLessThanOrEqual(facts.viewport)
    expect(facts.order[0]).toBeLessThan(facts.order[1])
    expect(facts.order[1]).toBeLessThan(facts.order[2])
    expect(facts.background).not.toBe('rgba(0, 0, 0, 0)')
  })
}

test('desktop uses two-column overview while mobile stacks it', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto('/activities/a0')
  const layout = page.locator('.detail-overview-layout')
  await expect(layout).toBeVisible()
  expect(
    (await layout.evaluate((el) => getComputedStyle(el).gridTemplateColumns)).split(' '),
  ).toHaveLength(2)

  await page.setViewportSize({ width: 390, height: 844 })
  expect(
    (await layout.evaluate((el) => getComputedStyle(el).gridTemplateColumns)).split(' '),
  ).toHaveLength(1)
})
