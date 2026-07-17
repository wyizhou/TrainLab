// Session-scoped activity overlay (contract C-13), consumed via
// useSyncExternalStore without a global state library. Local FIT/TCX/GPX preview
// records created by addUploadedActivities use `upload-<n>` ids; authenticated
// backend results merged by mergeImportedActivities retain their server UUIDs.
// Both forms are cleared when the authenticated subject ends or changes.

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

export function mergeImportedActivities(items: Activity[]): void {
  if (items.length === 0) return
  const incoming = new Set(items.map((item) => item.id))
  uploaded = [...items, ...uploaded.filter((item) => !incoming.has(item.id))]
  emit()
}

export function getUploadedActivities(): readonly Activity[] {
  return uploaded
}

// Clears the session-scoped overlay on logout/subject change and between tests.
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
