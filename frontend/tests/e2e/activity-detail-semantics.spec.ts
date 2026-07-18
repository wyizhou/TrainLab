import { expect, test, type Page } from '@playwright/test'

type Profile = 'strength' | 'lead' | 'boulder'

const IDS: Record<Profile, string> = {
  strength: '11111111-1111-4111-8111-111111111111',
  lead: '22222222-2222-4222-8222-222222222222',
  boulder: '33333333-3333-4333-8333-333333333333',
}

function activity(profile: Profile) {
  const labels = {
    strength: ['力量', '合成力量训练'],
    lead: ['难度攀岩', '合成难度攀岩'],
    boulder: ['抱石', '合成抱石'],
  } as const
  return {
    id: IDS[profile],
    date: '2026-07-18',
    type: labels[profile][0],
    name: labels[profile][1],
    distanceKm: null,
    durationSec: 3600,
    avgHr: 118,
    paceSecPerKm: null,
    pace100Sec: null,
    powerW: null,
    source: 'FIT上传',
    profile,
  }
}

function baseDetail(profile: Profile, segments: unknown[]) {
  return {
    activity: activity(profile),
    summary: {
      sport: profile === 'strength' ? 'training' : 'rock_climbing',
      subSport: profile,
      startTime: '2026-07-18T01:00:00Z',
      localStartTime: '2026-07-18T09:00:00',
      utcOffsetMinutes: 480,
      totalTimerTimeSec: 3600,
      totalElapsedTimeSec: 3700,
      totalDistanceM: 0,
      avgHr: 118,
      maxHr: 160,
      totalCalories: 400,
      avgPowerW: null,
      maxPowerW: null,
      normalizedPowerW: null,
      totalAscentM: null,
      totalDescentM: null,
      avgSpeedMps: null,
      maxSpeedMps: null,
      avgCadenceSpm: null,
      totalTrainingEffect: null,
      totalAnaerobicTrainingEffect: null,
      avgTemperatureC: null,
      maxTemperatureC: null,
      minTemperatureC: null,
      avgGctMs: null,
      avgVertOscMm: null,
      avgVerticalRatio: null,
      avgStepLengthMm: null,
      workoutFeel: null,
      workoutRpe: null,
      extraMetrics: {},
    },
    records: [],
    recordCount: 0,
    recordsSampled: false,
    laps: [],
    segments,
    devices: [],
    metricDefinitions: [],
    parseStatus: 'complete',
    downloadAvailable: true,
    originalFileName: 'synthetic.fit',
  }
}

function strengthSegments() {
  const result = []
  for (let group = 0; group < 30; group += 1) {
    const action = group % 10
    result.push({
      sequence: result.length,
      kind: 'active',
      label: "['raw', 'array']",
      startTime: null,
      durationSec: 1393.485 / 30,
      repetitions: 5 + action,
      weightKg: action === 0 ? null : 10 + action,
      extraData: { sourceMessage: 'set', ...(action === 0 ? { weight_type: 'body_weight' } : {}) },
      semantic: {
        schemaVersion: 1,
        sourceMessage: 'set',
        exercise: { stepIndex: action, name: `合成动作${action + 1}` },
      },
    })
    if (group < 29) {
      result.push({
        sequence: result.length,
        kind: 'rest',
        label: '23',
        startTime: null,
        durationSec: 2171.271 / 29,
        repetitions: null,
        weightKg: null,
        extraData: { sourceMessage: 'set' },
        semantic: { schemaVersion: 1, sourceMessage: 'set' },
      })
    }
  }
  result.push(
    ...Array.from({ length: 58 }, (_, index) => ({
      sequence: result.length + index,
      kind: index % 2 ? 'rest' : 'active',
      label: 'split 不应重复',
      startTime: null,
      durationSec: 999,
      repetitions: 999,
      weightKg: 999,
      extraData: { sourceMessage: 'split' },
      semantic: { schemaVersion: 1, sourceMessage: 'split' },
    })),
  )
  return result
}

