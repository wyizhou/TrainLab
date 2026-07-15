// 双账号合并去重模型 (contract C-12). When a second Garmin region (国际区) is
// connected its activities are reconciled against the already-synced 中国区
// records. Records that share the same 开始时间 + 时长 are the same session
// recorded twice and are auto-deduped (keeping a single record whose 来源标注
// preserves both regions). Records that are close but not identical cannot be
// auto-decided and surface as 冲突组 for the user to resolve one by one.
// Everything here is front-end mock (G-mock); no real network.

import { type ActivitySource, type ActivityType } from '../activities/activityData'

// ---- model --------------------------------------------------------------------

export type ConflictRegion = 'cn' | 'global'

export const REGION_LABEL: Record<ConflictRegion, string> = {
  cn: '中国区',
  global: '国际区',
}

// The 来源标注 written onto the kept record for each region.
export const REGION_SOURCE: Record<ConflictRegion, ActivitySource> = {
  cn: '佳明CN',
  global: '佳明国际',
}

// One imported candidate record. startTime is 'YYYY-MM-DDTHH:mm' (local) so the
// dedup diff is deterministic and does not depend on wall-clock time.
export type ImportRecord = {
  id: string
  region: ConflictRegion
  startTime: string
  durationSec: number
  name: string
  type: ActivityType
  distanceKm: number | null
}

// A record kept after reconciliation, annotated with the region source(s) it
// came from (both regions when auto-deduped — 来源标注保留).
export type MergedRecord = {
  id: string
  startTime: string
  durationSec: number
  name: string
  type: ActivityType
  distanceKm: number | null
  sources: ActivitySource[]
}

export type ConflictSide = {
  id: string
  region: ConflictRegion
  source: ActivitySource
  startTime: string
  durationSec: number
  name: string
  type: ActivityType
  distanceKm: number | null
}

// A suspected-duplicate pair that could not be auto-decided; the user keeps one.
export type ConflictGroup = {
  id: string
  cn: ConflictSide
  global: ConflictSide
}

export type DedupeResult = {
  merged: MergedRecord[]
  conflicts: ConflictGroup[]
}

// ---- dedup rule ---------------------------------------------------------------

// Fuzzy window: a 中国区 / 国际区 pair within these bounds (but not identical)
// is a suspected — not certain — duplicate, so it becomes a conflict group.
const FUZZY_START_MS = 5 * 60 * 1000 // 开始时间 within 5 minutes
const FUZZY_DURATION_SEC = 60 // 时长 within 60 seconds

function epoch(startTime: string): number {
  return Date.parse(startTime)
}

function isExact(a: ImportRecord, b: ImportRecord): boolean {
  return a.startTime === b.startTime && a.durationSec === b.durationSec
}

function isFuzzy(a: ImportRecord, b: ImportRecord): boolean {
  if (isExact(a, b)) return false
  return (
    Math.abs(epoch(a.startTime) - epoch(b.startTime)) <= FUZZY_START_MS &&
    Math.abs(a.durationSec - b.durationSec) <= FUZZY_DURATION_SEC
  )
}

function toSide(r: ImportRecord): ConflictSide {
  return {
    id: r.id,
    region: r.region,
    source: REGION_SOURCE[r.region],
    startTime: r.startTime,
    durationSec: r.durationSec,
    name: r.name,
    type: r.type,
    distanceKm: r.distanceKm,
  }
}

function toMerged(r: ImportRecord, sources: ActivitySource[]): MergedRecord {
  return {
    id: r.id,
    startTime: r.startTime,
    durationSec: r.durationSec,
    name: r.name,
    type: r.type,
    distanceKm: r.distanceKm,
    sources,
  }
}

