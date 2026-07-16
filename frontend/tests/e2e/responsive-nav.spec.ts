import { test, expect, type Page } from '@playwright/test'

// Baseline viewports (contract G-resp): mobile 390 / tablet 768 / desktop 1280 / wide 1920.
const MOBILE = { width: 390, height: 844 }
const TABLET = { width: 768, height: 1024 }
const DESKTOP = { width: 1280, height: 800 }

const ROUTES = [
  { label: '分析', testid: 'page-analysis' },
  { label: '运动记录', testid: 'page-activities' },
  { label: '健康记录', testid: 'page-health' },
  { label: '连接器', testid: 'page-connectors' },
  { label: '设置', testid: 'page-settings' },
] as const

async function noHorizontalOverflow(page: Page): Promise<boolean> {
  return page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
}

// AC-001b-1
test('mobile hides the top nav and shows a fixed 60px bottom tab bar with 5 items', async ({
  page,
}) => {
  await page.setViewportSize(MOBILE)
  await page.goto('/')
  await expect(page.getByTestId('page-analysis')).toBeVisible()

  // Top nav must be absent from the DOM, not merely hidden.
  await expect(page.getByTestId('top-nav')).toHaveCount(0)
  await expect(page.getByRole('navigation', { name: '主导航' })).toHaveCount(1)

  const bar = page.getByTestId('bottom-tab-bar')
  await expect(bar).toBeVisible()
  const layout = await bar.evaluate((el) => {
    const s = getComputedStyle(el)
    return {
      position: s.position,
      bottom: s.bottom,
      height: s.height,
      children: el.children.length,
    }
  })
  expect(layout.position).toBe('fixed')
  expect(layout.bottom).toBe('0px')
  expect(layout.height).toBe('60px')
  expect(layout.children).toBe(5)
})

// AC-001b-2
test('tablet shows the top nav and hides the bottom tab bar and sync pill', async ({ page }) => {
  await page.setViewportSize(TABLET)
  await page.goto('/')
  await expect(page.getByTestId('top-nav')).toBeVisible()
  await expect(page.getByTestId('bottom-tab-bar')).toHaveCount(0)
  await expect(page.getByTestId('last-sync')).toHaveCount(0)
})

// AC-001b-3
test('desktop shows the last-sync pill', async ({ page }) => {
  await page.setViewportSize(DESKTOP)
  await page.goto('/')
  const pill = page.getByTestId('last-sync')
  await expect(pill).toBeVisible()
  await expect(pill).toHaveText(/^上次同步/)
})

// AC-001b-4
test('main content padding is graded per breakpoint', async ({ page }) => {
  const cases = [
    { vp: MOBILE, top: '14px', right: '12px', bottom: '76px', left: '12px' },
    { vp: TABLET, top: '18px', right: '16px', bottom: '18px', left: '16px' },
    { vp: DESKTOP, top: '22px', right: '24px', bottom: '22px', left: '24px' },
  ]
  for (const c of cases) {
    await page.setViewportSize(c.vp)
    await page.goto('/')
    const pad = await page.locator('main.app-main').evaluate((el) => {
      const s = getComputedStyle(el)
      return {
        top: s.paddingTop,
        right: s.paddingRight,
        bottom: s.paddingBottom,
        left: s.paddingLeft,
      }
    })
    expect(pad, `padding at ${c.vp.width}px`).toEqual({
      top: c.top,
      right: c.right,
      bottom: c.bottom,
      left: c.left,
    })
  }
})

// AC-001b-5
test('all five routes are reachable in each nav mode, default lands analysis, no overflow', async ({
  page,
}) => {
  // Desktop: navigate via the top nav.
  await page.setViewportSize(DESKTOP)
  await page.goto('/')
  await expect(page.getByTestId('page-analysis')).toBeVisible()
  const topNav = page.getByRole('navigation', { name: '主导航' })
  for (const route of ROUTES) {
    await topNav.getByRole('link', { name: route.label, exact: true }).click()
    await expect(page.getByTestId(route.testid)).toBeVisible()
    expect(await noHorizontalOverflow(page), `desktop overflow on ${route.testid}`).toBe(true)
  }

  // Mobile: navigate via the bottom tab bar.
  await page.setViewportSize(MOBILE)
  await page.goto('/')
  await expect(page.getByTestId('page-analysis')).toBeVisible()
  const bottomBar = page.getByTestId('bottom-tab-bar')
  for (const route of ROUTES) {
    await bottomBar.getByRole('link', { name: route.label, exact: true }).click()
    await expect(page.getByTestId(route.testid)).toBeVisible()
    expect(await noHorizontalOverflow(page), `mobile overflow on ${route.testid}`).toBe(true)
  }
})
