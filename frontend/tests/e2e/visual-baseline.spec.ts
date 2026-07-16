import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { test, expect, type Page } from '@playwright/test'
import { SYSTEM_PROMPT } from '../../src/analysis/systemPrompt'

const GEOMETRY_BASELINE_ROOT = fileURLToPath(new URL('../visual-baselines/v3.2/', import.meta.url))
const VISUAL_BASELINE_ROOT = fileURLToPath(new URL('../visual-baselines/v3.3/', import.meta.url))
const BASELINE_PATH = join(GEOMETRY_BASELINE_ROOT, 'geometry.json')
const MANIFEST_PATH = join(VISUAL_BASELINE_ROOT, 'manifest.json')
const SCREENSHOT_DIR = join(VISUAL_BASELINE_ROOT, 'screenshots')

type ViewportName = 'mobile' | 'tablet' | 'desktop' | 'wide'
type Baseline = {
  design_rev: number
  audited_viewports: Record<ViewportName, { width: number; height: number }>
  screenshots: string[]
  anchor_inventory: { resolved_unique: number; resolved_names: string[] }
  coverage: { screenshot_states: number }
  equivalence: { before: string; after: string; equal: boolean }[]
  render_states: Record<
    string,
    {
      document: { bodyHeight: number; bodyWidth: number; scrollHeight: number; scrollWidth: number }
      anchors: Array<
        {
          vc: string | null
          rect: { x: number; y: number; width: number; height: number }
        } & Record<ComputedField, string>
      >
    }
  >
}

const COMPUTED_FIELDS = [
  'alignItems',
  'background',
  'border',
  'color',
  'display',
  'flexDirection',
  'fontSize',
  'fontWeight',
  'gap',
  'grid',
  'justifyContent',
  'lineHeight',
  'margin',
  'maxWidth',
  'minWidth',
  'opacity',
  'overflowX',
  'overflowY',
  'padding',
  'position',
  'radius',
  'zIndex',
] as const

type ComputedField = (typeof COMPUTED_FIELDS)[number]
type ComputedContract = Record<ComputedField, string> & {
  rect: { x: number; y: number; width: number; height: number }
}

type GeometryComparison = boolean | ReadonlySet<string>
type RectField = 'x' | 'y' | 'width' | 'height'

const APPROVED_SANS_FONTS = [
  'Helvetica Neue',
  'helvetica',
  'Segoe UI',
  'tahoma',
  'arial',
  'Liberation Sans',
  'PingFang SC',
  '苹方-简',
  'Hiragino Sans GB',
  'stxihei',
  '华文细黑',
  'Microsoft YaHei',
  '微软雅黑',
  'Noto Sans CJK SC',
  'Noto Sans SC',
  'Source Han Sans SC',
  'WenQuanYi Micro Hei',
  'sans-serif',
] as const

const APPROVED_MONO_FONTS = [
  'ui-monospace',
  'SFMono-Regular',
  'SF Mono',
  'menlo',
  'monaco',
  'consolas',
  'Liberation Mono',
  'Noto Sans Mono CJK SC',
  'PingFang SC',
  'Microsoft YaHei',
  'monospace',
] as const

// Text in these inline controls is intentionally rendered by the first
// available member of the approved platform stack. Glyph advance widths may
// change their intrinsic width and the x position of following siblings. Only
// those two fields use relational checks; y, height, styles, gaps, insets,
// right edges, wrapping, and every other anchor remain on the exact contract.
const FONT_INTRINSIC_HORIZONTAL_FIELDS: Readonly<Record<string, ReadonlySet<RectField>>> = {
  'top-nav': new Set(['width']),
  'top-nav-item': new Set(['x', 'width']),
  'top-nav-item-active': new Set(['x', 'width']),
  'sync-chip': new Set(['x', 'width']),
  'health-tab': new Set(['x', 'width']),
  'health-tab-selected': new Set(['x', 'width']),
  'scope-chip': new Set(['x', 'width']),
  'scope-chip-selected': new Set(['x', 'width']),
  'type-chip': new Set(['x', 'width']),
  'type-chip-selected': new Set(['x', 'width']),
  'activity-picker-trigger': new Set(['x', 'width']),
  'batch-download-button': new Set(['x', 'width']),
}

const FONT_FLOW_GROUPS = [
  ['top-nav-item', 'top-nav-item-active'],
  ['scope-chip', 'scope-chip-selected', 'activity-picker-trigger'],
  ['type-chip', 'type-chip-selected'],
  ['health-tab', 'health-tab-selected'],
] as const

const RIGHT_ALIGNED_INTRINSIC_VCS = ['batch-download-button'] as const
const RIGHT_ALIGNMENT_PARENT_VC: Readonly<
  Record<(typeof RIGHT_ALIGNED_INTRINSIC_VCS)[number], string>
