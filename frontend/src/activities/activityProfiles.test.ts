import {
  buildActivityProfile,
  profileActivityById,
  resolveActivityProfileId,
} from './activityProfiles'
import type { Activity } from './activityData'
import type { ParsedActivity } from './fitParser'

type ImportedProfile = NonNullable<ParsedActivity['backend']>['profile']
type ImportedSegment = NonNullable<ParsedActivity['backend']>['segments'][number]

function importedActivity(profile: ImportedProfile): Activity {
  const typeByProfile: Record<ImportedProfile, Activity['type']> = {
    run: '跑步',
    hike: '徒步',
    strength: '力量',
    lead: '难度攀岩',
    boulder: '抱石',
    cycling: '骑行',
    generic: '其他',
  }
  return {
    id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    date: '2026-07-14',
    type: typeByProfile[profile],
    name: `真实${typeByProfile[profile]}`,
    distanceKm: null,
    durationSec: 120,
    avgHr: 118,
    paceSecPerKm: null,
    pace100Sec: null,
    powerW: null,
    source: 'FIT上传',
    profile,
  }
}

function importedParsed(profile: ImportedProfile, segments: ImportedSegment[]): ParsedActivity {
  return {
    summary: {
      sport: profile === 'lead' || profile === 'boulder' ? 'rock_climbing' : profile,
      subSport: profile,
      startTime: '2026-07-14T07:49:13Z',
      localStartTime: '2026-07-14T15:49:13',
      utcOffsetMinutes: 480,
      totalTimerTimeSec: 120,
      totalElapsedTimeSec: 180,
      totalDistanceM: 0,
      avgHr: 118,
      maxHr: 160,
      totalCalories: 40,
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
      avgLSS: null,
      avgVILR: null,
      avgBodyYPIF: null,
      workoutFeel: null,
      workoutRpe: null,
      extraMetrics: {},
    },
    records: [],
    laps: [],
    hrZoneSeconds: [],
    backend: {
      profile,
      parseStatus: 'complete',
      originalFileName: `${profile}.fit`,
      downloadAvailable: true,
      recordCount: 0,
      recordsSampled: false,
      segments,
      devices: [],
      metricDefinitions: [],
    },
  }
}

function splitPairs(count: number): ImportedSegment[] {
  const segments = Array.from({ length: count }, (_, index) =>
    (['climb_active', 'rest'] as const).map((kind, offset): ImportedSegment => ({
      sequence: index * 2 + offset,
      kind,
      label: null,
      startTime: null,
      durationSec: 30,
      repetitions: null,
      weightKg: null,
      extraData: { sourceMessage: 'split' },
      semantic: {
        schemaVersion: 1,
        sourceMessage: 'split',
        ...(kind === 'climb_active'
          ? {
              climb: {
                gradeStatus: 'unavailable' as const,
                gradeReason: 'unknown_profile_field' as const,
              },
            }
          : {}),
      },
    })),
  ).flat()
  return [
    ...segments,
    ...Array.from({ length: 2 }, (_, index): ImportedSegment => ({
      sequence: segments.length + index,
      kind: 'split_summary',
      label: null,
      startTime: null,
      durationSec: count * 30,
      repetitions: null,
      weightKg: null,
      extraData: { sourceMessage: 'split_summary' },
      semantic: { schemaVersion: 1, sourceMessage: 'split_summary' as const },
    })),
  ]
}

