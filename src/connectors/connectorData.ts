// Connector data model + demo initial state (contract C-10).
// A connector is a Garmin account region (中国区 / 国际区) with one of four
// sync states. All values are static mock (G-mock); no real network. Later
// requirements layer on auth (C-11), merge (C-12) and upload (C-13).

// ---- model --------------------------------------------------------------------

export type ConnectorStatus = 'connected' | 'disconnected' | 'syncing' | 'failed'

// Auto-sync cadence: minutes, or 'manual' for 仅手动.
export type AutoSyncInterval = 30 | 60 | 360 | 'manual'

export type SyncError = {
  at: string // 失败时间 (display string)
  reason: string // 原因, e.g. ETIMEDOUT
}

export type Connector = {
  id: string
  name: string // 佳明中国区 / 佳明国际区
  status: ConnectorStatus
  lastSyncAt: string | null // 上次成功同步时间; null = 从未
  syncedCount: number // 已同步数量
  autoSyncInterval: AutoSyncInterval
  error?: SyncError // present only when status === 'failed'
}

// ---- labels -------------------------------------------------------------------

const STATUS_LABELS: Record<ConnectorStatus, string> = {
  connected: '已连接',
  disconnected: '未连接',
  syncing: '同步中',
  failed: '同步失败',
}

export function statusLabel(status: ConnectorStatus): string {
  return STATUS_LABELS[status]
}

const INTERVAL_LABELS: Record<string, string> = {
  '30': '30 分钟',
  '60': '1 小时',
  '360': '6 小时',
  manual: '仅手动',
}

export function autoSyncLabel(interval: AutoSyncInterval): string {
  return INTERVAL_LABELS[String(interval)]
}

// 自动同步间隔可选项 (used by the interval selector).
export const AUTO_SYNC_OPTIONS: readonly AutoSyncInterval[] = [30, 60, 360, 'manual']

// ---- demo initial state -------------------------------------------------------

// Design §5.1 演示初始态: 中国区 = 同步失败(ETIMEDOUT), 国际区 = 未连接.
export function demoConnectors(): Connector[] {
  return [
    {
      id: 'garmin-cn',
      name: '佳明中国区',
      status: 'failed',
      lastSyncAt: '2026-07-10 22:14',
      syncedCount: 1284,
      autoSyncInterval: 60,
      error: { at: '2026-07-11 06:30', reason: 'ETIMEDOUT' },
    },
    {
      id: 'garmin-global',
      name: '佳明国际区',
      status: 'disconnected',
      lastSyncAt: null,
      syncedCount: 0,
      autoSyncInterval: 'manual',
    },
  ]
}
