import {
  fitFileName,
  formatDistance,
  formatDuration,
  formatPaceOrPower,
  generateActivities,
  type Activity,
} from './activityData'

function make(overrides: Partial<Activity>): Activity {
  return {
    id: 'a0',
    date: '2026-07-11',
    type: '跑步',
    name: '测试',
    distanceKm: 5,
    durationSec: 1800,
    avgHr: 150,
    paceSecPerKm: 360,
    pace100Sec: null,
    powerW: null,
    source: '佳明CN',
    ...overrides,
  }
}

describe('activity formatters', () => {
  it('formats distance with two decimals and "--" for strength', () => {
    expect(formatDistance(5.08)).toBe('5.08 km')
    expect(formatDistance(null)).toBe('--')
  })

  it('formats duration as M:SS under an hour and H:MM:SS over', () => {
    expect(formatDuration(1885)).toBe('31:25')
    expect(formatDuration(3671)).toBe('1:01:11')
  })

  it('renders pace for run/swim, power for ride, "--" for strength', () => {
    expect(formatPaceOrPower(make({ paceSecPerKm: 371 }))).toBe(`6'11"/km`)
    expect(formatPaceOrPower(make({ type: '游泳', paceSecPerKm: null, pace100Sec: 145 }))).toBe(
      `2'25"/100m`,
    )
    expect(formatPaceOrPower(make({ type: '骑行', paceSecPerKm: null, powerW: 212 }))).toBe('212 W')
    expect(formatPaceOrPower(make({ type: '力量', paceSecPerKm: null, distanceKm: null }))).toBe(
      '--',
    )
  })

  it('derives a stable FIT filename', () => {
    expect(fitFileName(make({ id: 'a3', date: '2026-07-08' }))).toBe('2026-07-08_a3.fit')
  })
})

describe('generateActivities', () => {
  it('is deterministic and volume-rich enough to paginate', () => {
    const a = generateActivities()
    const b = generateActivities()
    expect(a.length).toBe(b.length)
    expect(a.length).toBeGreaterThan(60)
    expect(a.map((x) => x.id)).toEqual(b.map((x) => x.id))
  })

  it('leads with the 晨间轻松跑 slot and only uses the six contracted types', () => {
    const acts = generateActivities()
    expect(acts[0].name).toBe('晨间轻松跑')
    const allowed = new Set(['跑步', '骑行', '游泳', '力量', '越野跑'])
    expect(acts.every((x) => allowed.has(x.type))).toBe(true)
    const sources = new Set(acts.map((x) => x.source))
    expect(sources).toContain('佳明CN')
  })
})
