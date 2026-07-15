import { describe, expect, it } from 'vitest'
import {
  generateHabitSeed,
  generateHrv,
  generateRestingHr,
  generateSleep,
  generateWeight,
  HABIT_GROUPS,
  HEALTH_TODAY,
  recordedDayCount,
} from './healthData'

describe('health mock generators', () => {
  it('meets the contract C-9 row lower bounds', () => {
    // weight / resting HR / HRV each ≥30 rows; sleep ≥14.
    expect(generateSleep().length).toBeGreaterThanOrEqual(14)
    expect(generateWeight().length).toBeGreaterThanOrEqual(30)
    expect(generateRestingHr().length).toBeGreaterThanOrEqual(30)
    expect(generateHrv().length).toBeGreaterThanOrEqual(30)
  })

  it('is deterministic (fixed seed + anchor)', () => {
    expect(generateWeight()).toEqual(generateWeight())
    expect(generateSleep()[0].date).toBe(HEALTH_TODAY)
  })

  it('reports sleep totals as the sum of the three stages', () => {
    const first = generateSleep()[0]
    expect(first.totalMin).toBe(first.deepMin + first.lightMin + first.remMin)
  })

  it('exposes four habit groups covering the preset factors', () => {
    expect(HABIT_GROUPS).toHaveLength(4)
    const factorIds = HABIT_GROUPS.flatMap((g) => g.factors.map((f) => f.id))
    expect(factorIds).toEqual(expect.arrayContaining(['coffee', 'nap', 'alcohol', 'intensity']))
  })

  it('seeds three recorded habit days and counts only non-empty dates', () => {
    const seed = generateHabitSeed()
    expect(recordedDayCount(seed)).toBe(3)
    expect(recordedDayCount({ ...seed, '2026-01-01': [] })).toBe(3)
  })
})
