import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
} from 'react'
import type { Activity } from '../activities/activityData'
import { ActivityApiError } from '../activities/activityApi'
import './ActivityActions.css'

export type ActivityManagementMode = 'rename' | 'restore' | 'delete'

type ActivityActionsProps = {
  activity: Activity
  detail?: boolean
  onRename: (activity: Activity, name: string) => Promise<Activity>
  onRestore: (activity: Activity) => Promise<Activity>
  onDelete: (activity: Activity) => Promise<void>
  onDownload: (activity: Activity) => Promise<void> | void
  onFeedback: (message: string) => void
  downloadAvailable?: boolean
}

const MODE_COPY: Record<ActivityManagementMode, { title: string; submit: string; busy: string }> = {
  rename: { title: '重命名运动', submit: '保存名称', busy: '保存中…' },
  restore: { title: '恢复解析标题', submit: '确认恢复', busy: '恢复中…' },
  delete: { title: '删除运动', submit: '确认删除', busy: '删除中…' },
}

function safeActionError(error: unknown, mode: ActivityManagementMode): string {
  if (mode === 'delete' && error instanceof ActivityApiError) {
    if (error.code === 'import_in_progress') return '该运动对应的导入仍在进行，请稍后重试。'
    if (error.code === 'delete_incomplete') return '删除尚未完成，记录已保留，请稍后重试。'
  }
  if (mode === 'rename') return '名称暂时无法保存，请稍后重试。'
  if (mode === 'restore') return '解析标题暂时无法恢复，请稍后重试。'
  return '运动暂时无法删除，请稍后重试。'
}

