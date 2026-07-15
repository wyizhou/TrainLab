import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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
        avgPaceSecPerKm: 398,
        avgPowerW: 244,
      },
      {
        index: 1,
        distanceM: 400,
        durationSec: 130,
        avgHr: 150,
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
  it('annotates metric sections with FIT field names and shows raw training effects', () => {
    render(<ActivityDetail activity={activity} parsed={makeParsed()} />)
    expect(screen.getByText('avg_heart_rate')).toBeInTheDocument()
    expect(screen.getByText('total_training_effect')).toBeInTheDocument()
    expect(screen.getByText('normalized_power')).toBeInTheDocument()
    // Training effect renders the raw stored value.
    const section = screen.getByText('total_training_effect').closest('.metric-section')
    expect(section).toHaveTextContent('2.7')
  })

  it('renders the running set of 8 curves and toggles to the per-second table', async () => {
    const user = userEvent.setup()
    render(<ActivityDetail activity={activity} parsed={makeParsed()} />)

    // Default curve mode: 8 charts for a run.
    const curve = screen.getByTestId('series-curve')
    expect(within(curve).getAllByTestId('ts-chart')).toHaveLength(8)
    expect(screen.queryByTestId('series-table')).not.toBeInTheDocument()

    await user.click(screen.getByTestId('mode-table'))
    expect(screen.getByTestId('series-table')).toBeInTheDocument()
    expect(screen.getByTestId('record-table')).toBeInTheDocument()
    expect(screen.queryByTestId('series-curve')).not.toBeInTheDocument()
  })

  it('renders the HR-zone bars and the laps table with an average-power column', () => {
    render(<ActivityDetail activity={activity} parsed={makeParsed()} />)
    expect(screen.getAllByTestId('hr-zone-row')).toHaveLength(5)
    const laps = screen.getByTestId('laps-table')
    expect(laps).toHaveTextContent('平均功率')
    expect(screen.getAllByTestId('lap-row')).toHaveLength(2)
    expect(laps).toHaveTextContent('244 W')
  })

  it('renders "--" for FIT fields the sample lacks', () => {
    render(<ActivityDetail activity={activity} parsed={makeParsed({ maxPowerW: null })} />)
    const section = screen.getByText('max_power').closest('.metric-section')
    expect(section).toHaveTextContent('--')
  })

  it('fires the download callback with the activity id', async () => {
    const user = userEvent.setup()
    const onDownload = vi.fn()
    render(<ActivityDetail activity={activity} parsed={makeParsed()} onDownload={onDownload} />)
    await user.click(screen.getByTestId('detail-download'))
    expect(onDownload).toHaveBeenCalledWith('a0')
  })

  it('falls back to the list summary and empty notes without a parsed FIT', () => {
    render(<ActivityDetail activity={activity} parsed={null} />)
    // Basics still come from the list row.
    const hr = screen.getByText('avg_heart_rate').closest('.metric-section')
    expect(hr).toHaveTextContent('152 bpm')
    expect(screen.getByText('该记录无逐秒原始数据')).toBeInTheDocument()
    expect(screen.getByText('该记录无分段数据')).toBeInTheDocument()
  })
})
