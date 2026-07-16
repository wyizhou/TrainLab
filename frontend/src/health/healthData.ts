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
  maxHrvMs: number
  restingHr: number
}

// ---- deterministic generators -------------------------------------------------

// Matches the deterministic generator embedded in the exported v3.2 prototype.
function seeded(seed: number): () => number {
  let value = seed
  return () => {
    value = (value * 9301 + 49297) % 233280
    return value / 233280
  }
}

// Fixed anchor (not `new Date()`) keeps generated dates stable for tests. Shared
// with activityData's anchor so "今天" is consistent across the app's mock data.
const ANCHOR_MS = Date.parse('2026-07-09T00:00:00Z')
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

type HealthSeries = {
  sleep: SleepRecord[]
  weight: WeightRecord[]
  restingHr: RestingHrRecord[]
  hrv: HrvRecord[]
}

function buildHealthSeries(): HealthSeries {
  const rnd = seeded(42)
  const sleepOldest = Array.from({ length: DAYS }, (_, index) => {
    const offset = DAYS - 1 - index
    const deepMin = Math.round(+(1.1 + rnd() * 0.9).toFixed(1) * 60)
    const lightMin = Math.round(+(3.4 + rnd() * 1.2).toFixed(1) * 60)
    const remMin = Math.round(+(1 + rnd() * 0.9).toFixed(1) * 60)
    return {
      date: dateFor(offset),
      deepMin,
      lightMin,
      remMin,
      totalMin: deepMin + lightMin + remMin,
      restingHr: Math.round(44 + rnd() * 8),
    }
  })
  const weightOldest = Array.from({ length: DAYS }, (_, index) => {
    const offset = DAYS - 1 - index
    return {
      date: dateFor(offset),
      weightKg: +(69.2 - index * 0.008 + (rnd() - 0.5) * 0.5).toFixed(1),
      bodyFatPct: +(14.5 + (rnd() - 0.5) * 1.2).toFixed(1),
      muscleKg: +(54.2 + (rnd() - 0.5) * 0.6).toFixed(1),
      waterPct: +(58.5 + (rnd() - 0.5) * 1.5).toFixed(1),
    }
  })
  const hrvOldest = Array.from({ length: DAYS }, (_, index) => {
    const offset = DAYS - 1 - index
    const hrvMs = Math.round(52 + Math.sin(index / 4) * 7 + (rnd() - 0.5) * 8)
    const restingHr = Math.round(44 + rnd() * 7)
    return {
      date: dateFor(offset),
      hrvMs,
      maxHrvMs: hrvMs + Math.round(8 + rnd() * 10),
      restingHr,
      nightlyMinHr: restingHr - Math.round(3 + rnd() * 4),
    }
  })
  return {
    sleep: sleepOldest.reverse(),
    weight: weightOldest.reverse(),
    restingHr: hrvOldest
      .map(({ date, restingHr, nightlyMinHr }) => ({ date, restingHr, nightlyMinHr }))
      .reverse(),
    hrv: hrvOldest
      .map(({ date, hrvMs, maxHrvMs, restingHr }) => ({
        date,
        hrvMs,
        maxHrvMs,
        restingHr,
      }))
      .reverse(),
  }
}

const HEALTH_SERIES = buildHealthSeries()

export function generateSleep(): SleepRecord[] {
  return HEALTH_SERIES.sleep.map((record) => ({ ...record }))
}

export function generateWeight(): WeightRecord[] {
  return HEALTH_SERIES.weight.map((record) => ({ ...record }))
}

export function generateRestingHr(): RestingHrRecord[] {
  return HEALTH_SERIES.restingHr.map((record) => ({ ...record }))
}

export function generateHrv(): HrvRecord[] {
  return HEALTH_SERIES.hrv.map((record) => ({ ...record }))
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
      { id: 'morning-coffee', label: '咖啡' },
      { id: 'morning-light-exercise', label: '轻量运动' },
      { id: 'morning-medium-exercise', label: '中度运动' },
      { id: 'morning-hard-exercise', label: '重度运动' },
      { id: 'morning-reading', label: '看书' },
      { id: 'morning-meditation', label: '冥想' },
      { id: 'morning-stretch', label: '拉伸' },
      { id: 'morning-protein-breakfast', label: '高蛋白早餐' },
      { id: 'morning-fasted', label: '空腹训练' },
    ],
  },
  {
    id: 'noon',
    label: '中午',
    factors: [
      { id: 'noon-nap', label: '午睡' },
      { id: 'noon-coffee', label: '咖啡' },
      { id: 'noon-eating-out', label: '外食' },
      { id: 'noon-walk', label: '散步' },
      { id: 'noon-dessert', label: '奶茶/甜品' },
      { id: 'noon-light-exercise', label: '轻量运动' },
    ],
  },
  {
    id: 'evening',
    label: '晚上',
    factors: [
      { id: 'evening-reading', label: '看书' },
      { id: 'evening-stretch', label: '拉伸' },
      { id: 'evening-foot-bath', label: '泡脚' },
      { id: 'evening-meditation', label: '冥想' },
      { id: 'evening-alcohol', label: '酒精' },
      { id: 'evening-late-night', label: '熬夜(>23:30)' },
      { id: 'evening-screen', label: '长时间屏幕' },
      { id: 'evening-snack', label: '宵夜' },
    ],
  },
  {
    id: 'allday',
    label: '全天',
    factors: [
      { id: 'allday-hydration', label: '补水充足' },
      { id: 'allday-protein', label: '高蛋白饮食' },
      { id: 'allday-supplements', label: '补剂(镁/维D)' },
      { id: 'allday-sedentary', label: '久坐' },
      { id: 'allday-stress', label: '压力大' },
      { id: 'allday-sunlight', label: '户外日晒' },
    ],
  },
] as const

// Records stored by date → selected factor ids (design §4: 按日期存储). Seeded
// with the 3 most recent days (design §8: 3 天习惯记录) so the demo opens with a
// non-zero 已记录计数 and the default date already shows selections.
export type HabitRecords = Record<string, string[]>

export function generateHabitSeed(): HabitRecords {
  return {
    [dateFor(0)]: ['morning-coffee', 'morning-light-exercise', 'allday-hydration'],
    [dateFor(1)]: ['morning-coffee', 'evening-stretch', 'evening-screen', 'allday-sedentary'],
    [dateFor(2)]: ['morning-medium-exercise', 'noon-nap', 'evening-reading', 'allday-protein'],
  }
}

// Number of dates with at least one recorded factor (已记录计数).
export function recordedDayCount(records: HabitRecords): number {
  return Object.values(records).filter((ids) => ids.length > 0).length
}

export function selectedFactorCount(records: HabitRecords, date: string): number {
  return records[date]?.length ?? 0
}

// ---- display formatters -------------------------------------------------------

// Duration minutes → one-decimal hours, matching the exported prototype table.
export function formatSleepHm(min: number): string {
  return `${(min / 60).toFixed(1)} h`
}

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'] as const

export function formatHealthDate(date: string): string {
  const day = new Date(`${date}T00:00:00Z`).getUTCDay()
  return `${date.slice(5)} ${WEEKDAYS[day]}`
}

// Short month-day label for chart x-axis ticks.
export function shortDate(date: string): string {
  return date.slice(5) // "MM-DD"
}
