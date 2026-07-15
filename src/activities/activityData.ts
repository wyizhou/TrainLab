// Activity records data model + display formatters (contract C-7).
// The list is front-end mock data (G-mock); ~70 activities across ~180 days.
// The first row (晨间轻松跑) is a placeholder here — requirement 008 (C-8)
// replaces it with the real FIT parse. Everything is deterministic (fixed seed
// + fixed anchor date) so unit tests never depend on wall-clock time.

export type ActivityType = '跑步' | '骑行' | '游泳' | '力量' | '越野跑'
export type ActivitySource = '佳明CN' | '佳明国际' | 'FIT上传'

export type Activity = {
  id: string
  date: string // YYYY-MM-DD
  type: ActivityType
  name: string
  distanceKm: number | null // null for strength sessions
  durationSec: number
  avgHr: number
  paceSecPerKm: number | null // run / trail
  pace100Sec: number | null // swim (seconds per 100m)
  powerW: number | null // ride
  source: ActivitySource
}

// The list's first row is the real FIT-backed activity (contract C-8). Its
// summary values are taken from tests/fixtures/614797758_ACTIVITY.fit and are
// asserted against a live @garmin/fitsdk parse in fitParser.test.ts, so the row
// provably equals the parsed FIT (distance 5081.39 m, timer 1887.163 s).
export const FIT_ACTIVITY_ID = 'a0'
export const FIT_A0 = {
  distanceKm: 5.08, // 5081.39 m rounded to display precision
  durationSec: 1887, // total_timer_time 1887.163 s
  avgHr: 152,
  paceSecPerKm: 371, // 1887.163 s / 5.08139 km
} as const

// The filter capsules; 全部 is the default (no filter). Order matches C-7.
export const TYPE_FILTERS = ['全部', '跑步', '骑行', '游泳', '力量', '越野跑'] as const
export type TypeFilter = (typeof TYPE_FILTERS)[number]

// Maps a type to a stable CSS class slug for its colour dot. The raw colours
// live in the token module (G-token); the dot picks one via a modifier class.
export const TYPE_DOT_SLUG: Record<ActivityType, string> = {
  跑步: 'run',
  骑行: 'ride',
  游泳: 'swim',
  力量: 'strength',
  越野跑: 'trail',
}

// ---- deterministic generators -------------------------------------------------

// mulberry32 — a tiny seeded PRNG so the dataset is identical every run.
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

// Fixed anchor (not `new Date()`) keeps the generated dates stable for tests.
const ANCHOR_MS = Date.parse('2026-07-09T00:00:00Z')
const DAY_MS = 86_400_000

function dateFor(offsetDays: number): string {
  return new Date(ANCHOR_MS - offsetDays * DAY_MS).toISOString().slice(0, 10)
}

