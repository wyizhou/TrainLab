import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { profileActivityById } from '../activities/activityProfiles'
import { ActivityDetail } from './ActivityDetail'
import type { Activity } from '../activities/activityData'
import type { FitRecordPoint, ParsedActivity } from '../activities/fitParser'

const activity: Activity = {
  id: 'a0',
  date: '2026-07-08',
  type: '跑步',
  name: '晨间轻松跑',
  distanceKm: 5.08,
  durationSec: 1887,
  avgHr: 152,
  paceSecPerKm: 371,
  pace100Sec: null,
  powerW: null,
  source: '佳明CN',
}

function rec(i: number): FitRecordPoint {
  return {
    tSec: i,
    distanceM: i * 3,
    speedMps: 2.7,
    paceSecPerKm: 370,
    hr: 150 + (i % 4),
    powerW: 260,
    cadenceSpm: 174,
    altitudeM: 498,
    temperatureC: 32,
    gctMs: 264,
    vertOscMm: 81,
  }
}

function makeParsed(overrides: Partial<ParsedActivity['summary']> = {}): ParsedActivity {
  return {
    summary: {
      sport: 'running',
      subSport: 'generic',
      startTime: '2026-07-08T22:41:56.000Z',
      totalTimerTimeSec: 1887.163,
      totalElapsedTimeSec: 1947.864,
      totalDistanceM: 5081.39,
      avgHr: 152,
      maxHr: 170,
      totalCalories: 344,
      avgPowerW: 265,
      maxPowerW: 310,
      normalizedPowerW: 264,
      totalAscentM: 2,
      totalDescentM: 4,
      avgSpeedMps: 2.693,
      maxSpeedMps: 3.004,
      avgCadenceSpm: 174,
      totalTrainingEffect: 2.7,
      totalAnaerobicTrainingEffect: 0,
      avgTemperatureC: 32,
      maxTemperatureC: 33,
      minTemperatureC: 31,
      avgGctMs: 264.5,
      avgVertOscMm: 81.2,
      avgVerticalRatio: 8.8,
      avgStepLengthMm: 922.6,
      avgLSS: 4.56,
      avgVILR: 39.53,
      avgBodyYPIF: 17.59,
      workoutFeel: 50,
      workoutRpe: 30,
      ...overrides,
    },
    records: Array.from({ length: 120 }, (_, i) => rec(i)),
    laps: [
      {
        index: 0,
        distanceM: 300.94,
        durationSec: 120,
        avgHr: 118,
        maxHr: 132,
        avgPaceSecPerKm: 398,
        avgPowerW: 244,
      },
      {
        index: 1,
        distanceM: 400,
        durationSec: 130,
        avgHr: 150,
        maxHr: 164,
        avgPaceSecPerKm: 360,
        avgPowerW: 260,
      },
    ],
    hrZoneSeconds: [
      { zone: 1, seconds: 68 },
      { zone: 2, seconds: 799 },
      { zone: 3, seconds: 1014 },
      { zone: 4, seconds: 5 },
      { zone: 5, seconds: 0 },
    ],
  }
}