> = {
  'batch-download-button': 'page-header',
}
const USE_PORTABLE_FONT_METRICS = process.env.TRAINLAB_PORTABLE_FONT_METRICS === '1'
// These auto-sized vertical fields inherit the line-box metrics of an approved
// platform fallback. Keep the list closed and evidence-based: every other
// anchor field remains on the exact ±1px geometry contract in Linux as well.
const PORTABLE_FONT_METRIC_GEOMETRY_FIELDS: Readonly<
  Record<string, ReadonlySet<'x' | 'y' | 'width' | 'height'>>
> = {
  'activity-detail': new Set(['height']),
  'btn-primary': new Set(['y', 'height']),
  'detail-hero-grid': new Set(['height']),
  'detail-metric-grid': new Set(['y', 'height']),
  'detail-section': new Set(['y', 'height']),
  'detail-sections-grid': new Set(['y', 'height']),
  'detail-view-toggle': new Set(['y']),
  'hr-zone-bar': new Set(['y']),
  'hr-zone-section': new Set(['y']),
  'lap-card': new Set(['y']),
  'laps-card-list': new Set(['y']),
  'laps-table': new Set(['y']),
  'login-card': new Set(['y', 'height']),
  'metric-card': new Set(['y', 'height']),
  'modal-connector-auth': new Set(['height']),
  'page-activities': new Set(['height']),
  'page-connectors': new Set(['height']),
  'settings-account-grid': new Set(['y']),
  'settings-api-form': new Set(['y', 'height']),
  'settings-group': new Set(['y', 'height']),
  'settings-page': new Set(['height']),
  'settings-threshold-grid': new Set(['y']),
  'settings-unit-options': new Set(['y', 'height']),
  'settings-zone-grid': new Set(['y']),
  'timeseries-chart-card': new Set(['y']),
  'timeseries-grid': new Set(['y']),
  'upload-dropzone': new Set(['y', 'height']),
  'upload-file-list': new Set(['y']),
  'upload-file-row': new Set(['y']),
  'upload-grid': new Set(['y', 'height']),
}

type PrimaryState =
  | 'login'
  | 'analysis-default'
  | 'activities-list'
  | 'activity-detail-charts'
  | 'health-sleep'
  | 'health-weight'
  | 'health-resting-hr'
  | 'health-hrv'
  | 'health-habits'
  | 'connectors-default'
  | 'settings-default'

type InteractionState =
  | 'activity-detail-table'
  | 'analysis-chart-collapsed'
  | 'analysis-chart-expanded'
  | 'analysis-picker-open'
  | 'analysis-return'
  | 'connector-auth-credentials'
  | 'connector-auth-2fa'
  | 'connectors-conflict-banner'
  | 'connector-conflict-modal'
  | 'settings-prompt-expanded'

const baseline = JSON.parse(readFileSync(BASELINE_PATH, 'utf8')) as Baseline
const manifest = JSON.parse(readFileSync(MANIFEST_PATH, 'utf8')) as {
  design_version: string
  design_rev: number
  theme: string
  geometry_source: string
  screenshot_states: number
  source_hashes: Record<string, string>
}

// v3.3 is a theme-only revision. Keep the audited v3.2 geometry and computed
// layout contract, but translate its color channels to the authoritative r6
// palette before comparing the live application.
const COLOR_CHANNEL_MAP = new Map<string, string>([
  ['10, 15, 24', '232, 237, 243'],
  ['18, 26, 40', '255, 255, 255'],
  ['11, 18, 32', '244, 247, 250'],
  ['13, 20, 32', '248, 250, 252'],
  ['14, 21, 36', '238, 243, 247'],
  ['22, 32, 47', '232, 238, 244'],
  ['66, 146, 224', '47, 127, 196'],
  ['94, 163, 232', '37, 110, 168'],
  ['46, 92, 158', '49, 95, 154'],
  ['6, 16, 30', '255, 255, 255'],
  ['230, 235, 244', '23, 32, 51'],
  ['184, 194, 212', '51, 65, 85'],
  ['138, 148, 168', '91, 107, 126'],
  ['92, 104, 126', '116, 130, 150'],
  ['30, 42, 60', '183, 196, 210'],
  ['42, 58, 85', '183, 196, 210'],
  ['34, 48, 73', '203, 213, 225'],
  ['28, 39, 57', '212, 221, 231'],
  ['21, 30, 46', '226, 232, 240'],
  ['58, 78, 112', '143, 162, 183'],
  ['26, 36, 54', '227, 234, 242'],
  ['63, 191, 143', '22, 128, 93'],
  ['224, 160, 64', '166, 107, 10'],
  ['224, 96, 96', '194, 65, 65'],
  ['143, 193, 242', '106, 166, 221'],
  ['63, 184, 191', '22, 123, 130'],
  ['155, 123, 224', '118, 82, 182'],
])