export function generateActivities(): Activity[] {
  const acts: Activity[] = []
  let seq = 0

  const mkRun = (
    off: number,
    name: string,
    dist: number,
    paceSec: number,
    aHr: number,
    src: ActivitySource,
    type: ActivityType = '跑步',
  ) =>
    acts.push({
      id: `a${seq++}`,
      date: dateFor(off),
      type,
      name,
      distanceKm: dist,
      durationSec: Math.round(dist * paceSec),
      avgHr: aHr,
      paceSecPerKm: paceSec,
      pace100Sec: null,
      powerW: null,
      source: src,
    })

  const mkRide = (
    off: number,
    name: string,
    dist: number,
    kmh: number,
    pwr: number,
    aHr: number,
    src: ActivitySource,
  ) =>
    acts.push({
      id: `a${seq++}`,
      date: dateFor(off),
      type: '骑行',
      name,
      distanceKm: dist,
      durationSec: Math.round((dist / kmh) * 3600),
      avgHr: aHr,
      paceSecPerKm: null,
      pace100Sec: null,
      powerW: pwr,
      source: src,
    })

  const mkSwim = (
    off: number,
    name: string,
    dist: number,
    pace100: number,
    aHr: number,
    src: ActivitySource,
  ) =>
    acts.push({
      id: `a${seq++}`,
      date: dateFor(off),
      type: '游泳',
      name,
      distanceKm: dist,
      durationSec: Math.round(dist * 10 * pace100),
      avgHr: aHr,
      paceSecPerKm: null,
      pace100Sec: pace100,
      powerW: null,
      source: src,
    })

  const mkStr = (off: number, name: string, durMin: number, aHr: number, src: ActivitySource) =>
    acts.push({
      id: `a${seq++}`,
      date: dateFor(off),
      type: '力量',
      name,
      distanceKm: null,
      durationSec: durMin * 60,
      avgHr: aHr,
      paceSecPerKm: null,
      pace100Sec: null,
      powerW: null,
      source: src,
    })

  // Curated recent activities (mirrors the design source of truth). a0 is the
  // "晨间轻松跑" slot, filled from the real FIT parse (contract C-8, FIT_A0).
  acts.push({
    id: `a${seq++}`,
    date: dateFor(0),
    type: '跑步',
    name: '晨间轻松跑',
    distanceKm: FIT_A0.distanceKm,
    durationSec: FIT_A0.durationSec,
    avgHr: FIT_A0.avgHr,
    paceSecPerKm: FIT_A0.paceSecPerKm,
    pace100Sec: null,
    powerW: null,
    source: '佳明CN',
  })
  mkRide(1, '间歇功率课', 45.3, 29.5, 212, 151, '佳明CN')
  mkSwim(2, '泳池有氧', 2.0, 145, 128, '佳明国际')
  mkStr(3, '下肢力量', 55, 112, '佳明CN')
  mkRun(4, '山地越野', 15.6, 456, 149, '佳明国际', '越野跑')
  mkRun(5, '节奏跑 6×1km', 12.1, 292, 156, '佳明CN')
  mkRide(7, '有氧耐力骑', 78.4, 28.5, 186, 138, '佳明CN')
  mkRun(9, '长距离慢跑', 21.1, 320, 145, '佳明CN')
  mkSwim(11, '技术课', 1.5, 160, 120, '佳明国际')
  mkRun(14, '恢复跑', 6.0, 340, 128, 'FIT上传')

  // Programmatic fill across ~180 days so pagination has real volume.
  const rnd = mulberry32(7)
  const runNames = ['轻松跑', '有氧跑', '间歇训练', '节奏跑', '长距离跑', '渐加速跑', '恢复跑']
  const rideNames = ['有氧骑行', '间歇骑', '长途骑行', '恢复骑', '爬坡训练']
  const swimNames = ['泳池训练', '有氧游', '技术课']
  const strNames = ['力量训练', '核心训练', '上肢力量']
  const trailNames = ['越野跑', '山地越野', '丘陵越野']
  const pick = (list: string[]) => list[Math.floor(rnd() * list.length)]
  const pickSource = (): ActivitySource =>
    rnd() < 0.72 ? '佳明CN' : rnd() < 0.7 ? '佳明国际' : 'FIT上传'

  let off = 16
  while (acts.length < 104) {
    const r = rnd()
    const src = pickSource()
    if (r < 0.42) {
      mkRun(
        off,
        pick(runNames),
        +(5 + rnd() * 17).toFixed(2),
        Math.round(280 + rnd() * 70),
        Math.round(130 + rnd() * 28),
        src,
      )
    } else if (r < 0.65) {
      mkRide(
        off,
        pick(rideNames),
        +(30 + rnd() * 70).toFixed(1),
        +(26 + rnd() * 7).toFixed(1),
        Math.round(170 + rnd() * 70),
        Math.round(130 + rnd() * 26),
        src,
      )
    } else if (r < 0.78) {
      mkSwim(
        off,
        pick(swimNames),
        +(1 + rnd() * 2).toFixed(1),
        Math.round(135 + rnd() * 35),
        Math.round(115 + rnd() * 20),
        src,
      )
    } else if (r < 0.9) {
      mkStr(off, pick(strNames), Math.round(35 + rnd() * 30), Math.round(100 + rnd() * 20), src)
    } else {
      mkRun(
        off,
        pick(trailNames),
        +(9 + rnd() * 10).toFixed(1),
        Math.round(420 + rnd() * 80),
        Math.round(140 + rnd() * 16),
        src,
        '越野跑',
      )
    }
    off += 1 + Math.floor(rnd() * 3)
  }

  return acts
}

// ---- display formatters -------------------------------------------------------

const DASH = '—'

export function formatDistance(km: number | null): string {
  return km === null ? DASH : `${km.toFixed(1)} km`
}

export function formatActivityDate(date: string): string {
  const parsed = new Date(`${date}T00:00:00Z`)
  const weekdays = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
  return `${date.slice(5)} ${weekdays[parsed.getUTCDay()]}`
}

export function formatDuration(sec: number): string {
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = sec % 60
  const mm = String(m).padStart(2, '0')
  const ss = String(s).padStart(2, '0')
  return h > 0 ? `${h}:${mm}:${ss}` : `${m}:${ss}`
}

function formatClock(totalSec: number, unit: string): string {
  const m = Math.floor(totalSec / 60)
  const s = Math.round(totalSec % 60)
  return `${m}'${String(s).padStart(2, '0')}"/${unit}`
}

// The "配速 / 功率" column: pace for run/trail (per km) and swim (per 100m),
// power for rides, and "--" for strength.
export function formatPaceOrPower(a: Activity): string {
  if (a.paceSecPerKm !== null) return formatClock(a.paceSecPerKm, 'km')
  if (a.pace100Sec !== null) return formatClock(a.pace100Sec, '100m')
  if (a.powerW !== null) return `${a.powerW} W`
  return DASH
}

// The simulated FIT filename for an activity (download is mock-only, G-mock).
export function fitFileName(a: Activity): string {
  return `${a.date}_${a.id}.fit`
}
