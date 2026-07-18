import type { ImportRecord, StorageUsage } from './dataManagementApi'

const base = {
  source: 'fit_upload',
  sizeBytes: 1_248_300,
  createdAt: '2026-07-18T02:10:00Z',
  updatedAt: '2026-07-18T02:12:00Z',
  attemptCount: 1,
  lastAttemptAt: '2026-07-18T02:11:00Z',
  completedAt: null,
  warningCount: 0,
  errorCode: null,
  errorMessage: null,
  retryAvailable: false,
  deleteRetryAvailable: false,
} as const

export const demoImportFirstPage: ImportRecord[] = [
  {
    ...base,
    importId: 'imp-complete',
    activityId: 'a0',
    originalFileName: '617273913_ACTIVITY.fit',
    sizeBytes: 264 * 1024,
    status: 'complete',
    completedAt: '2026-07-18T02:12:00Z',
  },
  {
    ...base,
    importId: 'imp-partial',
    activityId: 'profile-hike',
    originalFileName: '600348741_ACTIVITY.fit',
    sizeBytes: 605 * 1024,
    status: 'partial',
    warningCount: 3,
    retryAvailable: true,
    errorMessage: '部分扩展指标未能解析。',
  },
  {
    ...base,
    importId: 'imp-pending',
    activityId: null,
    originalFileName: '616634193_ACTIVITY.fit',
    sizeBytes: 57 * 1024,
    status: 'pending',
    attemptCount: 0,
    lastAttemptAt: null,
  },
  {
    ...base,
    importId: 'imp-processing',
    activityId: null,
    originalFileName: '616627608_ACTIVITY.fit',
    sizeBytes: 82 * 1024,
    status: 'processing',
  },
]

export const demoImportMorePage: ImportRecord[] = [
  {
    ...base,
    importId: 'imp-failed',
    activityId: null,
    originalFileName: '578824608_ACTIVITY.fit',
    sizeBytes: 130 * 1024,
    status: 'failed',
    retryAvailable: true,
    errorCode: 'fit_parse_failed',
    errorMessage: '文件未能完成解析，请确认文件完整后重试。',
  },
  {
    ...base,
    importId: 'imp-deleting',
    activityId: null,
    originalFileName: '614797758_ACTIVITY.fit',
    sizeBytes: 240 * 1024,
    status: 'deleting',
    deleteRetryAvailable: true,
    errorMessage: '删除正在继续处理中。',
  },
  {
    ...base,
    importId: 'imp-delete-failed',
    activityId: null,
    originalFileName: '2026-07-06-evening-ride.fit',
    sizeBytes: 1_248_300,
    status: 'delete_failed',
    deleteRetryAvailable: true,
    errorCode: 'delete_incomplete',
    errorMessage: '删除尚未完成，原记录已安全保留。',
  },
]

export const demoStorageUsage: StorageUsage = {
  usedBytes: 3_435_973_837,
  fileCount: 186,
  maxBytes: 10_737_418_240,
  maxFiles: 500,
  remainingBytes: 7_301_444_403,
  remainingFiles: 314,
}