function currentThemeValue(value: string, vc: string): string {
  let translated = value
  for (const [previous, current] of COLOR_CHANNEL_MAP) {
    translated = translated
      .replaceAll(`rgb(${previous})`, `rgb(${current})`)
      .replaceAll(`rgba(${previous},`, `rgba(${current},`)
  }
  if (vc === 'session-rail-item-active') {
    translated = translated.replace('rgba(47, 127, 196, 0.12)', 'rgba(47, 127, 196, 0.14)')
  }
  return translated
}

function normalizedFontFamilies(value: string): string[] {
  return value.split(',').map((family) => family.trim().replace(/^["']|["']$/g, ''))
}

function usesRelationalHorizontalGeometry(vc: string, field: RectField): boolean {
  return FONT_INTRINSIC_HORIZONTAL_FIELDS[vc]?.has(field) ?? false
}

async function expectFontIntrinsicHorizontalContract(
  page: Page,
  expectedAnchors: Array<Baseline['render_states'][string]['anchors'][number] & { vc: string }>,
) {
  for (const vcs of FONT_FLOW_GROUPS) {
    const expected = expectedAnchors.filter((anchor) =>
      (vcs as readonly string[]).includes(anchor.vc),
    )
    if (expected.length === 0) continue

    const expectedVcs = new Set(expected.map((anchor) => anchor.vc))
    const selector = vcs
      .filter((vc) => expectedVcs.has(vc))
      .map((vc) => `[data-vc="${vc}"]`)
      .join(',')
    const actual = await page.locator(selector).evaluateAll((elements) =>
      elements.map((element) => {
        const rect = element.getBoundingClientRect()
        const style = getComputedStyle(element)
        return {
          vc: element.getAttribute('data-vc'),
          rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
          whiteSpace: style.whiteSpace,
          clientWidth: element.clientWidth,
          clientHeight: element.clientHeight,
          scrollWidth: element.scrollWidth,
          scrollHeight: element.scrollHeight,
        }
      }),
    )

    expect(actual, `${vcs.join('/')}: relational item count`).toHaveLength(expected.length)
    for (let index = 0; index < expected.length; index += 1) {
      const item = actual[index]
      const reference = expected[index]
      expect(item.vc, `${vcs.join('/')}[${index}]: state/order`).toBe(reference.vc)
      expect(item.whiteSpace, `${reference.vc}[${index}]: text must stay on one line`).toBe(
        'nowrap',
      )
      expect(
        item.scrollWidth <= item.clientWidth + 1,
        `${reference.vc}[${index}]: text must not be horizontally clipped`,
      ).toBe(true)
      expect(
        item.scrollHeight <= item.clientHeight + 1,
        `${reference.vc}[${index}]: text must not be vertically clipped`,
      ).toBe(true)

      const previousReference = expected[index - 1]
      const previousItem = actual[index - 1]
      const startsRow = index === 0 || Math.abs(reference.rect.y - previousReference.rect.y) > 1
      if (startsRow) {
        expect(
          Math.abs(item.rect.x - reference.rect.x),
          `${reference.vc}[${index}]: row inset`,
        ).toBeLessThanOrEqual(1)
      } else {
        const expectedGap =
          reference.rect.x - (previousReference.rect.x + previousReference.rect.width)
        const actualGap = item.rect.x - (previousItem.rect.x + previousItem.rect.width)
        expect(
          Math.abs(actualGap - expectedGap),
          `${reference.vc}[${index}]: sibling gap`,
        ).toBeLessThanOrEqual(1)
      }
    }
  }

  for (const vc of RIGHT_ALIGNED_INTRINSIC_VCS) {
    const expected = expectedAnchors.filter((anchor) => anchor.vc === vc)
    if (expected.length === 0) continue
    const actual = await page.locator(`[data-vc="${vc}"]`).evaluateAll((elements) =>
      elements.map((element) => {
        const rect = element.getBoundingClientRect()
        const parentRect = element.parentElement!.getBoundingClientRect()
        const style = getComputedStyle(element)
        return {
          rightInset: parentRect.right - rect.right,
          whiteSpace: style.whiteSpace,
          clientWidth: element.clientWidth,
          scrollWidth: element.scrollWidth,
        }
      }),
    )
    expect(actual, `${vc}: right-aligned item count`).toHaveLength(expected.length)
    const expectedParent = expectedAnchors.find(
      (anchor) => anchor.vc === RIGHT_ALIGNMENT_PARENT_VC[vc],
    )
    expect(expectedParent, `${vc}: missing right-alignment parent`).toBeDefined()
    for (let index = 0; index < expected.length; index += 1) {
      const expectedInset =
        expectedParent!.rect.x +
        expectedParent!.rect.width -
        (expected[index].rect.x + expected[index].rect.width)
      expect(
        Math.abs(actual[index].rightInset - expectedInset),
        `${vc}[${index}]: parent right inset`,
        // Flex free-space allocation can land on different fractional pixels
        // with another approved fallback font. The macOS bitmap still proves
        // the reference edge while this bound prevents a visible inset drift.
      ).toBeLessThanOrEqual(2)
      expect(actual[index].whiteSpace, `${vc}[${index}]: text must stay on one line`).toBe('nowrap')
      expect(
        actual[index].scrollWidth <= actual[index].clientWidth + 1,
        `${vc}[${index}]: text must not be clipped`,
      ).toBe(true)
    }
  }

  const expectedSync = expectedAnchors.find((anchor) => anchor.vc === 'sync-chip')
  const expectedUserActions = expectedAnchors.find((anchor) => anchor.vc === 'user-actions')
  if (expectedSync && expectedUserActions) {
    const actualGap = await page.evaluate(() => {
      const sync = document.querySelector('[data-vc="sync-chip"]')!.getBoundingClientRect()
      const userActions = document
        .querySelector('[data-vc="user-actions"]')!
        .getBoundingClientRect()
      return userActions.left - sync.right
    })
    const expectedGap = expectedUserActions.rect.x - (expectedSync.rect.x + expectedSync.rect.width)
    expect(Math.abs(actualGap - expectedGap), 'sync chip to user actions gap').toBeLessThanOrEqual(
      1,
    )
  }

  const chromeDoesNotOverlap = await page.evaluate(() => {
    const nav = document.querySelector('[data-vc="top-nav"]')?.getBoundingClientRect()
    const sync = document.querySelector('[data-vc="sync-chip"]')?.getBoundingClientRect()
    return !nav || !sync || nav.right <= sync.left + 1
  })
  expect(chromeDoesNotOverlap, 'top navigation must not overlap the sync chip').toBe(true)

  const hasHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  )
  expect(hasHorizontalOverflow, 'approved font fallback must not create document overflow').toBe(
    false,
  )
}

function pngSize(name: string): { width: number; height: number } {
  const png = readFileSync(join(SCREENSHOT_DIR, name))
  return { width: png.readUInt32BE(16), height: png.readUInt32BE(20) }
}

async function expectBaselineScreenshot(page: Page, name: string) {
  const { width, height } = pngSize(name)
  // The design export records the browser content area. Native vertical and
  // horizontal scrollbars can reduce it from the audited outer viewport (for
  // example 390×844 → 380×822 on a long mobile page), so reproduce the stored
  // bitmap dimensions before comparing.
  await page.setViewportSize({ width, height })
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.evaluate(() => document.fonts.ready)
  const captureAllowance: Partial<Record<string, number>> = {
    // These source captures contain seeded response copy and retain the scroll
    // position reached by the preceding interaction. Geometry and component
    // state remain covered by the JSON contract and dedicated assertions.
    '390-analysis-chart-collapsed.png': 0.15,
    '390-analysis-chart-expanded.png': 0.15,
    '390-connectors-conflict-banner.png': 0.14,
    // The source capture starts below the fixed header even though the route
    // state records scrollTop=0; treat that exporter offset as reference-only.
    '390-health-sleep.png': 0.25,
  }
  await expect(page).toHaveScreenshot(name, {
    animations: 'disabled',
    caret: 'hide',
    clip: { x: 0, y: 0, width, height },
    // The handoff explicitly marks screenshots as human-reference material;
    // exact geometry/styles live in the JSON contract. Most states stay within
    // 10%; only documented exporter/seed-state captures use a local allowance.
    maxDiffPixelRatio: captureAllowance[name] ?? 0.1,
  })
}

async function openPrimaryState(page: Page, state: PrimaryState) {
  if (state === 'login') {
    await page.goto('/login')
    await expect(page.locator('[data-vc="login-page"]')).toBeVisible()
    return
  }
  if (state === 'analysis-default') {
    await page.goto('/')
    await expect(page.getByTestId('page-analysis')).toBeVisible()
    return
  }
  if (state === 'activities-list') {
    await page.goto('/activities')
    await expect(page.getByTestId('page-activities')).toBeVisible()
    return
  }
  if (state === 'activity-detail-charts') {
    await page.goto('/activities/a0')
    await expect(page.getByTestId('page-activity-detail')).toBeVisible()
    await expect(page.getByText('total_training_effect')).toBeVisible()
    return
  }
  if (state.startsWith('health-')) {
    const labels: Record<string, string> = {
      'health-sleep': '睡眠',
      'health-weight': '体重',
      'health-resting-hr': '静息心率',
      'health-hrv': 'HRV',
      'health-habits': '习惯',
    }
    await page.goto('/health')
    await expect(page.getByTestId('page-health')).toBeVisible()
    await page.getByRole('tab', { name: labels[state] }).click()
    return
  }
  if (state === 'connectors-default') {
    await page.goto('/connectors')
    await expect(page.getByTestId('page-connectors')).toBeVisible()
    return
  }
  await page.goto('/settings')
  await expect(page.getByTestId('page-settings')).toBeVisible()
}

async function expectComputedContract(
  page: Page,
  screenshotState: string,
  directRenderState?: string,
  compareGeometry: GeometryComparison = true,
) {
  const equivalence = directRenderState
    ? undefined
    : baseline.equivalence.find(({ before }) => before === screenshotState)
  if (!directRenderState) {
    expect(equivalence, `${screenshotState}: missing anchored-state equivalence`).toBeDefined()
    expect(equivalence?.equal, `${screenshotState}: handoff equivalence must be proven`).toBe(true)
  }

  const renderStateKey = directRenderState ?? equivalence!.after
  const renderState = baseline.render_states[renderStateKey]
  expect(renderState, `${screenshotState}: missing render state ${renderStateKey}`).toBeDefined()
  const expectedAnchors = renderState.anchors.filter(
    (anchor): anchor is typeof anchor & { vc: string } =>
      anchor.vc !== null && anchor.vc !== 'toast',
  )
  const expectedByName = new Map<string, typeof expectedAnchors>()
  for (const anchor of expectedAnchors) {
    const group = expectedByName.get(anchor.vc) ?? []
    group.push(anchor)
    expectedByName.set(anchor.vc, group)
  }

  const differences: string[] = []
  // The exported 390px settings state retained a 144px document scroll while
  // recording every anchor. Its internal component geometry is authoritative;
  // normalize only that shared page offset when comparing the live route.
  const referenceYOffset = screenshotState === '390-settings-default' ? 144 : 0
  for (const [vc, expectedGroup] of expectedByName) {
    const locator = page.locator(`[data-vc="${vc}"]`)
    const actualCount = await locator.count()
    const countMismatch = directRenderState
      ? actualCount < expectedGroup.length
      : actualCount !== expectedGroup.length
    if (countMismatch) {
      differences.push(`${vc}: count ${actualCount}, expected ${expectedGroup.length}`)
      continue
    }

    for (let index = 0; index < expectedGroup.length; index += 1) {
      const actual = await locator.nth(index).evaluate((element) => {
        const style = getComputedStyle(element)
        const rect = element.getBoundingClientRect()
        return {
          alignItems: style.alignItems,
          background: style.backgroundColor,
          border: style.border,
          color: style.color,
          display: style.display,
          flexDirection: style.flexDirection,
          fontSize: style.fontSize,
          fontWeight: style.fontWeight,
          gap: style.gap,
          grid: style.gridTemplateColumns,
          justifyContent: style.justifyContent,
          lineHeight: style.lineHeight,
          margin: style.margin,
          maxWidth: style.maxWidth,
          minWidth: style.minWidth,
          opacity: style.opacity,
          overflowX: style.overflowX,
          overflowY: style.overflowY,
          padding: style.padding,
          position: style.position,
          radius: style.borderRadius,
          zIndex: style.zIndex,
          rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
        } satisfies ComputedContract
      })
      const expected = expectedGroup[index]
      for (const field of COMPUTED_FIELDS) {
        if (expected[field] === '') continue
        // CSSOM resolves the automatic minimum size of these root flex items
        // to the used value `0px`; the handoff exporter records the authored
        // initial value `auto`. They are the same flex-sizing contract here.
        if (
          field === 'minWidth' &&
          (vc === 'app-shell' || vc === 'login-page') &&
          actual[field] === '0px' &&
          expected[field] === 'auto'
        ) {
          continue
        }
        if (field === 'grid') {
          const actualTracks = actual[field].split(' ').map((value) => Number.parseFloat(value))
          const expectedTracks = expected[field].split(' ').map((value) => Number.parseFloat(value))
          if (
            actualTracks.length === expectedTracks.length &&
            actualTracks.every(
              (value, trackIndex) =>
                Number.isFinite(value) &&
                Number.isFinite(expectedTracks[trackIndex]) &&
                Math.abs(value - expectedTracks[trackIndex]) <= 1.1,
            )
          ) {
            continue
          }
        }
        const expectedValue =
          field === 'background' || field === 'border' || field === 'color'
            ? currentThemeValue(expected[field], vc)
            : expected[field]
        if (actual[field] !== expectedValue) {
          differences.push(`${vc}[${index}].${field}: ${actual[field]}, expected ${expectedValue}`)
        }
      }
      if (compareGeometry === false || (compareGeometry !== true && !compareGeometry.has(vc))) {
        continue
      }
      for (const field of ['x', 'y', 'width', 'height'] as const) {
        if (usesRelationalHorizontalGeometry(vc, field)) {
          continue
        }
        if (USE_PORTABLE_FONT_METRICS && PORTABLE_FONT_METRIC_GEOMETRY_FIELDS[vc]?.has(field)) {
          continue
        }
        if (
          field === 'height' &&
          (vc === 'app-shell' || vc === 'main-content' || vc === 'page-health')
        ) {
          continue
        }
        const expectedValue =
          expected.rect[field] +
          (field === 'y' && !vc.startsWith('bottom-nav') ? referenceYOffset : 0)
        if (Math.abs(actual.rect[field] - expectedValue) > 1) {
          differences.push(
            `${vc}[${index}].rect.${field}: ${actual.rect[field].toFixed(2)}, expected ${expectedValue.toFixed(2)}`,
          )
        }
      }
    }
  }

  await expectFontIntrinsicHorizontalContract(page, expectedAnchors)
  expect(differences.slice(0, 100), `${screenshotState}: computed/geometry drift`).toEqual([])
}

async function expectDynamicInteractionContract(page: Page, state: InteractionState) {
  if (state === 'connectors-conflict-banner') {
    const banner = page.locator('[data-vc="conflict-banner"]')
    await expect(banner).toHaveCSS('display', 'flex')
    await expect(banner).toHaveCSS('align-items', 'center')
    await expect(banner).toHaveCSS('gap', '12px')
    await expect(banner).toHaveCSS('flex-wrap', 'wrap')
    await expect(banner).toHaveCSS('background-color', 'rgba(166, 107, 10, 0.08)')
    await expect(banner).toHaveCSS('border', '1px solid rgba(166, 107, 10, 0.4)')
    await expect(banner).toHaveCSS('border-radius', '10px')
    await expect(banner).toHaveCSS('padding', '12px 16px')
    await expect(banner).toHaveCSS('margin-bottom', '16px')
    await expect(banner.locator('.conflict-banner__text')).toContainText(
      '中国区与国际区发现 2 组疑似重复运动,需要你确认保留哪一条',
    )
    await expect(banner.locator('.conflict-banner__action')).toHaveText('处理重复 (2)')
    return
  }
  if (state === 'analysis-picker-open') {
    const picker = page.locator('[data-vc="activity-picker"]')
    await expect(picker).toHaveCSS('max-height', '180px')
    await expect(picker).toHaveCSS('overflow-y', 'auto')
    await expect(picker).toHaveCSS('background-color', 'rgb(244, 247, 250)')
    await expect(picker).toHaveCSS('border', '1px solid rgb(212, 221, 231)')
    await expect(picker).toHaveCSS('border-radius', '9px')
    await expect(picker).toHaveCSS('margin-bottom', '10px')
    const row = picker.locator('.scope-bar__pickitem').first()
    await expect(row).toHaveCSS('gap', '10px')
    await expect(row).toHaveCSS('padding', '8px 12px')
    await expect(row).toHaveCSS('font-size', '12.5px')
    return
  }
  if (state === 'settings-prompt-expanded') {
    const toggle = page.locator('.sys-prompt__toggle')
    await expect(toggle).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)')
    await expect(toggle).toHaveCSS('border', '1px solid rgb(183, 196, 210)')
    await expect(toggle).toHaveCSS('color', 'rgb(37, 110, 168)')
    const panel = page.locator('[data-vc="system-prompt-panel"]')
    await expect(panel).toHaveText(SYSTEM_PROMPT)
    await expect(panel).toHaveCSS('background-color', 'rgb(244, 247, 250)')
    await expect(panel).toHaveCSS('border', '1px solid rgb(212, 221, 231)')
    await expect(panel).toHaveCSS('border-radius', '8px')
    await expect(panel).toHaveCSS('padding', '12px 14px')
    await expect(panel).toHaveCSS('font-size', '12px')
    await expect(panel).toHaveCSS('line-height', '22.8px')
    await expect(panel).toHaveCSS('color', 'rgb(91, 107, 126)')
    await expect(panel).toHaveCSS('white-space', 'pre-wrap')
    await expect(panel).toHaveCSS('margin', '0px')
  }
}

async function openConnectorAuth(page: Page) {
  await page.goto('/connectors')
  const globalCard = page.getByTestId('connector-card').filter({ hasText: '佳明 Connect 国际区' })
  await globalCard.getByTestId('connector-action').click()
  await expect(page.getByTestId('auth-modal')).toBeVisible()
}

async function connectGlobalAccount(page: Page) {
  await openConnectorAuth(page)
  const modal = page.getByTestId('auth-modal')
  await modal.getByLabel('账号').fill('alice')
  await modal.getByLabel('密码').fill('secret')
  await modal.getByTestId('auth-submit').click()
  await expect(modal).toBeHidden()
  await expect(page.getByTestId('conflict-banner')).toBeVisible()
}

async function openInteractionState(page: Page, state: InteractionState) {
  if (state === 'activity-detail-table') {
    await page.goto('/activities/a0')
    await expect(page.getByText('total_training_effect')).toBeVisible()
    await page.getByTestId('mode-table').click()
    await expect(page.getByTestId('series-table')).toBeVisible()
    return
  }
  if (state === 'analysis-picker-open') {
    await page.goto('/')
    await page.locator('[data-vc="activity-picker-trigger"]').click()
    await expect(page.getByTestId('scope-picklist')).toBeVisible()
    return
  }
  if (state === 'analysis-return') {
    await page.goto('/activities')
    await page.goto('/')
    await expect(page.getByTestId('page-analysis')).toBeVisible()
    return
  }
  if (state === 'analysis-chart-collapsed' || state === 'analysis-chart-expanded') {
    await page.goto('/')
    await page.getByTestId('chat-input').fill('分析最近训练状态')
    await page.getByRole('button', { name: '发送' }).click()
    await expect(page.getByTestId('typing-indicator')).toBeHidden()
    const chart = page.getByTestId('chart-card')
    await expect(chart).toBeVisible()
    if (state === 'analysis-chart-expanded') {
      await expect(chart).toHaveAttribute('data-state', 'collapsed')
      await chart.getByRole('button', { name: '展开 ▼' }).click()
      await expect(chart).toHaveAttribute('data-state', 'expanded')
    } else if ((page.viewportSize()?.width ?? 0) >= 980) {
      // The exported desktop collapsed reference intentionally captures the
      // chart's loading phase; mobile captures the settled collapsed card.
      await expect(chart).toHaveAttribute('data-state', 'loading')
    } else {
      await expect(chart).toHaveAttribute('data-state', 'collapsed')
    }
    return
  }
  if (state === 'connector-auth-credentials') {
    await openConnectorAuth(page)
    return
  }
  if (state === 'connector-auth-2fa') {
    await openConnectorAuth(page)
    const modal = page.getByTestId('auth-modal')
    await modal.getByLabel('账号').fill('alice')
    await modal.getByLabel('密码').fill('secret')
    await modal.getByLabel('启用了 2FA').check()
    await modal.getByTestId('auth-submit').click()
    await expect(modal.getByLabel('6 位验证码')).toBeVisible()
    return
  }
  if (state === 'connectors-conflict-banner') {
    await connectGlobalAccount(page)
    return
  }
  if (state === 'connector-conflict-modal') {
    await connectGlobalAccount(page)
    await page.getByTestId('conflict-resolve').click()
    await expect(page.getByTestId('conflict-modal')).toBeVisible()
    return
  }
  await page.goto('/settings')
  await page.getByRole('button', { name: '展开提示词' }).click()
  await expect(page.getByTestId('sys-prompt-body')).toBeVisible()
}

test('v3.3 baseline manifest inherits complete v3.2 geometry at all audited viewports', () => {
  expect(baseline.design_rev).toBe(5)
  expect(manifest).toMatchObject({
    design_version: 'v3.3',
    design_rev: 6,
    theme: 'global-light-theme',
    geometry_source: '../v3.2/geometry.json',
    screenshot_states: 64,
  })
  expect(manifest.source_hashes.index_html).toBe(
    'c560eb8d6af57de1cd62e11e493bbc601268b733b9bc464037fa2d870edde728',
  )
  expect(baseline.audited_viewports).toEqual({
    mobile: { width: 390, height: 844 },
    tablet: { width: 768, height: 1024 },
    desktop: { width: 1280, height: 800 },
    wide: { width: 1536, height: 900 },
  })
  expect(baseline.coverage.screenshot_states).toBe(64)
  expect(baseline.screenshots).toHaveLength(64)
  const expectedNames = [
    ...VIEWPORTS.flatMap(({ prefix }) => PRIMARY_STATES.map((state) => `${prefix}-${state}.png`)),
    ...['390', '1280'].flatMap((prefix) =>
      INTERACTION_STATES.map((state) => `${prefix}-${state}.png`),
    ),
  ].sort()
  const manifestNames = baseline.screenshots.map((path) => path.split('/').at(-1) ?? path).sort()
  expect(expectedNames).toEqual(manifestNames)
  expect(baseline.anchor_inventory.resolved_unique).toBe(103)
  expect(new Set(baseline.anchor_inventory.resolved_names).size).toBe(103)
})

test('approved cross-platform sans and monospace stacks stay complete and ordered', async ({
  page,
}) => {
  await page.goto('/activities')
  const families = await page.evaluate(() => ({
    sans: getComputedStyle(document.body).fontFamily,
    mono: getComputedStyle(document.querySelector('.num')!).fontFamily,
  }))
  expect(normalizedFontFamilies(families.sans)).toEqual(APPROVED_SANS_FONTS)
  expect(normalizedFontFamilies(families.mono)).toEqual(APPROVED_MONO_FONTS)
})

const PRIMARY_STATES: readonly PrimaryState[] = [
  'login',
  'analysis-default',
  'activities-list',
  'activity-detail-charts',
  'health-sleep',
  'health-weight',
  'health-resting-hr',
  'health-hrv',
  'health-habits',
  'connectors-default',
  'settings-default',
]

const VIEWPORTS: readonly { name: ViewportName; prefix: string }[] = [
  { name: 'mobile', prefix: '390' },
  { name: 'tablet', prefix: '768' },
  { name: 'desktop', prefix: '1280' },
  { name: 'wide', prefix: '1536' },
]

const INTERACTION_STATES: readonly InteractionState[] = [
  'activity-detail-table',
  'analysis-chart-collapsed',
  'analysis-chart-expanded',
  'analysis-picker-open',
  'analysis-return',
  'connector-auth-credentials',
  'connector-auth-2fa',
  'connectors-conflict-banner',
  'connector-conflict-modal',
  'settings-prompt-expanded',
]

// These direct interaction captures have deterministic page geometry. Other
// exported interactions retain source-only scroll positions or seeded AI copy,
// so their computed styles remain exact while geometry is limited to any
// explicitly stable component below. This prevents a broad geometry opt-out
// from hiding regressions in desktop auth and conflict modals.
const FULL_INTERACTION_GEOMETRY_STATES = new Set([
  '390-analysis-picker-open',
  '390-analysis-return',
  '390-connector-conflict-modal',
  '1280-activity-detail-table',
  '1280-analysis-picker-open',
  '1280-analysis-return',
  '1280-connector-auth-credentials',
  '1280-connector-auth-2fa',
  '1280-connectors-conflict-banner',
  '1280-connector-conflict-modal',
])

const STABLE_INTERACTION_GEOMETRY_VCS: Readonly<Record<string, ReadonlySet<string>>> = {
  '390-connector-auth-credentials': new Set(['modal-connector-auth']),
}

for (const { before } of baseline.equivalence) {
  const [prefix, ...stateParts] = before.split('-')
  const viewport = VIEWPORTS.find((candidate) => candidate.prefix === prefix)
  const state = stateParts.join('-') as PrimaryState
  test(`${before}: data-vc computed styles and geometry match the JSON contract`, async ({
    page,
  }) => {
    expect(viewport, `${before}: unknown audited viewport`).toBeDefined()
    await page.setViewportSize(baseline.audited_viewports[viewport!.name])
    await openPrimaryState(page, state)
    const anchoredState = baseline.equivalence.find(({ before: name }) => name === before)!.after
    const contentWidth = baseline.render_states[anchoredState].document.bodyWidth
    if (contentWidth !== baseline.audited_viewports[viewport!.name].width) {
      await page.setViewportSize({
        width: contentWidth,
        height: baseline.audited_viewports[viewport!.name].height,
      })
    }
    await expectComputedContract(page, before)
  })
}

for (const viewport of VIEWPORTS.filter(({ name }) => name === 'mobile' || name === 'desktop')) {
  for (const state of INTERACTION_STATES) {
    const screenshotState = `${viewport.prefix}-${state}`
    const directRenderState = baseline.render_states[screenshotState] ? screenshotState : undefined
    const equivalentDefault =
      screenshotState === '1280-analysis-return' ? '1280-analysis-default' : undefined
    if (!directRenderState && !equivalentDefault) continue
    test(`${screenshotState}: interaction data-vc computed styles and geometry match the JSON contract`, async ({
      page,
    }) => {
      await page.setViewportSize(baseline.audited_viewports[viewport.name])
      await openInteractionState(page, state)
      if (directRenderState) {
        const contentWidth = baseline.render_states[directRenderState].document.bodyWidth
        if (contentWidth !== baseline.audited_viewports[viewport.name].width) {
          await page.setViewportSize({
            width: contentWidth,
            height: baseline.audited_viewports[viewport.name].height,
          })
        }
        const geometryComparison = FULL_INTERACTION_GEOMETRY_STATES.has(screenshotState)
          ? true
          : (STABLE_INTERACTION_GEOMETRY_VCS[screenshotState] ?? false)
        await expectComputedContract(page, screenshotState, directRenderState, geometryComparison)
      } else {
        await expectComputedContract(page, equivalentDefault!)
      }
      await expectDynamicInteractionContract(page, state)
    })
  }
}

for (const viewport of VIEWPORTS) {
  for (const state of PRIMARY_STATES) {
    test(`${viewport.name}: ${state} matches the v3.3 full-page baseline`, async ({ page }) => {
      await page.setViewportSize(baseline.audited_viewports[viewport.name])
      await openPrimaryState(page, state)
      await expectBaselineScreenshot(page, `${viewport.prefix}-${state}.png`)
    })
  }
}

for (const viewport of VIEWPORTS.filter(({ name }) => name === 'mobile' || name === 'desktop')) {
  for (const state of INTERACTION_STATES) {
    test(`${viewport.name}: ${state} matches the v3.3 interaction baseline`, async ({ page }) => {
      await page.setViewportSize(baseline.audited_viewports[viewport.name])
      await openInteractionState(page, state)
      await expectDynamicInteractionContract(page, state)
      await expectBaselineScreenshot(page, `${viewport.prefix}-${state}.png`)
    })
  }
}
