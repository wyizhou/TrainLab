import { apiRequest } from '../activities/activityApi'

export type ImportStatus =
  'pending' | 'processing' | 'complete' | 'partial' | 'failed' | 'deleting' | 'delete_failed'

export type ImportRecord = {
  importId: string
  activityId: string | null
  source: string
  originalFileName: string
  sizeBytes: number
  status: ImportStatus
  createdAt: string
  updatedAt: string
  attemptCount: number
  lastAttemptAt: string | null
  completedAt: string | null
  warningCount: number
  errorCode: string | null
  errorMessage: string | null
  retryAvailable: boolean
  deleteRetryAvailable: boolean
}

export type ImportPage = { items: ImportRecord[]; nextCursor: string | null }

export type StorageUsage = {
  usedBytes: number
  fileCount: number
  maxBytes: number
  maxFiles: number
  remainingBytes: number
  remainingFiles: number
}

export function listImports(cursor?: string | null): Promise<ImportPage> {
  const query = new URLSearchParams({ limit: '50' })
  if (cursor) query.set('cursor', cursor)
  return apiRequest<ImportPage>(`/api/v1/imports?${query}`)
}

export function retryImport(importId: string): Promise<void> {
  return apiRequest<void>(`/api/v1/imports/${importId}/retry`, { method: 'POST' })
}

export function deleteImport(importId: string): Promise<void> {
  return apiRequest<void>(`/api/v1/imports/${importId}`, { method: 'DELETE' })
}

export function loadStorageUsage(): Promise<StorageUsage> {
  return apiRequest<StorageUsage>('/api/v1/storage/usage')
}
