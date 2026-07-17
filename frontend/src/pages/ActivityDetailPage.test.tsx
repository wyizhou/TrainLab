import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom'
import { ActivityDetailPage } from './ActivityDetailPage'
import type { ParsedActivity } from '../activities/fitParser'
import * as activityApi from '../activities/activityApi'
import { AuthContext, demoUser, type AuthContextValue } from '../auth/AuthState'

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

function renderAt(path: string, loadFit?: () => Promise<ParsedActivity>, demoMode = true) {
  const auth: AuthContextValue = {
    status: 'authenticated',
    user: demoUser,
    demoMode,
    login: async () => {},
    logout: async () => {},
  }
  render(
    <MemoryRouter initialEntries={[path]}>
      <AuthContext.Provider value={auth}>
        <Routes>
          <Route path="/activities/:id" element={<ActivityDetailPage loadFit={loadFit} />} />
        </Routes>
      </AuthContext.Provider>
    </MemoryRouter>,
  )
}

describe('ActivityDetailPage', () => {
  afterEach(() => vi.restoreAllMocks())

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

  it('loads a persisted UUID into the shared v3.4 detail page', async () => {
    const id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
    const parsed = parsedStub()
    parsed.backend = {
      profile: 'run',
      parseStatus: 'complete',
      originalFileName: 'persisted.fit',
      downloadAvailable: true,
      recordCount: parsed.records.length,
      recordsSampled: false,
      segments: [],
      devices: [],
      metricDefinitions: [],
    }
    vi.spyOn(activityApi, 'loadImportedActivity').mockResolvedValue({
      activity: {
        id,
        date: '2026-07-09',
        type: '跑步',
        name: '持久化跑步',
        distanceKm: 5.08,
        durationSec: 1887,
        avgHr: 152,
        paceSecPerKm: 371,
        pace100Sec: null,
        powerW: null,
        source: 'FIT上传',
        profile: 'run',
      },
      parsed,
    })

    renderAt(`/activities/${id}`, undefined, false)
    expect(screen.getByTestId('detail-loading')).toBeInTheDocument()
    expect(await screen.findByText('持久化跑步')).toBeInTheDocument()
    expect(screen.getByTestId('activity-detail')).toHaveAttribute('data-profile', 'run')
    expect(screen.getByText('persisted.fit')).toBeInTheDocument()
  })

  it('distinguishes a transient imported-detail failure and retries successfully', async () => {
    const id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
    const parsed = parsedStub()
    parsed.backend = {
      profile: 'run',
      parseStatus: 'complete',
      originalFileName: 'retried.fit',
      downloadAvailable: true,
      recordCount: 1,
      recordsSampled: false,
      segments: [],
      devices: [],
      metricDefinitions: [],
    }
    vi.spyOn(activityApi, 'loadImportedActivity')
      .mockRejectedValueOnce(new activityApi.ActivityApiError('暂时不可用', 'internal_error', 503))
      .mockResolvedValueOnce({
        activity: {
          id,
          date: '2026-07-09',
          type: '跑步',
          name: '重试成功跑步',
          distanceKm: 5.08,
          durationSec: 1887,
          avgHr: 152,
          paceSecPerKm: 371,
          pace100Sec: null,
          powerW: null,
          source: 'FIT上传',
          profile: 'run',
        },
        parsed,
      })

    renderAt(`/activities/${id}`, undefined, false)
    expect(await screen.findByTestId('detail-load-error')).toHaveTextContent('暂时加载失败')
    expect(screen.queryByText('未找到该运动记录。')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '重新加载' }))
    expect(await screen.findByText('重试成功跑步')).toBeInTheDocument()
    expect(activityApi.loadImportedActivity).toHaveBeenCalledTimes(2)
  })

  it('shows not found only for an imported-detail 404', async () => {
    const id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
    vi.spyOn(activityApi, 'loadImportedActivity').mockRejectedValue(
      new activityApi.ActivityApiError('不存在', 'activity_not_found', 404),
    )

    renderAt(`/activities/${id}`, undefined, false)
    expect(await screen.findByText('未找到该运动记录。')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '重新加载' })).not.toBeInTheDocument()
  })

  it('does not expose design fixture routes in a real authenticated session', () => {
    const loadFit = vi.fn(() => Promise.resolve(parsedStub()))
    renderAt('/activities/a0', loadFit, false)

    expect(screen.getByText('未找到该运动记录。')).toBeInTheDocument()
    expect(loadFit).not.toHaveBeenCalled()
  })

  it('clears activity A before loading activity B on a UUID route change', async () => {
    const firstId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
    const secondId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
    const parsed = parsedStub()
    parsed.backend = {
      profile: 'run',
      parseStatus: 'complete',
      originalFileName: 'private.fit',
      downloadAvailable: true,
      recordCount: 1,
      recordsSampled: false,
      segments: [],
      devices: [],
      metricDefinitions: [],
    }
    vi.spyOn(activityApi, 'loadImportedActivity').mockImplementation((id) => {
      if (id === firstId) {
        return Promise.resolve({
          activity: {
            id,
            date: '2026-07-09',
            type: '跑步',
            name: '用户 A 私有运动',
            distanceKm: 5,
            durationSec: 1800,
            avgHr: 150,
            paceSecPerKm: 360,
            pace100Sec: null,
            powerW: null,
            source: 'FIT上传',
            profile: 'run',
          },
          parsed,
        })
      }
      return new Promise(() => {})
    })
    const auth: AuthContextValue = {
      status: 'authenticated',
      user: demoUser,
      demoMode: false,
      login: async () => {},
      logout: async () => {},
    }
    function SwitchRoute() {
      const navigate = useNavigate()
      return (
        <button type="button" onClick={() => navigate(`/activities/${secondId}`)}>
          switch route
        </button>
      )
    }
    render(
      <MemoryRouter initialEntries={[`/activities/${firstId}`]}>
        <AuthContext.Provider value={auth}>
          <SwitchRoute />
          <Routes>
            <Route path="/activities/:id" element={<ActivityDetailPage />} />
          </Routes>
        </AuthContext.Provider>
      </MemoryRouter>,
    )

    expect(await screen.findByText('用户 A 私有运动')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'switch route' }))
    expect(await screen.findByTestId('detail-loading')).toBeInTheDocument()
    expect(screen.queryByText('用户 A 私有运动')).not.toBeInTheDocument()
  })
})
