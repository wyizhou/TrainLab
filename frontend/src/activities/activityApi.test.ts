import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  isImportedActivityId,
  listImportedActivities,
  loadImportedActivity,
  deleteImportedActivity,
  updateImportedActivityName,
  uploadFitFile,
} from './activityApi'
import {
  addUploadedActivities,
  getUploadedActivities,
  resetUploadedActivities,
} from './uploadStore'
import { getSettings, resetSettings, updateSettings } from '../settings/settingsStore'

const activity = {
  id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  date: '2026-07-09',
  type: '跑步' as const,
  name: '持久化跑步',
  distanceKm: 5.08,
  durationSec: 1887,
  avgHr: 152,
  paceSecPerKm: 371,
  pace100Sec: null,
  powerW: null,
  source: 'FIT上传' as const,
  profile: 'run' as const,
}

afterEach(() => {
  vi.unstubAllGlobals()
  resetUploadedActivities()
  resetSettings()
})

describe('activity API', () => {
  it('walks cursor pages and keeps imported UUID detection strict', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ items: [activity], nextCursor: 'next' }), {
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ items: [], nextCursor: null }), {
          headers: { 'Content-Type': 'application/json' },
        }),
      )
    vi.stubGlobal('fetch', fetchMock)

    await expect(listImportedActivities()).resolves.toEqual([activity])
    expect(String(fetchMock.mock.calls[1][0])).toContain('cursor=next')
    expect(isImportedActivityId(activity.id)).toBe(true)
    expect(isImportedActivityId('profile-run')).toBe(false)
  })

  it('uploads FIT as multipart without forcing a JSON content type', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      expect(init?.body).toBeInstanceOf(FormData)
      expect(new Headers(init?.headers).has('Content-Type')).toBe(false)
      return new Response(
        JSON.stringify({
          importId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
          status: 'complete',
          deduplicated: false,
          activity,
          retryAvailable: false,
        }),
        { status: 201, headers: { 'Content-Type': 'application/json' } },
      )
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await uploadFitFile(new File([new Uint8Array([1])], 'run.fit'))
    expect(result.activity).toEqual(activity)
  })

  it('sends string and null activity names and accepts a 204 delete without JSON', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ...activity, name: '新名称' }), {
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(activity), { headers: { 'Content-Type': 'application/json' } }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)

    await updateImportedActivityName(activity.id, '新名称')
    await updateImportedActivityName(activity.id, null)
    await expect(deleteImportedActivity(activity.id)).resolves.toBeUndefined()

    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({ name: '新名称' })
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual({ name: null })
    expect(fetchMock.mock.calls[2][1]).toMatchObject({ method: 'DELETE' })
  })

  it('maps the owner detail payload into the shared ParsedActivity shape', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              activity,
              summary: {
                sport: 'running',
                subSport: 'generic',
                startTime: '2026-07-08T22:41:56Z',
                localStartTime: '2026-07-09T06:41:56',
                utcOffsetMinutes: 480,
                totalTimerTimeSec: 1887,
                totalElapsedTimeSec: 1948,
                totalDistanceM: 5081,
                avgHr: 152,
                maxHr: 170,
                totalCalories: 344,
                avgPowerW: 265,
                maxPowerW: 310,
                normalizedPowerW: 264,
                totalAscentM: 2,
                totalDescentM: 4,
                avgSpeedMps: 2.69,
                maxSpeedMps: 3,
                avgCadenceSpm: 174,
                totalTrainingEffect: 2.7,
                totalAnaerobicTrainingEffect: 0,
                avgTemperatureC: 32,
                maxTemperatureC: 33,
                minTemperatureC: 31,
                avgGctMs: 264,
                avgVertOscMm: 81,
                avgVerticalRatio: 8.8,
                avgStepLengthMm: 922,
                workoutFeel: 50,
                workoutRpe: 30,
                extraMetrics: {
                  'native:time_in_zone:session:time_in_hr_zone': [
                    68.49, 798.924, 1014.229, 4.915, 0, 0, 0,
                  ],
                },
              },
              records: [],
              recordCount: 1890,
              recordsSampled: true,
              laps: [],
              segments: [
                {
                  sequence: 0,
                  kind: 'active',
                  label: '合成动作',
                  startTime: null,
                  durationSec: 30,
                  repetitions: 8,
                  weightKg: 20,
                  extraData: { sourceMessage: 'set' },
                  semantic: {
                    schemaVersion: 1,
                    sourceMessage: 'set',
                    exercise: { stepIndex: 0, name: '合成动作' },
                  },
                },
              ],
              devices: [],
              metricDefinitions: [],
              parseStatus: 'complete',
              downloadAvailable: true,
              originalFileName: 'run.fit',
            }),
            { headers: { 'Content-Type': 'application/json' } },
          ),
      ),
    )

    const result = await loadImportedActivity(activity.id)
    expect(result.parsed.backend).toMatchObject({
      profile: 'run',
      originalFileName: 'run.fit',
      recordCount: 1890,
      recordsSampled: true,
    })
    expect(result.parsed.backend?.segments[0].semantic).toEqual({
      schemaVersion: 1,
      sourceMessage: 'set',
      exercise: { stepIndex: 0, name: '合成动作' },
    })
    expect(result.parsed.summary.localStartTime).toBe('2026-07-09T06:41:56')
    expect(result.parsed.hrZoneSeconds).toEqual([
      { zone: 1, seconds: 68.49 },
      { zone: 2, seconds: 798.924 },
      { zone: 3, seconds: 1014.229 },
      { zone: 4, seconds: 4.915 },
      { zone: 5, seconds: 0 },
    ])
  })

  it('clears session-scoped summaries and API keys when the server invalidates the session', async () => {
    addUploadedActivities([
      {
        date: '2026-07-01',
        type: '力量',
        name: 'private summary',
        distanceKm: null,
        durationSec: 600,
        avgHr: null,
        paceSecPerKm: null,
        pace100Sec: null,
        powerW: null,
        source: 'FIT上传',
      },
    ])
    updateSettings((previous) => ({
      ...previous,
      ai: { ...previous.ai, apiKey: 'private-key' },
    }))
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(JSON.stringify({ code: 'authentication_required', message: '请先登录' }), {
            status: 401,
            headers: { 'Content-Type': 'application/json' },
          }),
      ),
    )

    await expect(listImportedActivities()).rejects.toMatchObject({ status: 401 })
    expect(getUploadedActivities()).toHaveLength(0)
    expect(getSettings().ai.apiKey).toBe('')
  })
})
