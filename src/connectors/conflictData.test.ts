import { describe, expect, it } from 'vitest'
import {
  dedupeImports,
  demoConflictGroups,
  demoImportRecords,
  resolveConflict,
  type ImportRecord,
} from './conflictData'

const rec = (over: Partial<ImportRecord>): ImportRecord => ({
  id: 'x',
  region: 'cn',
  startTime: '2026-07-06T18:30',
  durationSec: 2700,
  name: 'a',
  type: '跑步',
  distanceKm: 8.5,
  ...over,
})

describe('dedupeImports 去重规则', () => {
  it('exact 开始时间+时长 auto-dedups into one record keeping both sources', () => {
    const { merged, conflicts } = dedupeImports([
      rec({ id: 'cn-1', region: 'cn', startTime: '2026-07-09T07:15', durationSec: 3600 }),
      rec({ id: 'gl-1', region: 'global', startTime: '2026-07-09T07:15', durationSec: 3600 }),
    ])
    expect(conflicts).toHaveLength(0)
    expect(merged).toHaveLength(1)
    expect(merged[0].sources).toEqual(['佳明CN', '佳明国际'])
  })

  it('near-match (within window, not identical) becomes a conflict group', () => {
    const { merged, conflicts } = dedupeImports([
      rec({ id: 'cn-2', region: 'cn', startTime: '2026-07-06T18:30', durationSec: 2700 }),
      rec({ id: 'gl-2', region: 'global', startTime: '2026-07-06T18:32', durationSec: 2740 }),
    ])
    expect(merged).toHaveLength(0)
    expect(conflicts).toHaveLength(1)
    expect(conflicts[0].cn.source).toBe('佳明CN')
    expect(conflicts[0].global.source).toBe('佳明国际')
  })

  it('outside the window each record passes through with its own single source', () => {
    const { merged, conflicts } = dedupeImports([
      rec({ id: 'cn-3', region: 'cn', startTime: '2026-07-06T18:30', durationSec: 2700 }),
      rec({ id: 'gl-3', region: 'global', startTime: '2026-07-06T18:40', durationSec: 2700 }),
    ])
    expect(conflicts).toHaveLength(0)
    expect(merged).toHaveLength(2)
    expect(merged.map((m) => m.sources)).toEqual([['佳明CN'], ['佳明国际']])
  })

  it('duration difference beyond 60s is not a conflict', () => {
    const { conflicts } = dedupeImports([
      rec({ id: 'cn-4', region: 'cn', startTime: '2026-07-06T18:30', durationSec: 2700 }),
      rec({ id: 'gl-4', region: 'global', startTime: '2026-07-06T18:30', durationSec: 2800 }),
    ])
    expect(conflicts).toHaveLength(0)
  })
})

describe('demo data', () => {
  it('reconciling the demo import yields exactly 2 conflict groups', () => {
    expect(demoConflictGroups()).toHaveLength(2)
  })

  it('demo import also auto-dedups one pair keeping both sources', () => {
    const { merged } = dedupeImports(demoImportRecords())
    expect(merged.some((m) => m.sources.length === 2)).toBe(true)
  })
})

describe('resolveConflict', () => {
  it('keeps the chosen region with its own source annotation', () => {
    const [group] = demoConflictGroups()
    expect(resolveConflict(group, 'cn').sources).toEqual(['佳明CN'])
    expect(resolveConflict(group, 'global').sources).toEqual(['佳明国际'])
    expect(resolveConflict(group, 'global').id).toBe(group.global.id)
  })
})
