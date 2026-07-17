// Settings store (contract C-14). The 设置 page's four groups persist here as a
// tiny module-level observable consumed via useSyncExternalStore — the same
// pattern as uploadStore (requirement 007: no global state library). Everything
// is front-end mock (G-mock): no network, no real persistence.
//
// There is deliberately no retention / auto-clean state: the system offers no
// bulk-delete or expiry cleanup of data (C-14 返工 design_rev 2).
//
// The 区间设定 group is the one cross-section consumer: its zone boundaries feed
// the detail page's 心率区间图 (C-8) as raw-data annotation only — the system
// never recomputes times from them (C-14: 系统不用于计算).

import { useSyncExternalStore } from 'react'
import { DEFAULT_HR_ZONES, type HrZoneConfig } from '../activities/hrZones'

// 单位制 — display units only; stored values are never converted (G-mock).
export type UnitSystem = {
  distance: 'km' | 'mi' // 距离 / 海拔
  pace: 'min/km' | 'min/mi' // 配速
  weight: 'kg' | 'lb' // 体重
}

// 区间设定 — the zone-chart config (MaxHR + Z1–Z4 upper bounds) plus the two
// threshold annotations (LTHR / FTP). Annotation boundaries only, never used in
// calculation (C-14). MaxHR + bounds project onto HrZoneConfig for C-8.
export type ZoneSettings = {
  maxHr: number
  lthr: number
  ftp: number
  bounds: [number, number, number, number] // Z1–Z4 上界
}

// AI 接口 — request target for 分析对话 (C-6). Defaults to DeepSeek.
export type AiSettings = {
  baseUrl: string
  apiKey: string
  model: string
}

export type Settings = {
  units: UnitSystem
  zones: ZoneSettings
  ai: AiSettings
}

export const DEFAULT_AI_BASE_URL = 'https://api.deepseek.com'

// v3.2 baseline settings. Zone defaults mirror hrZones.DEFAULT_HR_ZONES so the
// settings page and activity detail always share the same interval labels.
export function defaultSettings(): Settings {
  return {
    units: { distance: 'km', pace: 'min/km', weight: 'kg' },
    zones: {
      maxHr: DEFAULT_HR_ZONES.maxHr,
      lthr: 168,
      ftp: 245,
      bounds: [
        DEFAULT_HR_ZONES.bounds[0],
        DEFAULT_HR_ZONES.bounds[1],
        DEFAULT_HR_ZONES.bounds[2],
        DEFAULT_HR_ZONES.bounds[3],
      ],
    },
    ai: { baseUrl: DEFAULT_AI_BASE_URL, apiKey: '', model: 'deepseek-chat' },
  }
}

let current: Settings = defaultSettings()
const listeners = new Set<() => void>()

function emit(): void {
  for (const listener of listeners) listener()
}

export function getSettings(): Settings {
  return current
}

// Replaces settings via a patch producer, then notifies subscribers. Callers
// return a fresh object so useSyncExternalStore sees a new snapshot reference.
export function updateSettings(patch: (prev: Settings) => Settings): void {
  current = patch(current)
  emit()
}

// Restores the baseline on logout/subject change and between tests.
export function resetSettings(): void {
  current = defaultSettings()
  emit()
}

function subscribe(callback: () => void): () => void {
  listeners.add(callback)
  return () => {
    listeners.delete(callback)
  }
}

export function useSettings(): Settings {
  return useSyncExternalStore(subscribe, getSettings, getSettings)
}

// The HrZoneConfig the detail page (C-8) reads — projected from 区间设定. Called
// during render, so a fresh object here is fine (the snapshot stays `current`).
export function useHrZoneConfig(): HrZoneConfig {
  const { zones } = useSettings()
  return { maxHr: zones.maxHr, bounds: zones.bounds }
}
