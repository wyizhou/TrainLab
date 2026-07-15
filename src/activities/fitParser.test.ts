import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { downsampleRecords, parseFitActivity, type ParsedActivity } from './fitParser'
import { FIT_A0 } from './activityData'

// The real sample lives as committed test infrastructure (contract C-8 前置).
const FIXTURE = join(process.cwd(), 'tests/fixtures/614797758_ACTIVITY.fit')

function parseFixture(): ParsedActivity {
  return parseFitActivity(new Uint8Array(readFileSync(FIXTURE)))
}

describe('parseFitActivity — FIT field whitelist (contract C-8, ≥8 assertions)', () => {
  const { summary, records, laps, hrZoneSeconds } = parseFixture()

  it('sport / sub_sport are the FIT stored enums', () => {
    expect(summary.sport).toBe('running')
    expect(summary.subSport).toBe('generic')
  })

  it('start_time is the exact FIT timestamp', () => {
    expect(summary.startTime).toBe('2026-07-08T22:41:56.000Z')
  })

  it('total_timer_time / total_distance match the FIT (exact)', () => {
    expect(summary.totalTimerTimeSec).toBe(1887.163)
    expect(summary.totalDistanceM).toBe(5081.39)
  })

  it('avg/max heart rate and total calories match the FIT (exact ints)', () => {
    expect(summary.avgHr).toBe(152)
    expect(summary.maxHr).toBe(170)
    expect(summary.totalCalories).toBe(344)
  })

  it('avg_speed converts to the displayed pace (371 s/km)', () => {
    const pace = summary.avgSpeedMps ? Math.round(1000 / summary.avgSpeedMps) : null
    expect(pace).toBe(371)
  })

  it('total_ascent is the FIT stored value', () => {
    expect(summary.totalAscentM).toBe(2)
  })

  it('training effects are FIT raw stored values (not computed)', () => {
    expect(summary.totalTrainingEffect).toBe(2.7)
    expect(summary.totalAnaerobicTrainingEffect).toBe(0)
  })

  it('the list row (FIT_A0) equals the parsed FIT to display precision', () => {
    expect(+(summary.totalDistanceM / 1000).toFixed(2)).toBe(FIT_A0.distanceKm)
    expect(Math.round(summary.totalTimerTimeSec)).toBe(FIT_A0.durationSec)
    expect(summary.avgHr).toBe(FIT_A0.avgHr)
    expect(summary.avgSpeedMps ? Math.round(1000 / summary.avgSpeedMps) : null).toBe(
      FIT_A0.paceSecPerKm,
    )
  })

  it('exposes per-second records, 8 laps and 5 HR zones', () => {
    expect(records.length).toBe(1890)
    expect(laps.length).toBe(8)
    expect(laps[0].avgPowerW).toBe(244)
    expect(hrZoneSeconds).toHaveLength(5)
    // FIT session time_in_hr_zone: most time in Z2/Z3.
    expect(hrZoneSeconds[1].seconds).toBeCloseTo(798.924, 2)
    expect(hrZoneSeconds[2].seconds).toBeCloseTo(1014.229, 2)
  })

  it('records carry the running-dynamics fields (gct / vertical oscillation)', () => {
    const mid = records[Math.floor(records.length / 2)]
    expect(mid.hr).not.toBeNull()
    expect(mid.gctMs).not.toBeNull()
    expect(mid.vertOscMm).not.toBeNull()
    expect(mid.cadenceSpm).toBeGreaterThan(150) // rpm ×2
  })
})

describe('downsampleRecords', () => {
  it('caps to the target while keeping the first and last point', () => {
    const { records } = parseFixture()
    const sampled = downsampleRecords(records, 56)
    expect(sampled.length).toBe(56)
    expect(sampled[0]).toBe(records[0])
    expect(sampled[sampled.length - 1]).toBe(records[records.length - 1])
  })

  it('returns the input unchanged when it is already small', () => {
    const { records } = parseFixture()
    const small = records.slice(0, 10)
    expect(downsampleRecords(small, 56)).toHaveLength(10)
  })
})