function climbingSegments(pairCount: number) {
  const result = Array.from({ length: pairCount }, (_, index) => [
    {
      sequence: index * 2,
      kind: 'climb_active',
      label: null,
      startTime: null,
      durationSec: 30,
      repetitions: null,
      weightKg: null,
      extraData: { sourceMessage: 'split', 69: 8, 70: 1, raw: ['hidden'] },
      semantic: {
        schemaVersion: 1,
        sourceMessage: 'split',
        climb: { gradeStatus: 'unavailable', gradeReason: 'unknown_profile_field' },
      },
    },
    {
      sequence: index * 2 + 1,
      kind: 'climb_rest',
      label: null,
      startTime: null,
      durationSec: 30,
      repetitions: null,
      weightKg: null,
      extraData: { sourceMessage: 'split' },
      semantic: { schemaVersion: 1, sourceMessage: 'split' },
    },
  ]).flat()
  return [
    ...result,
    {
      sequence: result.length,
      kind: 'split_summary',
      label: '摘要不应成为实例',
      startTime: null,
      durationSec: pairCount * 60,
      repetitions: null,
      weightKg: null,
      extraData: { sourceMessage: 'split_summary' },
      semantic: { schemaVersion: 1, sourceMessage: 'split_summary' },
    },
  ]
}

async function mockDetail(page: Page, profile: Profile) {
  const segments =
    profile === 'strength' ? strengthSegments() : climbingSegments(profile === 'lead' ? 5 : 21)
  await page.route(`**/api/v1/activities/${IDS[profile]}`, async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify(baseDetail(profile, segments)),
    })
  })
  await page.goto(`/activities/${IDS[profile]}`)
  await expect(page.getByTestId('activity-detail')).toHaveAttribute('data-profile', profile)
}

for (const viewport of [
  { width: 390, height: 844 },
  { width: 768, height: 1024 },
  { width: 1280, height: 800 },
  { width: 1536, height: 900 },
]) {
  test(`${viewport.width}px: normalized strength aggregation stays within the document`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport)
    await mockDetail(page, 'strength')

    await expect(page.locator('.detail-table tbody tr')).toHaveCount(10)
    const metrics = page.locator('[data-vc="activity-summary-metric"]')
    await expect(metrics.filter({ hasText: /^动作数/ })).toContainText('10')
    await expect(metrics.filter({ hasText: /^有效组/ })).toContainText('30')
    await expect(page.getByText("['raw', 'array']")).toHaveCount(0)
    await page.getByRole('button', { name: '分段 / 训练组' }).click()
    const rows = page.locator('[data-vc="activity-training-exercise"]')
    await expect(rows).toHaveCount(59)
    await expect(rows.filter({ hasText: /^休息 / })).toHaveCount(29)
    expect(
      await page.evaluate(() => ({
        width: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
      })),
    ).toMatchObject({ width: viewport.width, scrollWidth: viewport.width })
  })
}

for (const [profile, count] of [
  ['lead', 5],
  ['boulder', 21],
] as const) {
  test(`${profile} uses split instances and explains unavailable grades`, async ({ page }) => {
    await mockDetail(page, profile)
    await expect(page.getByText('攀爬 / 休息').locator('..')).toContainText(`${count} / ${count}`)
    await page.getByRole('button', { name: '分段 / 训练组' }).click()
    const rows = page.locator('[data-vc="activity-climb-attempt"]')
    await expect(rows).toHaveCount(count * 2)
    await expect(rows.filter({ hasText: '等级暂不可用：文件字段尚无可靠映射' })).toHaveCount(count)
    await expect(page.getByText('摘要不应成为实例')).toHaveCount(0)
    const visibleRowText = (await rows.allTextContents()).join('\n')
    expect(visibleRowText).not.toContain('["hidden"]')
    expect(visibleRowText).not.toMatch(/(?:^|\s)(?:69|70)(?:\s|$)/)
  })
}
