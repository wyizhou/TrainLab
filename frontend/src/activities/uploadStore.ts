// Uploaded-activity store (contract C-13). FileUpload parses FIT/TCX/GPX files
// on the 连接器 page and "入库" the results here; ActivitiesPage merges them into
// the 运动记录 list. There is no global state library (see requirement 007) — this
// is a tiny module-level observable consumed via useSyncExternalStore. Everything
// stays front-end mock (G-mock): no network, ids are local (`upload-<n>`).

import { useSyncExternalStore } from 'react'
import type { Activity } from './activityData'

let uploaded: readonly Activity[] = []
let seq = 0
const listeners = new Set<() => void>()

function emit(): void {
  for (const listener of listeners) listener()
}

// Assigns each parsed record a stable local id and prepends it (newest first).
// Returns the created activities so callers can reflect what landed.
export function addUploadedActivities(items: Omit<Activity, 'id'>[]): Activity[] {
  const created = items.map((a) => ({ ...a, id: `upload-${seq++}` }))
  if (created.length > 0) {
    uploaded = [...created, ...uploaded]
    emit()
  }
  return created
}

export function getUploadedActivities(): readonly Activity[] {
  return uploaded
}

// Test-only: clears the module-level state between cases.
export function resetUploadedActivities(): void {
  uploaded = []
  seq = 0
  emit()
}

function subscribe(callback: () => void): () => void {
  listeners.add(callback)
  return () => {
    listeners.delete(callback)
  }
}

export function useUploadedActivities(): readonly Activity[] {
  return useSyncExternalStore(subscribe, getUploadedActivities, getUploadedActivities)
}
