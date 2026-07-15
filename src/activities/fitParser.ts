// Real FIT parsing with @garmin/fitsdk (contract C-8). Turns the raw bytes of
// tests/fixtures/614797758_ACTIVITY.fit into the summary / per-second records /
// laps / HR-zone data the detail page renders. Values are FIT stored values —
// nothing here is a system-computed derived metric.

import { Decoder, Stream } from '@garmin/fitsdk'
import type { LapMesg, RecordMesg, SessionMesg, TimeInZoneMesg } from '@garmin/fitsdk'

// ---- output shape -------------------------------------------------------------

export type FitSummary = {
  sport: string
  subSport: string
  startTime: string // ISO 8601, exact FIT timestamp
  totalTimerTimeSec: number
  totalElapsedTimeSec: number
  totalDistanceM: number
  avgHr: number | null
  maxHr: number | null
  totalCalories: number | null
  avgPowerW: number | null
  maxPowerW: number | null
  normalizedPowerW: number | null
  totalAscentM: number | null
  totalDescentM: number | null
  avgSpeedMps: number | null
  maxSpeedMps: number | null
  avgCadenceSpm: number | null
  totalTrainingEffect: number | null // FIT raw stored value, not computed
  totalAnaerobicTrainingEffect: number | null // FIT raw stored value, not computed
  avgTemperatureC: number | null
  maxTemperatureC: number | null
  minTemperatureC: number | null
  avgGctMs: number | null // stance time (running dynamics)
  avgVertOscMm: number | null
  avgVerticalRatio: number | null
  avgStepLengthMm: number | null
  // Connect IQ developer fields (no native FIT equivalent).
  avgLSS: number | null // leg spring stiffness (kn/m)
  avgVILR: number | null // vertical instantaneous loading rate (bw/s)
  avgBodyYPIF: number | null // body Y peak impact force (g)
  workoutFeel: number | null // 自我评价 (0–100)
  workoutRpe: number | null // 自我评价 RPE (0–100, ÷10 = 1–10)
}

// One per-second record row (design 3.2 逐秒数据表 / 降采样曲线).
export type FitRecordPoint = {
  tSec: number // seconds elapsed from start
  distanceM: number | null
  speedMps: number | null
  paceSecPerKm: number | null
  hr: number | null
  powerW: number | null
  cadenceSpm: number | null // running/step cadence (rpm ×2)
  altitudeM: number | null
  temperatureC: number | null
  gctMs: number | null // stance time
  vertOscMm: number | null
}

export type FitLap = {
  index: number
  distanceM: number
  durationSec: number
  avgHr: number | null
  maxHr: number | null
  avgPaceSecPerKm: number | null
  avgPowerW: number | null
}

// A single HR-zone bar: seconds spent (FIT time_in_hr_zone) + label boundaries.
export type FitHrZoneTime = {
  zone: number // 1..5
  seconds: number
}

export type ParsedActivity = {
  summary: FitSummary
  records: FitRecordPoint[]
  laps: FitLap[]
  hrZoneSeconds: FitHrZoneTime[] // Z1..Z5, from session time_in_hr_zone
}

// The number of zones the chart shows (Z1..Z5). FIT stores 7 slots.
const ZONE_COUNT = 5

// ---- value coercion helpers ---------------------------------------------------