export function ActivityActions({
  activity,
  detail = false,
  onRename,
  onRestore,
  onDelete,
  onDownload,
  onFeedback,
  downloadAvailable = true,
}: ActivityActionsProps) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [mode, setMode] = useState<ActivityManagementMode | null>(null)
  const [input, setInput] = useState(activity.name)
  const [busy, setBusy] = useState(false)
  const [downloadBusy, setDownloadBusy] = useState(false)
  const [error, setError] = useState('')
  const [menuPosition, setMenuPosition] = useState<{ top: number; right: number } | null>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const titleId = useId()

  useEffect(() => {
    if (!menuOpen) return
    const close = (event: PointerEvent) => {
      if (
        !menuRef.current?.contains(event.target as Node) &&
        !triggerRef.current?.contains(event.target as Node)
      ) {
        setMenuOpen(false)
      }
    }
    document.addEventListener('pointerdown', close)
    return () => document.removeEventListener('pointerdown', close)
  }, [menuOpen])

  useEffect(() => {
    if (!mode) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const timer = window.setTimeout(() => {
      if (mode === 'rename') {
        inputRef.current?.focus()
        inputRef.current?.select()
      } else {
        dialogRef.current?.focus()
      }
    })
    return () => {
      window.clearTimeout(timer)
      document.body.style.overflow = previousOverflow
    }
  }, [mode])

  const openMenu = () => {
    if (window.innerWidth < 640) {
      setMenuPosition(null)
      setMenuOpen((value) => {
        const next = !value
        if (next) {
          window.setTimeout(() =>
            menuRef.current?.querySelector<HTMLButtonElement>('[role=menuitem]')?.focus(),
          )
        }
        return next
      })
      return
    }
    const rect = triggerRef.current?.getBoundingClientRect()
    if (rect) {
      const menuHeight = 164
      const top =
        rect.bottom + menuHeight + 12 > window.innerHeight
          ? rect.top - menuHeight - 6
          : rect.bottom + 6
      setMenuPosition({ top: Math.max(6, top), right: Math.max(6, window.innerWidth - rect.right) })
    }
    setMenuOpen((value) => {
      const next = !value
      if (next) {
        window.setTimeout(() =>
          menuRef.current?.querySelector<HTMLButtonElement>('[role=menuitem]')?.focus(),
        )
      }
      return next
    })
  }

  const openDialog = (nextMode: ActivityManagementMode) => {
    setMenuOpen(false)
    setMode(nextMode)
    setInput(activity.name)
    setError('')
  }

  const closeDialog = () => {
    if (busy) return
    setMode(null)
    setError('')
    window.setTimeout(() => triggerRef.current?.focus())
  }

  const menuKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const items = Array.from(
      menuRef.current?.querySelectorAll<HTMLButtonElement>('[role=menuitem]:not(:disabled)') ?? [],
    )
    const index = items.indexOf(document.activeElement as HTMLButtonElement)
    if (event.key === 'Escape') {
      event.preventDefault()
      setMenuOpen(false)
      triggerRef.current?.focus()
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      const offset = event.key === 'ArrowDown' ? 1 : -1
      items[(index + offset + items.length) % items.length]?.focus()
    }
  }

  const dialogKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape' && !busy) {
      event.preventDefault()
      closeDialog()
      return
    }
    if (event.key !== 'Tab') return
    const focusable = Array.from(
      dialogRef.current?.querySelectorAll<HTMLElement>('input,button:not(:disabled)') ?? [],
    )
    if (focusable.length === 0) return
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  const submit = async () => {
    if (!mode || busy) return
    const trimmed = input.trim()
    if (mode === 'rename' && trimmed.length === 0) {
      setError('运动名称不能为空；如需恢复，请使用“恢复解析标题”。')
      return
    }
    if (mode === 'rename' && trimmed.length > 255) {
      setError('运动名称不能超过 255 个字符。')
      return
    }
    setBusy(true)
    setError('')
    try {
      if (mode === 'rename') {
        const updated = await onRename(activity, trimmed)
        onFeedback(`运动名称已更新：${updated.name}`)
      } else if (mode === 'restore') {
        const updated = await onRestore(activity)
        onFeedback(`已恢复解析标题：${updated.name}`)
      } else {
        await onDelete(activity)
        onFeedback('运动、导入记录和原始文件已删除')
      }
      const shouldRestoreFocus = mode !== 'delete'
      setMode(null)
      if (shouldRestoreFocus) window.setTimeout(() => triggerRef.current?.focus())
    } catch (actionError) {
      setError(safeActionError(actionError, mode))
    } finally {
      setBusy(false)
    }
  }

  const download = async () => {
    if (downloadBusy) return
    setMenuOpen(false)
    setDownloadBusy(true)
    try {
      await onDownload(activity)
    } catch {
      onFeedback('原始 FIT 下载失败，请稍后重试。')
    } finally {
      setDownloadBusy(false)
      triggerRef.current?.focus()
    }
  }

  const stop = (event: ReactMouseEvent) => event.stopPropagation()

  return (
    <div className="activity-actions" onClick={stop}>
      <button
        ref={triggerRef}
        type="button"
        className={
          detail
            ? 'activity-actions__trigger activity-actions__trigger--detail'
            : 'activity-actions__trigger'
        }
        data-vc={detail ? 'activity-detail-more' : 'activity-more-button'}
        aria-label="打开运动操作菜单"
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        onClick={openMenu}
      >
        更多
      </button>
      {menuOpen && (
        <div
          ref={menuRef}
          className="activity-actions__menu"
          data-vc={detail ? 'activity-detail-actions-menu' : 'activity-actions-menu'}
          role="menu"
          style={menuPosition ?? undefined}
          onKeyDown={menuKeyDown}
        >
          <button type="button" role="menuitem" onClick={() => openDialog('rename')}>
            重命名
          </button>
          <button type="button" role="menuitem" onClick={() => openDialog('restore')}>
            恢复解析标题
          </button>
          <button
            type="button"
            role="menuitem"
            disabled={downloadBusy || !downloadAvailable}
            onClick={() => void download()}
          >
            {!downloadAvailable ? '原始 FIT 不可用' : downloadBusy ? '下载中…' : '下载原始 FIT'}
          </button>
          <button
            type="button"
            role="menuitem"
            className="activity-actions__danger"
            onClick={() => openDialog('delete')}
          >
            删除运动
          </button>
        </div>
      )}
      {mode && (
        <div
          className="activity-dialog__overlay"
          onMouseDown={(event) => event.target === event.currentTarget && closeDialog()}
        >
          <div
            ref={dialogRef}
            className="activity-dialog"
            data-vc="activity-management-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            tabIndex={-1}
            onKeyDown={dialogKeyDown}
          >
            <h2 id={titleId}>{MODE_COPY[mode].title}</h2>
            {mode === 'rename' && (
              <label className="activity-dialog__field">
                <span>运动名称</span>
                <input
                  ref={inputRef}
                  aria-label="运动名称"
                  value={input}
                  maxLength={256}
                  disabled={busy}
                  onChange={(event) => setInput(event.target.value)}
                  onKeyDown={(event) => event.key === 'Enter' && void submit()}
                />
                <small className="num">{input.trim().length} / 255</small>
              </label>
            )}
            {mode === 'restore' && (
              <p>
                将移除“{activity.name}
                ”的自定义名称，并使用服务端重新返回的解析标题。提交前不会预览恢复后的名称。
              </p>
            )}
            {mode === 'delete' && (
              <p>将永久删除“{activity.name}”、对应导入记录和私有原始文件。此操作不可撤销。</p>
            )}
            {error && (
              <p className="activity-dialog__error" role="alert">
                {error}
              </p>
            )}
            <div className="activity-dialog__actions">
              <button
                type="button"
                className="activity-dialog__cancel"
                disabled={busy}
                onClick={closeDialog}
              >
                取消
              </button>
              <button
                type="button"
                className={
                  mode === 'delete'
                    ? 'activity-dialog__submit activity-dialog__submit--danger'
                    : 'activity-dialog__submit'
                }
                disabled={busy}
                onClick={() => void submit()}
              >
                {busy && <span className="activity-actions__spinner" aria-hidden="true" />}
                {busy ? MODE_COPY[mode].busy : MODE_COPY[mode].submit}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
