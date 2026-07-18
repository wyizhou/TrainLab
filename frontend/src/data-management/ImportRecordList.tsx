import { useCallback, useEffect, useMemo, useState } from 'react'
import { Toast } from '../components/Toast'
import {
  deleteImport,
  listImports,
  retryImport,
  type ImportRecord,
  type ImportStatus,
} from './dataManagementApi'
import { demoImportFirstPage, demoImportMorePage } from './demoData'
import './ImportRecordList.css'

const STATUS: Record<ImportStatus, string> = {
  pending: '等待处理',
  processing: '处理中',
  complete: '处理完成',
  partial: '部分完成',
  failed: '处理失败',
  deleting: '正在删除',
  delete_failed: '删除未完成',
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`
}

function formatTime(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('zh-CN', { hour12: false })
}

function safeMessage(record: ImportRecord): string {
  if (record.errorMessage) return record.errorMessage
  if (record.warningCount > 0) return `${record.warningCount} 条解析警告`
  if (record.status === 'processing') return '服务器正在解析此文件。'
  if (record.status === 'deleting') return '服务器正在清理关联数据。'
  return '未报告异常。'
}

function actionLabel(record: ImportRecord): string {
  if (record.status === 'deleting') return '继续删除'
  if (record.status === 'delete_failed') return '重试删除'
  return '重新处理'
}

export function ImportRecordList({
  demoMode,
  refreshKey = 0,
  loadPage = listImports,
  retryRecord = retryImport,
  removeRecord = deleteImport,
}: {
  demoMode: boolean
  refreshKey?: number
  loadPage?: typeof listImports
  retryRecord?: typeof retryImport
  removeRecord?: typeof deleteImport
}) {
  const [items, setItems] = useState<ImportRecord[]>(demoMode ? demoImportFirstPage : [])
  const [state, setState] = useState<'loading' | 'ready' | 'error'>(demoMode ? 'ready' : 'loading')
  const [nextCursor, setNextCursor] = useState<string | null>(demoMode ? 'demo-more' : null)
  const [loadMoreState, setLoadMoreState] = useState<'idle' | 'loading' | 'error'>('idle')
  const [rowBusy, setRowBusy] = useState<string | null>(null)
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({})
  const [toast, setToast] = useState('')
  const [attempt, setAttempt] = useState(0)

  const loadFirst = useCallback(async () => {
    if (demoMode) {
      setItems(demoImportFirstPage)
      setNextCursor('demo-more')
      setState('ready')
      return
    }
    setState('loading')
    try {
      const page = await loadPage()
      setItems(page.items)
      setNextCursor(page.nextCursor)
      setState('ready')
    } catch {
      setState('error')
    }
  }, [demoMode, loadPage])

  useEffect(() => {
    void loadFirst()
  }, [attempt, loadFirst, refreshKey])

  useEffect(() => {
    if (!toast) return
    const timer = window.setTimeout(() => setToast(''), 2800)
    return () => window.clearTimeout(timer)
  }, [toast])

  const loadMore = async () => {
    if (!nextCursor || loadMoreState === 'loading') return
    setLoadMoreState('loading')
    try {
      if (demoMode) {
        setItems((current) => [...current, ...demoImportMorePage])
        setNextCursor(null)
        setLoadMoreState('idle')
        return
      }
      const page = await loadPage(nextCursor)
      setItems((current) => {
        const known = new Set(current.map((item) => item.importId))
        return [...current, ...page.items.filter((item) => !known.has(item.importId))]
      })
      setNextCursor(page.nextCursor)
      setLoadMoreState('idle')
    } catch {
      setLoadMoreState('error')
    }
  }

  const runAction = async (record: ImportRecord) => {
    if (rowBusy) return
    setRowBusy(record.importId)
    setRowErrors((errors) => ({ ...errors, [record.importId]: '' }))
    const deleteAction = record.deleteRetryAvailable
    try {
      if (demoMode) {
        if (deleteAction)
          setItems((current) => current.filter((item) => item.importId !== record.importId))
        else
          setItems((current) =>
            current.map((item) =>
              item.importId === record.importId
                ? {
                    ...item,
                    status: 'processing',
                    retryAvailable: false,
                    attemptCount: item.attemptCount + 1,
                  }
                : item,
            ),
          )
      } else if (deleteAction) {
        await removeRecord(record.importId)
        setItems((current) => current.filter((item) => item.importId !== record.importId))
      } else {
        await retryRecord(record.importId)
        const page = await loadPage()
        setItems(page.items)
        setNextCursor(page.nextCursor)
      }
      setToast(deleteAction ? '导入记录已删除' : `已重新提交 ${record.originalFileName}`)
    } catch {
      setRowErrors((errors) => ({
        ...errors,
        [record.importId]: deleteAction
          ? '删除仍未完成，记录已保留。'
          : '重新处理未能开始，请稍后重试。',
      }))
    } finally {
      setRowBusy(null)
    }
  }

  const rows = useMemo(
    () =>
      items.map((record) => ({
        ...record,
        displayMessage: rowErrors[record.importId] || safeMessage(record),
      })),
    [items, rowErrors],
  )

  const canOpen = (record: ImportRecord) =>
    (record.status === 'complete' || record.status === 'partial') && Boolean(record.activityId)

  const actions = (record: ImportRecord) => (
    <div className="import-record__actions">
      {canOpen(record) && (
        <a
          href={`/activities/${record.activityId}`}
          aria-disabled={rowBusy === record.importId}
          onClick={(event) => rowBusy === record.importId && event.preventDefault()}
        >
          查看运动
        </a>
      )}
      {(record.retryAvailable || record.deleteRetryAvailable) && (
        <button type="button" disabled={rowBusy !== null} onClick={() => void runAction(record)}>
          {rowBusy === record.importId ? '提交中…' : actionLabel(record)}
        </button>
      )}
      {!canOpen(record) && !record.retryAvailable && !record.deleteRetryAvailable && (
        <span>暂无操作</span>
      )}
    </div>
  )

  return (
    <section className="import-records" data-vc="import-records" data-testid="import-records">
      <div className="import-records__head">
        <div>
          <h2>导入记录</h2>
          <p>仅包含已提交到服务器的 FIT 文件 · 采用游标加载，不显示总页数或总条数</p>
        </div>
        <button
          type="button"
          disabled={state === 'loading' || rowBusy !== null}
          onClick={() => setAttempt((value) => value + 1)}
        >
          刷新列表
        </button>
      </div>
      {state === 'loading' && (
        <div className="import-records__state" data-vc="import-list-loading" aria-live="polite">
          <span />
          <span />
          正在加载导入记录…
        </div>
      )}
      {state === 'error' && (
        <div
          className="import-records__state import-records__state--error"
          data-vc="import-list-error"
          role="alert"
        >
          <strong>导入记录暂时无法加载</strong>
          <span>运动数据不受影响，请稍后重试。</span>
          <button type="button" onClick={() => setAttempt((value) => value + 1)}>
            重新加载
          </button>
        </div>
      )}
      {state === 'ready' && rows.length === 0 && (
        <div className="import-records__state" data-vc="import-list-empty">
          <strong>暂无 FIT 导入记录</strong>
          <span>上传 FIT 后会在这里显示处理进度；TCX / GPX 仅作本地预览。</span>
        </div>
      )}
      {state === 'ready' && rows.length > 0 && (
        <>
          <div className="import-records__table" data-vc="import-records-table">
            <div className="import-records__row import-records__row--head">
              <span>文件</span>
              <span>大小</span>
              <span>状态</span>
              <span>更新时间</span>
              <span>尝试</span>
              <span>警告</span>
              <span>说明</span>
              <span>可用操作</span>
            </div>
            {rows.map((record) => (
              <div
                className="import-records__row"
                data-vc="import-record-row"
                data-testid="import-record-row"
                key={record.importId}
              >
                <strong className="import-record__file">{record.originalFileName}</strong>
                <span className="num">{formatBytes(record.sizeBytes)}</span>
                <span className={`import-status import-status--${record.status.replace('_', '-')}`}>
                  {STATUS[record.status]}
                </span>
                <span className="num">{formatTime(record.updatedAt)}</span>
                <span className="num">{record.attemptCount}</span>
                <span className="num">{record.warningCount}</span>
                <span
                  className={
                    rowErrors[record.importId]
                      ? 'import-record__message import-record__message--error'
                      : 'import-record__message'
                  }
                >
                  {record.displayMessage}
                </span>
                {actions(record)}
              </div>
            ))}
          </div>
          <div className="import-records__cards" data-vc="import-records-cards">
            {rows.map((record) => (
              <article
                className="import-record-card"
                data-vc="import-record-card"
                data-testid="import-record-card"
                key={record.importId}
              >
                <div className="import-record-card__head">
                  <strong>{record.originalFileName}</strong>
                  <span
                    className={`import-status import-status--${record.status.replace('_', '-')}`}
                  >
                    {STATUS[record.status]}
                  </span>
                </div>
                <dl>
                  <div>
                    <dt>大小</dt>
                    <dd className="num">{formatBytes(record.sizeBytes)}</dd>
                  </div>
                  <div>
                    <dt>尝试</dt>
                    <dd className="num">{record.attemptCount}</dd>
                  </div>
                  <div>
                    <dt>更新时间</dt>
                    <dd className="num">{formatTime(record.updatedAt)}</dd>
                  </div>
                  <div>
                    <dt>警告</dt>
                    <dd className="num">{record.warningCount}</dd>
                  </div>
                </dl>
                <p
                  className={
                    rowErrors[record.importId]
                      ? 'import-record__message import-record__message--error'
                      : 'import-record__message'
                  }
                >
                  {record.displayMessage}
                </p>
                {actions(record)}
              </article>
            ))}
          </div>
          {nextCursor && (
            <div className="import-records__more">
              <button
                type="button"
                disabled={loadMoreState === 'loading'}
                onClick={() => void loadMore()}
              >
                {loadMoreState === 'loading' ? (
                  <>
                    <span className="import-records__spinner" aria-hidden="true" />
                    加载中…
                  </>
                ) : loadMoreState === 'error' ? (
                  '重试加载更多'
                ) : (
                  '加载更多'
                )}
              </button>
              {loadMoreState === 'error' && (
                <span role="alert">更多记录加载失败，现有记录已保留。</span>
              )}
            </div>
          )}
        </>
      )}
      {toast && <Toast message={toast} />}
    </section>
  )
}