function num(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

function isoOf(v: unknown): string {
  if (v instanceof Date) return v.toISOString()
  // FIT epoch = seconds since 1989-12-31T00:00:00Z; only used if the decoder
  // was told not to convert timestamps (it converts by default).
  if (typeof v === 'number') return new Date((v + 631065600) * 1000).toISOString()
  return ''
}

// Running cadence in steps-per-minute: FIT cadence is rpm; spm = (rpm+frac)×2.
function cadenceSpm(cadence: unknown, fractional: unknown): number | null {
  const c = num(cadence)
  if (c === null) return null
  return Math.round((c + (num(fractional) ?? 0)) * 2)
}

function paceFromSpeed(speedMps: number | null): number | null {
  return speedMps !== null && speedMps > 0 ? 1000 / speedMps : null
}

// ---- parse --------------------------------------------------------------------

export function parseFitActivity(bytes: Uint8Array): ParsedActivity {
  const decoder = new Decoder(Stream.fromByteArray(bytes))
  const { messages, errors } = decoder.read()
  if (errors.length > 0) {
    throw new Error(`FIT decode error: ${errors[0].message}`)
  }

  const session: SessionMesg = messages.sessionMesgs?.[0] ?? {}
  const dev = session.developerFields ?? {}
  const startMs = Date.parse(isoOf(session.startTime))

  const summary: FitSummary = {
    sport: typeof session.sport === 'string' ? session.sport : 'generic',
    subSport: typeof session.subSport === 'string' ? session.subSport : 'generic',
    startTime: isoOf(session.startTime),
    totalTimerTimeSec: num(session.totalTimerTime) ?? 0,
    totalElapsedTimeSec: num(session.totalElapsedTime) ?? 0,
    totalDistanceM: num(session.totalDistance) ?? 0,
    avgHr: num(session.avgHeartRate),
    maxHr: num(session.maxHeartRate),
    totalCalories: num(session.totalCalories),
    avgPowerW: num(session.avgPower),
    maxPowerW: num(session.maxPower),
    normalizedPowerW: num(session.normalizedPower),
    totalAscentM: num(session.totalAscent),
    totalDescentM: num(session.totalDescent),
    avgSpeedMps: num(session.enhancedAvgSpeed) ?? num(session.avgSpeed),
    maxSpeedMps: num(session.enhancedMaxSpeed) ?? num(session.maxSpeed),
    avgCadenceSpm: cadenceSpm(session.avgCadence ?? session.avgRunningCadence, 0),
    totalTrainingEffect: num(session.totalTrainingEffect),
    totalAnaerobicTrainingEffect: num(session.totalAnaerobicTrainingEffect),
    avgTemperatureC: num(session.avgTemperature),
    maxTemperatureC: num(session.maxTemperature),
    minTemperatureC: num(session.minTemperature),
    avgGctMs: num(session.avgStanceTime),
    avgVertOscMm: num(session.avgVerticalOscillation),
    avgVerticalRatio: num(session.avgVerticalRatio),
    avgStepLengthMm: num(session.avgStepLength),
    avgLSS: num(dev['5']),
    avgVILR: num(dev['6']),
    avgBodyYPIF: num(dev['7']),
    workoutFeel: num(session.workoutFeel),
    workoutRpe: num(session.workoutRpe),
  }

  const recordMesgs: RecordMesg[] = messages.recordMesgs ?? []
  const records: FitRecordPoint[] = recordMesgs.map((r) => {
    const ts = Date.parse(isoOf(r.timestamp))
    const speedMps = num(r.enhancedSpeed) ?? num(r.speed)
    return {
      tSec: Number.isFinite(ts) && Number.isFinite(startMs) ? Math.round((ts - startMs) / 1000) : 0,
      distanceM: num(r.distance),
      speedMps,
      paceSecPerKm: paceFromSpeed(speedMps),
      hr: num(r.heartRate),
      powerW: num(r.power),
      cadenceSpm: cadenceSpm(r.cadence, r.fractionalCadence),
      altitudeM: num(r.enhancedAltitude) ?? num(r.altitude),
      temperatureC: num(r.temperature),
      gctMs: num(r.stanceTime),
      vertOscMm: num(r.verticalOscillation),
    }
  })

  const lapMesgs: LapMesg[] = messages.lapMesgs ?? []
  const laps: FitLap[] = lapMesgs.map((l, i) => {
    const speed = num(l.enhancedAvgSpeed) ?? num(l.avgSpeed)
    return {
      index: num(l.messageIndex) ?? i,
      distanceM: num(l.totalDistance) ?? 0,
      durationSec: num(l.totalTimerTime) ?? num(l.totalElapsedTime) ?? 0,
      avgHr: num(l.avgHeartRate),
      maxHr: num(l.maxHeartRate),
      avgPaceSecPerKm: paceFromSpeed(speed),
      avgPowerW: num(l.avgPower),
    }
  })

  // HR zone bars: the session-scoped time_in_hr_zone message (raw stored value).
  const sessionTiz: TimeInZoneMesg | undefined = (messages.timeInZoneMesgs ?? []).find(
    (t) => t.referenceMesg === 'session',
  )
  const tiz = sessionTiz?.timeInHrZone ?? []
  const hrZoneSeconds: FitHrZoneTime[] = Array.from({ length: ZONE_COUNT }, (_, i) => ({
    zone: i + 1,
    seconds: num(tiz[i]) ?? 0,
  }))

  return { summary, records, laps, hrZoneSeconds }
}

// ---- downsampling (design 3.2: 逐秒 record 流降采样 56 点) ----------------------

export const DOWNSAMPLE_POINTS = 56

// Evenly picks up to `target` records spanning the full activity (first & last
// always included) for the curve view.
export function downsampleRecords(
  records: FitRecordPoint[],
  target = DOWNSAMPLE_POINTS,
): FitRecordPoint[] {
  const n = records.length
  if (n <= target) return records.slice()
  const out: FitRecordPoint[] = []
  for (let i = 0; i < target; i += 1) {
    out.push(records[Math.round((i * (n - 1)) / (target - 1))])
  }
  return out
}
