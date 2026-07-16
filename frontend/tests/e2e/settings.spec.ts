import { test, expect } from '@playwright/test'

// Baseline viewports (contract G-resp): mobile 390 / tablet 768 / desktop 1280.
const MOBILE = { width: 390, height: 844 }
const TABLET = { width: 768, height: 1024 }
const DESKTOP = { width: 1280, height: 800 }

// The rev 1 数据保留策略 group is deleted (C-14 返工 design_rev 2).
const RETENTION_TEXT = ['数据保留策略', '到期自动清理', '保留期限']

// AC-014b-1: no 数据保留策略 copy or expiry-cleanup control at any breakpoint.
test('settings: no retention copy or cleanup control on mobile or desktop', async ({ page }) => {
  for (const vp of [MOBILE, DESKTOP]) {
    await page.setViewportSize(vp)
    await page.goto('/settings')
    await expect(page.getByTestId('page-settings')).toBeVisible()

    for (const text of RETENTION_TEXT) {
      await expect(page.getByText(text), `"${text}" absent at ${vp.width}px`).toHaveCount(0)
    }
    // The rev 1 group and its 到期自动清理 checkbox are gone from the DOM.
    await expect(page.getByTestId('settings-retention')).toHaveCount(0)
    await expect(page.getByRole('checkbox')).toHaveCount(0)
  }
})

// AC-014b-2: 心率区间输入 grid is 2×2 on mobile, 4 tracks on tablet/desktop.
test('settings: 心率区间输入 grid is 2 tracks on mobile, 4 on tablet/desktop', async ({ page }) => {
  const grid = () => page.locator('[data-testid="settings-zones"] .settings__grid')
  const trackCount = () =>
    grid().evaluate(
      (el) => getComputedStyle(el).gridTemplateColumns.split(' ').filter(Boolean).length,
    )

  // Mobile: 2 columns — first two inputs share a top edge, the 3rd wraps below.
  await page.setViewportSize(MOBILE)
  await page.goto('/settings')
  await expect(page.getByTestId('page-settings')).toBeVisible()
  expect(await trackCount(), 'mobile grid is 2 tracks').toBe(2)

  const fields = grid().locator('.settings__field')
  const box0 = await fields.nth(0).boundingBox()
  const box1 = await fields.nth(1).boundingBox()
  const box2 = await fields.nth(2).boundingBox()
  expect(box0, 'field 0 rendered').not.toBeNull()
  expect(box1, 'field 1 rendered').not.toBeNull()
  expect(box2, 'field 2 rendered').not.toBeNull()
  expect(Math.abs(box0!.y - box1!.y), 'first two inputs share a top edge').toBeLessThanOrEqual(1)
  expect(box2!.y, '3rd input wraps to the next row').toBeGreaterThan(box0!.y)

  // Tablet and desktop: 4 tracks.
  for (const vp of [TABLET, DESKTOP]) {
    await page.setViewportSize(vp)
    await page.goto('/settings')
    await expect(page.getByTestId('page-settings')).toBeVisible()
    expect(await trackCount(), `${vp.width}px grid is 4 tracks`).toBe(4)
  }
})

// AC-014c-1: settings-page max-width 760 centered; settings-group pixel-contract
// (bg / border / radius / padding) and four groups single-column stacked (desktop).
test('settings: page 760 centered + group pixel-contract on desktop', async ({ page }) => {
  await page.setViewportSize(DESKTOP)
  await page.goto('/settings')

  const pageEl = page.locator('[data-vc="settings-page"]')
  await expect(pageEl).toBeVisible()
  const pageStyle = await pageEl.evaluate((el) => {
    const s = getComputedStyle(el)
    return { maxWidth: s.maxWidth, ml: s.marginLeft, mr: s.marginRight }
  })
  expect(pageStyle.maxWidth, 'settings-page max-width').toBe('760px')
  expect(
    Math.abs(parseFloat(pageStyle.ml) - parseFloat(pageStyle.mr)),
    'settings-page left/right margins equal (centered)',
  ).toBeLessThanOrEqual(1)

  const groups = page.locator('[data-vc="settings-group"]')
  await expect(groups).toHaveCount(4)

  // Group pixel-contract via longhands (简写序列化不稳定, 契约验法细则).
  const g0 = await groups.first().evaluate((el) => {
    const s = getComputedStyle(el)
    return {
      bg: s.backgroundColor,
      bw: s.borderTopWidth,
      bs: s.borderTopStyle,
      bc: s.borderTopColor,
      radius: s.borderTopLeftRadius,
      pad: [s.paddingTop, s.paddingRight, s.paddingBottom, s.paddingLeft],
    }
  })
  expect(g0.bg, 'group bg').toBe('rgb(255, 255, 255)')
  expect(g0.bw, 'group border width').toBe('1px')
  expect(g0.bs, 'group border style').toBe('solid')
  expect(g0.bc, 'group border color').toBe('rgb(203, 213, 225)')
  expect(g0.radius, 'group radius').toBe('12px')
  expect(g0.pad, 'group padding 22 all sides').toEqual(['22px', '22px', '22px', '22px'])

  // Four groups single-column stacked: each spans 760, top increases, left constant.
  const boxes = []
  for (let i = 0; i < 4; i++) boxes.push(await groups.nth(i).boundingBox())
  for (const b of boxes) expect(b).not.toBeNull()
  for (let i = 0; i < 4; i++) {
    expect(Math.abs(boxes[i]!.width - 760), `group ${i} spans 760`).toBeLessThanOrEqual(1)
  }
  for (let i = 1; i < 4; i++) {
    expect(boxes[i]!.y, `group ${i} top increases`).toBeGreaterThan(boxes[i - 1]!.y)
    expect(Math.abs(boxes[i]!.x - boxes[0]!.x), `group ${i} left constant`).toBeLessThanOrEqual(1)
  }
})

// AC-014c-2: account-grid auto-fit resolves 2 cols desktop / 1 col mobile (filled
// geometry); zone-grid explicit repeat resolves 4 tracks desktop / 2 mobile.
test('settings: account-grid 2/1 cols and zone-grid 4/2 tracks across breakpoints', async ({
  page,
}) => {
  const zoneTracks = () =>
    page
      .locator('[data-vc="settings-zone-grid"]')
      .evaluate((el) => getComputedStyle(el).gridTemplateColumns.split(' ').filter(Boolean).length)
  // auto-fit collapses empty tracks to 0px, so count filled columns = children
  // sharing the top-most row's offsetTop (contract 验法细则: 已填充列几何).
  const accountCols = () =>
    page.locator('[data-vc="settings-account-grid"]').evaluate((el) => {
      const kids = Array.from(el.children) as HTMLElement[]
      const minTop = Math.min(...kids.map((c) => c.offsetTop))
      return kids.filter((c) => c.offsetTop === minTop).length
    })

  await page.setViewportSize(DESKTOP)
  await page.goto('/settings')
  await expect(page.getByTestId('page-settings')).toBeVisible()
  expect(await accountCols(), 'desktop account-grid 2 cols').toBe(2)
  expect(await zoneTracks(), 'desktop zone-grid 4 tracks').toBe(4)

  await page.setViewportSize(MOBILE)
  await page.goto('/settings')
  await expect(page.getByTestId('page-settings')).toBeVisible()
  expect(await accountCols(), 'mobile account-grid 1 col').toBe(1)
  expect(await zoneTracks(), 'mobile zone-grid 2 tracks').toBe(2)
})
