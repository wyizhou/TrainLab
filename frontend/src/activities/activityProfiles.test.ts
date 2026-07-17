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
    (['climb_active', 'rest'] as const).map((kind, offset) => ({
      sequence: index * 2 + offset,
      kind,
      label: null,
      startTime: null,
      durationSec: 30,
      repetitions: null,
      weightKg: null,
      extraData: { sourceMessage: 'split' },
    })),
  ).flat()
  return [
    ...segments,
    ...Array.from({ length: 2 }, (_, index) => ({
      sequence: segments.length + index,
      kind: 'split_summary',
      label: null,
      startTime: null,
      durationSec: count * 30,
      repetitions: null,
      weightKg: null,
      extraData: { sourceMessage: 'split_summary' },
    })),
  ]
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
    expect(profile.metrics.find((item) => item.label === '分段 / 训练组')?.value).toBe(
      String(pairCount * 2),
    )
    expect(profile.fields).toContainEqual(['split_summary', '2 个摘要'])
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
    expect(profile.metrics.find((item) => item.label === '分段 / 训练组')?.value).toBe('2')
    expect(profile.specialized).toMatchObject({
      kind: 'exercises',
      rows: expect.arrayContaining([]),
    })
    if (profile.specialized.kind !== 'exercises') throw new Error('expected exercises profile')
    expect(profile.specialized.rows).toHaveLength(2)
  })
})
