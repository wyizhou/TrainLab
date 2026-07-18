import { useEffect, useMemo, useState } from 'react'
import { loadStorageUsage, type StorageUsage } from './dataManagementApi'
import { demoStorageUsage } from './demoData'
import './StorageQuotaCard.css'

type StorageTone = 'normal' | 'near' | 'full' | 'empty'

function percentage(value: number, maximum: number): number {
  if (!Number.isFinite(value) || !Number.isFinite(maximum) || maximum <= 0) return 0
  return Math.min(100, Math.max(0, (value / maximum) * 100))
}

function formatCapacity(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '—'
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`
}

function statusOf(usage: StorageUsage): { tone: StorageTone; title: string; message: string } {
  if (usage.remainingBytes === 0)
    return {
      tone: 'full',
      title: '存储空间已满',
      message: '请先删除不再需要的运动，再上传新的 FIT。',
    }
  if (usage.remainingFiles === 0)
    return {
      tone: 'full',
      title: '文件数量已满',
      message: '文件数量已达到上限，请先删除不再需要的运动。',
    }
  if (usage.fileCount === 0)
    return {
      tone: 'empty',
      title: '暂无服务器文件',
      message: '上传第一个 FIT 后，这里会显示实际用量。',
    }
  if (
    percentage(usage.usedBytes, usage.maxBytes) >= 90 ||
    percentage(usage.fileCount, usage.maxFiles) >= 90
  )
    return {
      tone: 'near',
      title: '接近存储上限',
      message: '空间或文件数量已使用 90% 以上，请留意剩余容量。',
    }
  return { tone: 'normal', title: '存储状态正常', message: '当前空间和文件数量均在可用范围内。' }
}

export function StorageQuotaCard({
  demoMode,
  loadUsage = loadStorageUsage,
}: {
  demoMode: boolean
  loadUsage?: typeof loadStorageUsage
}) {
  const [usage, setUsage] = useState<StorageUsage | null>(demoMode ? demoStorageUsage : null)
  const [state, setState] = useState<'loading' | 'ready' | 'error'>(demoMode ? 'ready' : 'loading')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (demoMode) {
      setUsage(demoStorageUsage)
      setState('ready')
      return
    }
    let active = true
    setState('loading')
    loadUsage()
      .then((snapshot) => {
        if (!active) return
        setUsage(snapshot)
        setState('ready')
      })
      .catch(() => {
        if (active) setState('error')
      })
    return () => {
      active = false
    }
  }, [attempt, demoMode, loadUsage])

  const status = useMemo(() => (usage ? statusOf(usage) : null), [usage])
  const usedPercent = usage ? percentage(usage.usedBytes, usage.maxBytes) : 0

  return (
    <section
      className="storage-card"
      data-vc="settings-data-storage"
      data-testid="settings-data-storage"
    >
      <div className="storage-card__head">
        <div>
          <h2>数据与存储</h2>
          <p>当前服务器存储快照。FIT 会计入用量；TCX / GPX 本地预览不会计入。</p>
        </div>
        {state === 'ready' && (
          <button type="button" onClick={() => setAttempt((value) => value + 1)}>
            刷新用量
          </button>
        )}
      </div>
      {state === 'loading' && (
        <div className="storage-card__loading" data-vc="storage-loading" aria-live="polite">
          <span />
          <span />
          <span />
        </div>
      )}
      {state === 'error' && (
        <div className="storage-card__error" data-vc="storage-error" role="alert">
          <strong>存储用量加载失败</strong>
          <span>暂时无法读取当前配额快照，运动数据不受影响。</span>
          <button type="button" onClick={() => setAttempt((value) => value + 1)}>
            重新加载
          </button>
        </div>
      )}
      {state === 'ready' && usage && status && (
        <>
          <div
            className={`storage-card__banner storage-card__banner--${status.tone}`}
            data-vc="storage-status-banner"
          >
            <strong>{status.title}</strong>
            <span>{status.message}</span>
          </div>
          <div className="storage-card__progress-head">
            <span>服务器空间</span>
            <strong className="num">{usedPercent.toFixed(1)}%</strong>
          </div>
          <div
            className="storage-card__progress"
            role="progressbar"
            aria-label="服务器空间使用比例"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(usedPercent)}
          >
            <span
              className={`storage-card__progress-value storage-card__progress-value--${status.tone}`}
              style={{ width: `${usedPercent}%` }}
            />
          </div>
          <dl className="storage-card__summary">
            <div>
              <dt>已使用</dt>
              <dd className="num">{formatCapacity(usage.usedBytes)}</dd>
            </div>
            <div>
              <dt>总容量</dt>
              <dd className="num">{formatCapacity(usage.maxBytes)}</dd>
            </div>
            <div>
              <dt>文件数量</dt>
              <dd className="num">
                {usage.fileCount} / {usage.maxFiles}
              </dd>
            </div>
            <div>
              <dt>剩余空间</dt>
              <dd className="num">{formatCapacity(usage.remainingBytes)}</dd>
            </div>
          </dl>
          {usage.fileCount === 0 && (
            <div className="storage-card__empty" data-vc="storage-empty">
              当前没有服务器持久化文件。本地预览的 TCX / GPX 不会改变此快照。
            </div>
          )}
        </>
      )}
    </section>
  )
}
