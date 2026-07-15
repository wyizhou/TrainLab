import { test, expect, type Locator } from '@playwright/test'

// Baseline viewport (contract G-resp): desktop 1280. Both AC-008c anchors are
// desktop-only.
const DESKTOP = { width: 1280, height: 800 }

// The real FIT-backed 晨间轻松跑 detail. Contract paths say /activities/1 (the
// first / real-FIT activity); its route id is a0 (see activity-detail.spec.ts).
const FIT_DETAIL_URL = '/activities/a0'

// Read individual computed longhands (shorthand serialization is unstable — 验法细则).
async function computed(locator: Locator, props: string[]): Promise<Record<string, string>> {
  return locator.evaluate((el, keys) => {
    const s = getComputedStyle(el)
    const out: Record<string, string> = {}
    for (const k of keys) out[k] = s.getPropertyValue(k)
    return out
  }, props)
}

// ── C-8 AC-008c-1: metric-card visual contract + grid auto-fit. Desktop anchor. ─
test('AC-008c-1: metric-card visual contract + grid auto-fit ≥130px (desktop)', async ({
  page,
}) => {
  await page.setViewportSize(DESKTOP)
  await page.goto(FIT_DETAIL_URL)
  await expect(page.getByTestId('page-activity-detail')).toBeVisible()

  const card = page.locator('[data-vc="metric-card"]').first()
  await expect(card).toBeVisible()

  // panel bg · borderPanel border · radiusCardSm 10 · padMetric 14.
  const c = await computed(card, [
    'background-color',
    'border-top-width',
    'border-top-style',
    'border-top-color',
    'border-radius',
    'padding-top',
    'padding-right',
    'padding-bottom',
    'padding-left',
  ])
  expect(c['background-color']).toBe('rgb(18, 26, 40)') // panel
  expect(c['border-top-width']).toBe('1px')
  expect(c['border-top-style']).toBe('solid')
  expect(c['border-top-color']).toBe('rgb(34, 48, 73)') // borderPanel
  expect(c['border-radius']).toBe('10px') // radiusCardSm
  expect(c['padding-top']).toBe('14px') // padMetric
  expect(c['padding-right']).toBe('14px')
  expect(c['padding-bottom']).toBe('14px')
  expect(c['padding-left']).toBe('14px')

  // Grid intent repeat(auto-fit,minmax(130px,1fr)): auto-fit collapses empty
  // tracks to 0px, so judge by filled-track geometry — every non-zero column ≥
  // the 130px minmax floor, and at least two columns actually fill (验法细则).
  const grid = await computed(page.locator('.activity-detail__metrics'), [
    'display',
    'grid-template-columns',
  ])
  expect(grid['display']).toBe('grid')
  const tracks = grid['grid-template-columns']
    .split(' ')
    .map((t) => parseFloat(t))
    .filter((px) => px > 0)
  expect(tracks.length).toBeGreaterThanOrEqual(2)
  for (const px of tracks) expect(px).toBeGreaterThanOrEqual(130)
})

// ── C-8 AC-008c-2: five row bars, each 16/4 and coloured Z1–Z5. ───────────
test('AC-008c-2: five hr-zone bars are 16/4 with Z1–Z5 colours (desktop)', async ({ page }) => {
  await page.setViewportSize(DESKTOP)
  await page.goto(FIT_DETAIL_URL)
  await expect(page.getByTestId('page-activity-detail')).toBeVisible()

  const bar = page.locator('[data-vc="hr-zone-bar"]')
  await expect(bar).toHaveCount(5)

  const b = await computed(bar.first(), ['height', 'border-radius'])
  expect(b['height']).toBe('16px') // padZoneTrackH
  expect(b['border-radius']).toBe('4px') // radiusZone

  // Five bars in DOM order = Z1..Z5, each in its zone colour.
  const expected = [
    'rgb(92, 104, 126)', // Z1 textFaint
    'rgb(66, 146, 224)', // Z2 accent
    'rgb(63, 191, 143)', // Z3 success
    'rgb(224, 160, 64)', // Z4 warn
    'rgb(224, 96, 96)', // Z5 danger
  ]
  for (let i = 0; i < expected.length; i++) {
    const seg = await computed(bar.nth(i), ['background-color'])
    expect(seg['background-color']).toBe(expected[i])
  }
})