describe('ActivityDetail', () => {
  it('renders the v3.4 overview with five tabs and six primary metrics', () => {
    render(<ActivityDetail activity={activity} parsed={makeParsed()} />)
    const tabs = screen.getByRole('navigation', { name: '详情视图' })
    expect(tabs).toBeInTheDocument()
    expect(within(tabs).getAllByRole('button')).toHaveLength(5)
    expect(document.querySelectorAll('[data-vc="activity-summary-metric"]')).toHaveLength(6)
    expect(screen.getByTestId('detail-panel-overview')).toHaveTextContent('DATA INSIGHT')
  })

  it('switches among all five profile panels', async () => {
    const user = userEvent.setup()
    render(<ActivityDetail activity={activity} parsed={makeParsed()} />)

    await user.click(screen.getByRole('button', { name: '图表' }))
    expect(screen.getByTestId('detail-panel-charts')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '分段 / 训练组' }))
    expect(screen.getByTestId('detail-panel-segments')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '设备与指标' }))
    expect(screen.getByTestId('detail-panel-devices')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '原始数据' }))
    expect(screen.getByTestId('detail-panel-raw')).toBeInTheDocument()
  })

  it('links a selected segment to its position in the chart', async () => {
    const user = userEvent.setup()
    render(<ActivityDetail activity={activity} parsed={makeParsed()} />)
    await user.click(screen.getByRole('button', { name: '分段 / 训练组' }))
    await user.click(screen.getByRole('button', { name: /第 1 圈/ }))
    expect(screen.getByTestId('detail-panel-charts')).toHaveTextContent('已联动选择分段')
    expect(document.querySelector('[data-vc="activity-chart-linked-selection"]')).not.toBeNull()
  })

  it('filters device sources and keeps the first extension group open by default', async () => {
    const user = userEvent.setup()
    render(<ActivityDetail activity={activity} parsed={makeParsed()} />)
    await user.click(screen.getByRole('button', { name: '设备与指标' }))
    expect(screen.getByRole('button', { name: /跑步动态/ })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
    await user.click(screen.getByRole('button', { name: '传感器' }))
    expect(screen.getByText('Footpod / 跑姿传感器')).toBeInTheDocument()
    expect(screen.queryByText('运动手表')).not.toBeInTheDocument()
  })

  it('fires the download callback with the activity id', async () => {
    const user = userEvent.setup()
    const onDownload = vi.fn()
    render(<ActivityDetail activity={activity} parsed={makeParsed()} onDownload={onDownload} />)
    await user.click(screen.getByTestId('detail-download'))
    expect(onDownload).toHaveBeenCalledWith('a0')
  })

  it('does not invent FIT records for an unbound profile', async () => {
    const user = userEvent.setup()
    const generic = profileActivityById('profile-generic')!
    render(<ActivityDetail activity={generic} parsed={null} />)
    expect(screen.getByTestId('detail-download')).toBeDisabled()
    expect(screen.getByText('当前没有可验证的时间构成数据。')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '原始数据' }))
    expect(screen.getByText('等待真实 FIT 数据')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('renders time composition as accessible SVG geometry from the same percentages', () => {
    render(
      <ActivityDetail
        activity={activity}
        parsed={makeParsed({ totalTimerTimeSec: 39, totalElapsedTimeSec: 100 })}
      />,
    )

    const ring = screen.getByRole('img', { name: '时间构成：跑动 39%，暂停 61%' })
    expect(ring).toHaveAttribute('viewBox', '0 0 104 104')
    const segments = ring.querySelectorAll('circle')
    expect(segments).toHaveLength(2)
    expect(segments[0]).toHaveAttribute('data-percentage', '39')
    expect(segments[1]).toHaveAttribute('data-percentage', '61')

    const [activeArc, activeRemainder] = segments[0]
      .getAttribute('stroke-dasharray')!
      .split(' ')
      .map(Number)
    expect(activeArc / (activeArc + activeRemainder)).toBeCloseTo(0.39, 8)
    expect(screen.getByText('39%')).toBeInTheDocument()
    expect(screen.getByText('61%')).toBeInTheDocument()
  })

  it.each([
    [0, 100, '时间构成：跑动 0%，暂停 100%', [0, 100]],
    [50, 100, '时间构成：跑动 50%，暂停 50%', [50, 50]],
    [100, 100, '时间构成：跑动 100%，暂停 0%', [100, 0]],
  ] as const)(
    'keeps SVG arcs and legend aligned for %i/%i composition',
    (timerSeconds, elapsedSeconds, name, percentages) => {
      render(
        <ActivityDetail
          activity={activity}
          parsed={makeParsed({
            totalTimerTimeSec: timerSeconds,
            totalElapsedTimeSec: elapsedSeconds,
          })}
        />,
      )

      const ring = screen.getByRole('img', { name })
      const segments = ring.querySelectorAll('circle')
      expect(segments).toHaveLength(2)
      expect(Array.from(segments, (segment) => Number(segment.dataset.percentage))).toEqual(
        percentages,
      )
      expect(
        Array.from(segments, (segment) => {
          const [arc, remainder] = segment.getAttribute('stroke-dasharray')!.split(' ').map(Number)
          return Math.round((arc / (arc + remainder)) * 100)
        }),
      ).toEqual(percentages)
    },
  )

  it('uses the explanatory empty state when the composition total is zero', () => {
    render(
      <ActivityDetail
        activity={activity}
        parsed={makeParsed({ totalTimerTimeSec: 0, totalElapsedTimeSec: 0 })}
      />,
    )

    expect(screen.queryByTestId('detail-composition-ring')).not.toBeInTheDocument()
    expect(screen.getByText('当前没有可验证的时间构成数据。')).toBeInTheDocument()
  })
})
