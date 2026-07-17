import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { ActivityDetailPage } from './ActivityDetailPage'
import type { ParsedActivity } from '../activities/fitParser'

function parsedStub(): ParsedActivity {
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
    },
    records: [
      {
        tSec: 0,
        distanceM: 1.4,
        speedMps: 1.2,
        paceSecPerKm: 833,
        hr: 101,
        powerW: 24,
        cadenceSpm: 134,
        altitudeM: 498,
        temperatureC: 32,
        gctMs: null,
        vertOscMm: null,
      },
    ],
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

function renderAt(path: string, loadFit?: () => Promise<ParsedActivity>) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/activities/:id" element={<ActivityDetailPage loadFit={loadFit} />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('ActivityDetailPage', () => {
  it('shows a loading state then the parsed FIT detail for the FIT-backed row', async () => {
    renderAt('/activities/a0', () => Promise.resolve(parsedStub()))
    expect(screen.getByTestId('detail-loading')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByTestId('detail-loading')).not.toBeInTheDocument())
    expect(screen.getByTestId('detail-panel-overview')).toBeInTheDocument()
    expect(screen.getByText('record.heart_rate')).toBeInTheDocument()
  })

  it('renders a mock activity from the summary without invoking the FIT loader', () => {
    const loadFit = vi.fn(() => Promise.resolve(parsedStub()))
    renderAt('/activities/a1', loadFit)
    expect(loadFit).not.toHaveBeenCalled()
    expect(screen.getByTestId('activity-detail')).toBeInTheDocument()
    expect(screen.getByTestId('activity-detail')).toHaveAttribute('data-profile', 'cycling')
  })

  it('resolves a stable hidden design profile without invoking the FIT loader', () => {
    const loadFit = vi.fn(() => Promise.resolve(parsedStub()))
    renderAt('/activities/profile-hike', loadFit)
    expect(loadFit).not.toHaveBeenCalled()
    expect(screen.getByTestId('activity-detail')).toHaveAttribute('data-profile', 'hike')
    expect(screen.getByText('高海拔徒步')).toBeInTheDocument()
  })

  it('surfaces an error note when parsing fails', async () => {
    renderAt('/activities/a0', () => Promise.reject(new Error('bad')))
    expect(await screen.findByTestId('detail-error')).toBeInTheDocument()
  })

  it('shows a not-found message for an unknown id', () => {
    renderAt('/activities/does-not-exist')
    expect(screen.getByText('未找到该运动记录。')).toBeInTheDocument()
  })
})
