// Health-record data model + mock generators (contract C-9).
// Five raw-value series (device-stored, no system-side derivation, per design §4):
// sleep / weight / resting HR / HRV, plus habit factors keyed by date.
// Everything is deterministic (fixed seed + fixed anchor) so unit tests never
// depend on wall-clock time — same pattern as activities/activityData.ts.

// ---- record types -------------------------------------------------------------

export type SleepRecord = {
  date: string // YYYY-MM-DD
  deepMin: number
  lightMin: number
  remMin: number
  totalMin: number // deep + light + rem (shown, not recomputed by any metric)
  restingHr: number // 静息心率 travels with the sleep detail per design §4
}

export type WeightRecord = {
  date: string
  weightKg: number
  bodyFatPct: number
  muscleKg: number
  waterPct: number
}

export type RestingHrRecord = {
  date: string
  restingHr: number
  nightlyMinHr: number // 夜间最低
}

export type HrvRecord = {
  date: string
  hrvMs: number // nightly average HRV
}

// ---- deterministic generators -------------------------------------------------

// mulberry32 — a tiny seeded PRNG so each series is identical every run.
function mulberry32(seed: number): () => number {
  let a = seed
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

// Fixed anchor (not `new Date()`) keeps generated dates stable for tests. Shared
// with activityData's anchor so "今天" is consistent across the app's mock data.
const ANCHOR_MS = Date.parse('2026-07-11T00:00:00Z')
const DAY_MS = 86_400_000

function dateFor(offsetDays: number): string {
  return new Date(ANCHOR_MS - offsetDays * DAY_MS).toISOString().slice(0, 10)
}

// The demo "today" (design §4: habit date defaults to 当天). Deterministic so the
// HabitPicker's default date is stable in tests.
export const HEALTH_TODAY = dateFor(0)

// 90 days of health data (design §8). Row lower bounds required by contract C-9:
// weight / resting HR / HRV each ≥30, sleep ≥14 — 90 clears all of them.
const DAYS = 90

// Index 0 = most recent day (offset 0), matching the activities list ordering.
function offsets(): number[] {
  return Array.from({ length: DAYS }, (_, i) => i)
}

export function generateSleep(): SleepRecord[] {
  const rnd = mulberry32(21)
  return offsets().map((off) => {
    const deepMin = Math.round(55 + rnd() * 45) // 55–100
    const lightMin = Math.round(190 + rnd() * 80) // 190–270
    const remMin = Math.round(60 + rnd() * 50) // 60–110
    return {
      date: dateFor(off),
      deepMin,
      lightMin,
      remMin,
      totalMin: deepMin + lightMin + remMin,
      restingHr: Math.round(46 + rnd() * 12), // 46–58
    }
  })
}

export function generateWeight(): WeightRecord[] {
  const rnd = mulberry32(37)
  return offsets().map((off) => ({
    date: dateFor(off),
    // Gentle downward trend toward "today" plus daily noise.
    weightKg: +(67.5 + off * 0.012 + (rnd() - 0.5) * 0.7).toFixed(1),
    bodyFatPct: +(14 + rnd() * 4).toFixed(1), // 14–18 %
    muscleKg: +(31 + rnd() * 2.5).toFixed(1),
    waterPct: +(55 + rnd() * 6).toFixed(1), // 55–61 %
  }))
}

export function generateRestingHr(): RestingHrRecord[] {
  const rnd = mulberry32(53)
  return offsets().map((off) => {
    const restingHr = Math.round(45 + rnd() * 13) // 45–58
    return {
      date: dateFor(off),
      restingHr,
      nightlyMinHr: restingHr - (2 + Math.round(rnd() * 4)), // 2–6 bpm lower
    }
  })
}

export function generateHrv(): HrvRecord[] {
  const rnd = mulberry32(67)
  return offsets().map((off) => ({
    date: dateFor(off),
    hrvMs: Math.round(48 + rnd() * 45), // 48–93 ms
  }))
}

// ---- habit factors ------------------------------------------------------------

export type HabitFactor = { id: string; label: string }
export type HabitGroup = { id: string; label: string; factors: HabitFactor[] }

// Preset factor list, four time-of-day groups (design §4: 早上/中午/晚上/全天).
// Not user-editable in v1.0 (design §9 遗留建议).
export const HABIT_GROUPS: readonly HabitGroup[] = [
  {
    id: 'morning',
    label: '早上',
    factors: [
      { id: 'coffee', label: '咖啡' },
      { id: 'fasted', label: '空腹训练' },
    ],
  },
  {
    id: 'noon',
    label: '中午',
    factors: [
      { id: 'nap', label: '午睡' },
      { id: 'sedentary', label: '久坐' },
    ],
  },
  {
    id: 'evening',
    label: '晚上',
    factors: [
      { id: 'alcohol', label: '酒精' },
      { id: 'reading', label: '看书' },
      { id: 'latenight', label: '熬夜' },
    ],
  },
  {
    id: 'allday',
    label: '全天',
    factors: [
      { id: 'intensity', label: '运动强度' },
      { id: 'hydration', label: '多饮水' },
    ],
  },
] as const

// Records stored by date → selected factor ids (design §4: 按日期存储). Seeded
// with the 3 most recent days (design §8: 3 天习惯记录) so the demo opens with a
// non-zero 已记录计数 and the default date already shows selections.
export type HabitRecords = Record<string, string[]>

export function generateHabitSeed(): HabitRecords {
  return {
    [dateFor(0)]: ['coffee', 'sedentary', 'reading', 'intensity'],
    [dateFor(1)]: ['coffee', 'alcohol', 'latenight'],
    [dateFor(2)]: ['fasted', 'nap', 'hydration'],
  }
}

// Number of dates with at least one recorded factor (已记录计数).
export function recordedDayCount(records: HabitRecords): number {
  return Object.values(records).filter((ids) => ids.length > 0).length
}

// ---- display formatters -------------------------------------------------------

// Duration minutes → "Xh YYm" (sleep totals read as hours; per-stage stays min).
export function formatSleepHm(min: number): string {
  const h = Math.floor(min / 60)
  const m = min % 60
  return `${h}h ${String(m).padStart(2, '0')}m`
}

// Short month-day label for chart x-axis ticks.
export function shortDate(date: string): string {
  return date.slice(5) // "MM-DD"
}
