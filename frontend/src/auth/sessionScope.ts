import { resetUploadedActivities } from '../activities/uploadStore'
import { resetSettings } from '../settings/settingsStore'

export const SESSION_INVALIDATED_EVENT = 'trainlab:session-invalidated'

export function clearSessionScopedState(): void {
  resetUploadedActivities()
  resetSettings()
}

export function reportSessionInvalidated(): void {
  clearSessionScopedState()
  window.dispatchEvent(new Event(SESSION_INVALIDATED_EVENT))
}
