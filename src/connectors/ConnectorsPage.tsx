import { useEffect, useState } from 'react'
import { ConnectorCard } from './ConnectorCard'
import { ConnectorAuthModal } from './ConnectorAuthModal'
import { ConflictBanner } from './ConflictBanner'
import { ConflictModal } from './ConflictModal'
import { FileUpload } from './FileUpload'
import { Toast } from '../components/Toast'
import { demoConflictGroups, type ConflictGroup } from './conflictData'
import { demoConnectors, type AutoSyncInterval, type Connector } from './connectorData'
import './ConnectorsPage.css'

// 连接器 page (contract C-10 + C-11 + C-12). Renders the connector state cards
// from demo data. Actions are front-end mock only (G-mock) — a "sync" flips the
// card to connected with a refreshed timestamp. Connecting a disconnected
// account opens the auth modal (C-11). Connecting the second region (国际区)
// reconciles its activities against 中国区: suspected duplicates surface as a
// 冲突横幅 + 逐组保留弹窗 (C-12). The 文件上传 area (C-13) imports FIT/TCX/GPX files
// into 运动记录 with source 「FIT上传」.

// The second region whose connection triggers the double-account merge check.
const MERGE_TRIGGER_ID = 'garmin-global'

// A mock sync/connect: no real network, just mark the card connected.
function markConnected(c: Connector): Connector {
  return {
    ...c,
    status: 'connected',
    lastSyncAt: '刚刚',
    syncedCount: c.syncedCount + 12,
    error: undefined,
  }
}

export function ConnectorsPage() {
  const [connectors, setConnectors] = useState<Connector[]>(demoConnectors)
  // id of the connector currently being authorized, or null when closed.
  const [authForId, setAuthForId] = useState<string | null>(null)
  // Suspected-duplicate groups awaiting resolution (empty = no banner).
  const [conflicts, setConflicts] = useState<ConflictGroup[]>([])
  const [showConflictModal, setShowConflictModal] = useState(false)
  // Transient sync-success notice (AC-001c-4); auto-dismisses on a timer.
  const [toast, setToast] = useState<string | null>(null)

  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(null), 2600)
    return () => clearTimeout(timer)
  }, [toast])

  const update = (id: string, fn: (c: Connector) => Connector) =>
    setConnectors((prev) => prev.map((c) => (c.id === id ? fn(c) : c)))

  // 立即同步 / 重试同步 — mock sync (G-mock) surfaces a 同步成功 toast.
  const handleSync = (id: string) => {
    update(id, markConnected)
    setToast('同步成功')
  }

  // 连接账号 — opens the auth modal (C-11); the mock connect happens on success.
  const handleConnect = (id: string) => setAuthForId(id)

  const handleAuthSuccess = () => {
    if (authForId) update(authForId, markConnected)
    // Connecting the second region reconciles it against 中国区; the demo import
    // yields two suspected duplicates that need manual resolution (C-12).
    if (authForId === MERGE_TRIGGER_ID) setConflicts(demoConflictGroups())
    setAuthForId(null)
  }

  // 确认合并 — the merge is applied (mock) and the banner clears.
  const handleMergeConfirm = () => {
    setConflicts([])
    setShowConflictModal(false)
  }

  const handleIntervalChange = (id: string, interval: AutoSyncInterval) =>
    update(id, (c) => ({ ...c, autoSyncInterval: interval }))

  const authConnector = connectors.find((c) => c.id === authForId) ?? null

  return (
    <section className="page connectors" data-testid="page-connectors">
      <div className="connectors__head">
        <h1>连接器</h1>
        <p className="connectors__intro">连接佳明账号，自动同步运动与健康数据 · 同步均为前端模拟</p>
      </div>

      {conflicts.length > 0 && (
        <ConflictBanner count={conflicts.length} onResolve={() => setShowConflictModal(true)} />
      )}

      <FileUpload />

      <div className="connectors__grid" data-vc="connectors-grid">
        {connectors.map((connector) => (
          <ConnectorCard
            key={connector.id}
            connector={connector}
            onSync={handleSync}
            onConnect={handleConnect}
            onIntervalChange={handleIntervalChange}
          />
        ))}
      </div>

      {authConnector && (
        <ConnectorAuthModal
          connectorName={authConnector.name}
          onSuccess={handleAuthSuccess}
          onClose={() => setAuthForId(null)}
        />
      )}

      {showConflictModal && conflicts.length > 0 && (
        <ConflictModal
          groups={conflicts}
          onConfirm={handleMergeConfirm}
          onClose={() => setShowConflictModal(false)}
        />
      )}

      {toast && <Toast message={toast} />}
    </section>
  )
}
