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
  abbr: string
  name: string // 佳明 Connect 中国区 / 佳明 Connect 国际区
  description: string
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
  '30': '每 30 分钟',
  '60': '每 1 小时',
  '360': '每 6 小时',
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
      abbr: 'GC',
      name: '佳明 Connect 中国区',
      description: 'connect.garmin.cn',
      status: 'failed',
      lastSyncAt: '昨天 22:41',
      syncedCount: 186,
      autoSyncInterval: 60,
      error: { at: '今天 06:00', reason: '请求超时(ETIMEDOUT),已自动重试 3 次' },
    },
    {
      id: 'garmin-global',
      abbr: 'GI',
      name: '佳明 Connect 国际区',
      description: 'connect.garmin.com',
      status: 'disconnected',
      lastSyncAt: null,
      syncedCount: 0,
      autoSyncInterval: 'manual',
    },
  ]
}