// Reconcile 中国区 + 国际区 imports. Exact 开始时间+时长 matches auto-dedup into a
// single merged record carrying both sources; near-matches become conflicts;
// everything else passes through with its own single source.
export function dedupeImports(records: ImportRecord[]): DedupeResult {
  const cn = records.filter((r) => r.region === 'cn')
  const global = records.filter((r) => r.region === 'global')
  const merged: MergedRecord[] = []
  const conflicts: ConflictGroup[] = []
  const usedGlobal = new Set<string>()

  for (const c of cn) {
    const exact = global.find((g) => !usedGlobal.has(g.id) && isExact(c, g))
    if (exact) {
      usedGlobal.add(exact.id)
      merged.push(toMerged(c, [REGION_SOURCE.cn, REGION_SOURCE.global]))
      continue
    }
    const fuzzy = global.find((g) => !usedGlobal.has(g.id) && isFuzzy(c, g))
    if (fuzzy) {
      usedGlobal.add(fuzzy.id)
      conflicts.push({ id: `conf-${c.id}-${fuzzy.id}`, cn: toSide(c), global: toSide(fuzzy) })
      continue
    }
    merged.push(toMerged(c, [REGION_SOURCE.cn]))
  }

  for (const g of global) {
    if (!usedGlobal.has(g.id)) merged.push(toMerged(g, [REGION_SOURCE.global]))
  }

  return { merged, conflicts }
}

// Apply the user's per-group choice: keep the chosen region's record with its
// own source annotation and drop the other.
export function resolveConflict(group: ConflictGroup, keep: ConflictRegion): MergedRecord {
  const side = group[keep]
  return {
    id: side.id,
    startTime: side.startTime,
    durationSec: side.durationSec,
    name: side.name,
    type: side.type,
    distanceKm: side.distanceKm,
    sources: [side.source],
  }
}

// ---- demo data ----------------------------------------------------------------

// Fixed demo import set (design §5.2). Reconciling it yields exactly two
// conflict groups (演示：连接国际区后出现 2 组冲突), one auto-deduped pair, and a
// couple of unique pass-throughs — so demoConflictGroups() derives from the same
// rule the unit tests exercise rather than being hand-listed.
export function demoImportRecords(): ImportRecord[] {
  return [
    // exact duplicate → auto-deduped (来源标注保留 both regions)
    {
      id: 'cn-1',
      region: 'cn',
      startTime: '2026-07-09T07:15',
      durationSec: 3600,
      name: '晨间轻松跑',
      type: '跑步',
      distanceKm: 10.0,
    },
    {
      id: 'gl-1',
      region: 'global',
      startTime: '2026-07-09T07:15',
      durationSec: 3600,
      name: '晨跑',
      type: '跑步',
      distanceKm: 10.02,
    },

    // fuzzy pair #1 → conflict (Δ开始 2 分钟, Δ时长 40 秒)
    {
      id: 'cn-2',
      region: 'cn',
      startTime: '2026-07-06T18:30',
      durationSec: 2700,
      name: '傍晚配速跑',
      type: '跑步',
      distanceKm: 8.5,
    },
    {
      id: 'gl-2',
      region: 'global',
      startTime: '2026-07-06T18:32',
      durationSec: 2740,
      name: '配速跑',
      type: '跑步',
      distanceKm: 8.6,
    },

    // fuzzy pair #2 → conflict (Δ开始 0, Δ时长 45 秒)
    {
      id: 'cn-3',
      region: 'cn',
      startTime: '2026-07-03T06:50',
      durationSec: 5400,
      name: '长距离骑行',
      type: '骑行',
      distanceKm: 45.0,
    },
    {
      id: 'gl-3',
      region: 'global',
      startTime: '2026-07-03T06:50',
      durationSec: 5445,
      name: '耐力骑',
      type: '骑行',
      distanceKm: 45.2,
    },

    // unique 国际区 record → passes through
    {
      id: 'gl-4',
      region: 'global',
      startTime: '2026-07-01T12:00',
      durationSec: 1800,
      name: '泳池训练',
      type: '游泳',
      distanceKm: 2.0,
    },
  ]
}

export function demoConflictGroups(): ConflictGroup[] {
  return dedupeImports(demoImportRecords()).conflicts
}

// ---- display formatters -------------------------------------------------------

// '2026-07-06T18:32' → '2026-07-06 18:32' (drop the ISO 'T' separator).
export function formatStartTime(startTime: string): string {
  return startTime.replace('T', ' ')
}
