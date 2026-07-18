import type { Activity } from './activityData'
import type { ParsedActivity } from './fitParser'
import { reportSessionInvalidated } from '../auth/sessionScope'

export class ActivityApiError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly status: number,
    readonly details: Record<string, unknown> | null = null,
  ) {
    super(message)
  }
}

type ActivityListPage = { items: Activity[]; nextCursor: string | null }

export type FitImportResult = {
  importId: string
  status: 'complete' | 'partial'
  deduplicated: boolean
  activity: Activity
  retryAvailable: boolean
}

type BackendDetail = {
  activity: Activity
  summary: ParsedActivity['summary']
  records: Array<
    ParsedActivity['records'][number] & {
      sequence: number
      timestamp: string | null
      positionLat: number | null
      positionLong: number | null
      extraMetrics: Record<string, unknown>
    }
  >
  recordCount: number
  recordsSampled: boolean
  laps: Array<ParsedActivity['laps'][number] & { startTime: string | null }>
  segments: NonNullable<ParsedActivity['backend']>['segments']
  devices: NonNullable<ParsedActivity['backend']>['devices']
  metricDefinitions: NonNullable<ParsedActivity['backend']>['metricDefinitions']
  parseStatus: 'complete' | 'partial'
  downloadAvailable: boolean
  originalFileName: string
}

const SESSION_HR_ZONE_KEY = 'native:time_in_zone:session:time_in_hr_zone'

function storedHrZoneSeconds(
  extraMetrics: Record<string, unknown>,
): ParsedActivity['hrZoneSeconds'] {
  const raw = extraMetrics[SESSION_HR_ZONE_KEY]
  if (!Array.isArray(raw) || raw.length < 5) return []
  const seconds = raw.slice(0, 5)
  if (
    !seconds.every((value) => typeof value === 'number' && Number.isFinite(value) && value >= 0)
  ) {
    return []
  }
  return seconds.map((value, index) => ({ zone: index + 1, seconds: value as number }))
}

function cookieValue(name: string): string | null {
  const prefix = `${encodeURIComponent(name)}=`
  const item = document.cookie.split('; ').find((value) => value.startsWith(prefix))
  return item ? decodeURIComponent(item.slice(prefix.length)) : null
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (init.method && !['GET', 'HEAD'].includes(init.method.toUpperCase())) {
    const csrf = cookieValue('trainlab_csrf')
    if (csrf) headers.set('X-CSRF-Token', csrf)
  }
  const response = await fetch(path, { ...init, headers, credentials: 'same-origin' })
  const payload = (response.status === 204 ? null : await response.json().catch(() => null)) as
    ({ code?: string; message?: string; details?: Record<string, unknown> } & Partial<T>) | null
  if (!response.ok) {
    if (response.status === 401) reportSessionInvalidated()
    throw new ActivityApiError(
      payload?.message ?? '服务暂时不可用',
      payload?.code ?? 'request_failed',
      response.status,
      payload?.details ?? null,
    )
  }
  if (response.status === 204) return undefined as T
  return payload as T
}

export function updateImportedActivityName(
  activityId: string,
  name: string | null,
): Promise<Activity> {
  return apiRequest<Activity>(`/api/v1/activities/${activityId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
}

export function deleteImportedActivity(activityId: string): Promise<void> {
  return apiRequest<void>(`/api/v1/activities/${activityId}`, { method: 'DELETE' })
}

export async function listImportedActivities(): Promise<Activity[]> {
  const activities: Activity[] = []
  let cursor: string | null = null
  do {
    const query = new URLSearchParams({ limit: '100' })
    if (cursor) query.set('cursor', cursor)
    const page: ActivityListPage = await apiRequest(`/api/v1/activities?${query}`)
    activities.push(...page.items)
    cursor = page.nextCursor
  } while (cursor)
  return activities
}

export function uploadFitFile(file: File): Promise<FitImportResult> {
  const body = new FormData()
  body.append('file', file)
  return apiRequest<FitImportResult>('/api/v1/imports/fit', { method: 'POST', body })
}

export async function loadImportedActivity(
  activityId: string,
): Promise<{ activity: Activity; parsed: ParsedActivity }> {
  const detail = await apiRequest<BackendDetail>(`/api/v1/activities/${activityId}`)
  return {
    activity: detail.activity,
    parsed: {
      summary: detail.summary,
      records: detail.records,
      laps: detail.laps,
      hrZoneSeconds: storedHrZoneSeconds(detail.summary.extraMetrics ?? {}),
      backend: {
        profile: detail.activity.profile ?? 'generic',
        parseStatus: detail.parseStatus,
        originalFileName: detail.originalFileName,
        downloadAvailable: detail.downloadAvailable,
        recordCount: detail.recordCount,
        recordsSampled: detail.recordsSampled,
        segments: detail.segments,
        devices: detail.devices,
        metricDefinitions: detail.metricDefinitions,
      },
    },
  }
}

export async function downloadImportedActivity(activityId: string): Promise<void> {
  const response = await fetch(`/api/v1/activities/${activityId}/source`, {
    credentials: 'same-origin',
  })
  if (!response.ok) {
    if (response.status === 401) reportSessionInvalidated()
    const payload = (await response.json().catch(() => null)) as {
      code?: string
      message?: string
    } | null
    throw new ActivityApiError(
      payload?.message ?? '下载失败',
      payload?.code ?? 'download_failed',
      response.status,
    )
  }
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const utf8Name = disposition.match(/filename\*=utf-8''([^;]+)/i)?.[1]
  const simpleName = disposition.match(/filename="?([^";]+)"?/i)?.[1]
  const fileName = decodeURIComponent(utf8Name ?? simpleName ?? 'activity.fit')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName
  anchor.click()
  URL.revokeObjectURL(url)
}

export function isImportedActivityId(id: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(id)
}