function strengthContractSegments(): ImportedSegment[] {
  const names = Array.from({ length: 10 }, (_, index) => `合成动作${index + 1}`)
  const sets: ImportedSegment[] = []
  for (let group = 0; group < 30; group += 1) {
    const actionIndex = group % names.length
    sets.push({
      sequence: sets.length,
      kind: 'active',
      label: actionIndex === 0 ? "['dirty', 'array']" : String(20 + actionIndex),
      startTime: null,
      durationSec: 1393.485 / 30,
      repetitions: 5 + actionIndex,
      weightKg:
        actionIndex === 0 || actionIndex === 2 ? null : actionIndex === 1 ? 0 : 10 + actionIndex,
      extraData: {
        sourceMessage: 'set',
        ...(actionIndex === 0 ? { weight_type: 'body_weight' } : {}),
      },
      semantic: {
        schemaVersion: 1,
        sourceMessage: 'set',
        exercise: { stepIndex: actionIndex, name: names[actionIndex] },
      },
    })
    if (group < 29) {
      sets.push({
        sequence: sets.length,
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
  const parallel = Array.from({ length: 58 }, (_, index): ImportedSegment => ({
    sequence: sets.length + index,
    kind: index % 2 ? 'rest' : 'active',
    label: '不应重复',
    startTime: null,
    durationSec: 999,
    repetitions: 999,
    weightKg: 999,
    extraData: { sourceMessage: 'split' },
    semantic: { schemaVersion: 1, sourceMessage: 'split' },
  }))
  const summaries = Array.from({ length: 4 }, (_, index): ImportedSegment => ({
    sequence: sets.length + parallel.length + index,
    kind: 'split_summary',
    label: null,
    startTime: null,
    durationSec: 999,
    repetitions: null,
    weightKg: null,
    extraData: { sourceMessage: 'split_summary' },
    semantic: { schemaVersion: 1, sourceMessage: 'split_summary' },
  }))
  return [...sets, ...parallel, ...summaries]
}

describe('activity profile resolver', () => {
  it.each([
    ['running', 'generic', 'run'],
    ['hiking', 'generic', 'hike'],
    ['running', 'trail', 'hike'],
    ['strength_training', 'generic', 'strength'],
    ['rock_climbing', 'indoor_climbing', 'lead'],
    ['rock_climbing', 'bouldering', 'boulder'],
    ['cycling', 'road', 'cycling'],
    ['future_sport', 'custom', 'generic'],
  ])('maps %s / %s to %s', (sport, subSport, expected) => {
    expect(resolveActivityProfileId(sport, subSport)).toBe(expected)
  })

  it('keeps unknown activity data in the generic fallback instead of running', () => {
    const activity = profileActivityById('profile-generic')
    expect(activity).toBeDefined()
    expect(buildActivityProfile(activity!, null).id).toBe('generic')
    expect(buildActivityProfile(activity!, null).metrics).not.toEqual(
      expect.arrayContaining([expect.objectContaining({ label: '平均配速' })]),
    )
  })

  it('keeps a trail run on the route profile before and after FIT parsing', () => {
    const activity: Activity = {
      id: 'trail-consistency',
      date: '2026-07-17',
      type: '越野跑',
      name: '越野跑',
      distanceKm: 10,
      durationSec: 3600,
      avgHr: 140,
      paceSecPerKm: 360,
      pace100Sec: null,
      powerW: null,
      source: 'FIT上传',
    }
    const parsed = {
      summary: { sport: 'running', subSport: 'trail' },
    } as Parameters<typeof buildActivityProfile>[1]

    expect(buildActivityProfile(activity, null).id).toBe('hike')
    expect(buildActivityProfile(activity, parsed).id).toBe('hike')
  })

  it.each([
    ['profile-hike', 'hike'],
    ['profile-strength', 'strength'],
    ['profile-lead', 'lead'],
    ['profile-boulder', 'boulder'],
    ['profile-cycling', 'cycling'],
    ['profile-generic', 'generic'],
  ])('provides a stable activity id for the %s profile', (activityId, profileId) => {
    const activity = profileActivityById(activityId)
    expect(activity).toBeDefined()
    expect(buildActivityProfile(activity!, null).id).toBe(profileId)
  })

  it('does not invent values for cycling or generic profiles', () => {
    for (const id of ['profile-cycling', 'profile-generic']) {
      const activity = profileActivityById(id)!
      const profile = buildActivityProfile(activity, null)
      expect(profile.rawRecords).toHaveLength(0)
      expect(profile.segments).toHaveLength(0)
      expect(profile.metrics.some((metric) => /^\d/.test(metric.value))).toBe(false)
    }
  })

  it('renders an imported non-running activity from persisted capabilities', () => {
    const profile = buildActivityProfile(
      importedActivity('boulder'),
      importedParsed('boulder', splitPairs(1)),
    )
    expect(profile.id).toBe('boulder')
    expect(profile.fileName).toBe('boulder.fit')
    expect(profile.segments).toHaveLength(2)
    expect(profile.specialized).toMatchObject({ kind: 'attempts' })
    expect(profile.insight).toContain('不基于共现关系猜测')
  })

  it.each([
    ['lead', 5],
    ['boulder', 21],
  ] as const)('does not count split_summary as %s climb/rest instances', (profileId, pairCount) => {
    const profile = buildActivityProfile(
      importedActivity(profileId),
      importedParsed(profileId, splitPairs(pairCount)),
    )
    expect(profile.segments).toHaveLength(pairCount * 2)
    expect(profile.composition).toEqual([
      { label: profileId === 'boulder' ? '尝试' : '攀爬', value: pairCount * 30 },
      { label: '休息', value: pairCount * 30 },
    ])
    expect(profile.metrics.find((item) => item.label === '攀爬 / 休息')?.value).toBe(
      `${pairCount} / ${pairCount}`,
    )
    expect(profile.fields).toContainEqual(['split_summary', '2 个摘要'])
    expect(
      profile.segments.filter(
        (segment) => segment.label.startsWith('攀爬') || segment.label.startsWith('尝试'),
      ),
    ).toHaveLength(pairCount)
    expect(profile.segments.filter((segment) => segment.label.startsWith('休息'))).toHaveLength(
      pairCount,
    )
    for (const segment of profile.segments.filter(
      (candidate) => !candidate.label.startsWith('休息'),
    )) {
      expect(segment.details).toContain('等级暂不可用：文件字段尚无可靠映射')
      expect(segment.details.join(' ')).not.toMatch(/(?:^|\s)(?:69|70|71|72|73)(?:\s|$)/)
    }
  })

  it('uses FIT set messages for strength groups without duplicating parallel splits', () => {
    const make = (sequence: number, sourceMessage: 'set' | 'split' | 'split_summary') => ({
      sequence,
      kind: sequence % 2 ? 'rest' : 'active',
      label: `组 ${sequence + 1}`,
      startTime: null,
      durationSec: 30,
      repetitions: 8,
      weightKg: 20,
      extraData: { sourceMessage },
      semantic: { schemaVersion: 1 as const, sourceMessage },
    })
    const messages = [
      make(0, 'set'),
      make(1, 'set'),
      make(2, 'split'),
      make(3, 'split'),
      make(4, 'split_summary'),
    ]
    const profile = buildActivityProfile(
      importedActivity('strength'),
      importedParsed('strength', messages),
    )
    expect(profile.segments).toHaveLength(2)
    expect(profile.metrics.find((item) => item.label === '有效组')?.value).toBe('1')
    expect(profile.specialized).toMatchObject({
      kind: 'exercises',
      rows: expect.arrayContaining([]),
    })
    if (profile.specialized.kind !== 'exercises') throw new Error('expected exercises profile')
    expect(profile.specialized.rows).toHaveLength(1)
    expect(profile.specialized.rows[0][0]).toBe('动作名称未提供')
  })

  it('aggregates 10 normalized strength actions from 30 active and 29 rest sets only', () => {
    const profile = buildActivityProfile(
      importedActivity('strength'),
      importedParsed('strength', strengthContractSegments()),
    )
    const activeSeconds = profile.composition.find((item) => item.label === '活动')?.value
    const restSeconds = profile.composition.find((item) => item.label === '休息')?.value

    expect(profile.segments).toHaveLength(59)
    expect(profile.segments.filter((segment) => segment.label.startsWith('休息'))).toHaveLength(29)
    expect(activeSeconds).toBeCloseTo(1393.485, 6)
    expect(restSeconds).toBeCloseTo(2171.271, 6)
    expect(profile.metrics).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ label: '动作数', value: '10' }),
        expect.objectContaining({ label: '有效组', value: '30' }),
        expect.objectContaining({ label: '总次数', value: '285' }),
        expect.objectContaining({ label: '训练容量', value: '3780（部分）' }),
      ]),
    )
    expect(profile.fields).toContainEqual(['segment', '59 个实例'])
    expect(profile.fields).toContainEqual(['split_summary', '4 个摘要'])
    expect(profile.specialized.kind).toBe('exercises')
    if (profile.specialized.kind !== 'exercises') throw new Error('expected exercises profile')
    expect(profile.specialized.rows).toHaveLength(10)
    expect(profile.specialized.rows.map((row) => row[0])).toEqual(
      Array.from({ length: 10 }, (_, index) => `合成动作${index + 1}`),
    )
    expect(profile.specialized.rows[0][3]).toContain('3 组自重')
    expect(profile.specialized.rows[1][3]).toContain('3 组明确 0 kg')
    expect(profile.specialized.rows[2][3]).toContain('3 组重量未提供')
    expect(JSON.stringify(profile)).not.toContain("['dirty', 'array']")
    expect(JSON.stringify(profile)).not.toContain('不应重复')
  })

  it('shows a normalized climb grade only when the semantic projection marks it available', () => {
    const messages = splitPairs(1)
    messages[0] = {
      ...messages[0],
      extraData: { sourceMessage: 'split', 69: 999 },
      semantic: {
        schemaVersion: 1,
        sourceMessage: 'split',
        climb: {
          gradeStatus: 'available',
          gradeSystem: 'v_scale',
          grade: 'V2',
          outcome: 'complete',
        },
      },
    }
    const profile = buildActivityProfile(
      importedActivity('boulder'),
      importedParsed('boulder', messages),
    )

    expect(profile.segments[0].details).toEqual(['等级 V2', '已完成'])
    expect(JSON.stringify(profile)).not.toContain('999')
  })

  it('prefers semantic source messages and never falls back to split strength instances', () => {
    const splitOnly: ImportedSegment[] = [
      {
        sequence: 0,
        kind: 'active',
        label: '不应成为训练组',
        startTime: null,
        durationSec: 30,
        repetitions: 8,
        weightKg: 20,
        extraData: { sourceMessage: 'set' },
        semantic: { schemaVersion: 1, sourceMessage: 'split' },
      },
    ]

    const profile = buildActivityProfile(
      importedActivity('strength'),
      importedParsed('strength', splitOnly),
    )
    expect(profile.segments).toHaveLength(0)
    expect(profile.fields).toContainEqual(['segment', '0 个实例'])
  })
})
