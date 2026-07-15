import { useState, type KeyboardEvent } from 'react'
import { useBreakpoint } from '../hooks/useBreakpoint'
import type { Session } from '../hooks/useSessions'
import './SessionRail.css'

type SessionRailProps = {
  sessions: Session[]
  activeId: string
  onCreate: () => void
  onSelect: (id: string) => void
  onRename: (id: string, name: string) => void
  onDelete: (id: string) => void
}

export function SessionRail({
  sessions,
  activeId,
  onCreate,
  onSelect,
  onRename,
  onDelete,
}: SessionRailProps) {
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')

  // C-3 (design_rev 2): desktop/wide keep the 212px aside; mobile/tablet degrade
  // to a top dropdown. Rendering is breakpoint-conditional (not CSS display:none)
  // so the aside is truly absent from the DOM below 980px (AC-003b-1).
  const breakpoint = useBreakpoint()
  const isRail = breakpoint === 'desktop' || breakpoint === 'wide'

  const startEdit = (session: Session) => {
    setEditingId(session.id)
    setDraft(session.name)
  }

  const commit = () => {
    if (editingId == null) return
    onRename(editingId, draft)
    setEditingId(null)
  }

  const cancel = () => setEditingId(null)

  // Enter confirms, Esc cancels. Blur cancels (discard) to avoid the Esc→blur
  // race committing a rename the user meant to abandon.
  const handleRenameKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') {
      event.preventDefault()
      commit()
    } else if (event.key === 'Escape') {
      event.preventDefault()
      cancel()
    }
  }

  if (!isRail) {
    // Mobile/tablet: no aside, just a session dropdown + new button.
    return (
      <div
        className="session-rail__mobile"
        data-vc="analysis-session-select"
        data-testid="session-rail-mobile"
      >
        <select
          className="session-rail__select-menu"
          aria-label="选择会话"
          value={activeId}
          onChange={(event) => onSelect(event.target.value)}
        >
          {sessions.map((session) => (
            <option key={session.id} value={session.id}>
              {session.name}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="session-rail__new"
          aria-label="新建会话"
          onClick={onCreate}
        >
          ＋ 新建
        </button>
      </div>
    )
  }

  return (
    <aside
      className="session-rail__desktop"
      data-testid="session-rail-desktop"
      data-vc="session-rail"
    >
      <button type="button" className="session-rail__new" aria-label="新建会话" onClick={onCreate}>
        ＋ 新建会话
      </button>
      <ul className="session-rail__list" data-vc="session-list">
        {sessions.map((session) => {
          const active = session.id === activeId
          const itemClass = active
            ? 'session-rail__item session-rail__item--active'
            : 'session-rail__item'
          return (
            <li
              key={session.id}
              className={itemClass}
              data-testid="session-item"
              data-vc={active ? 'session-rail-item-active' : 'session-rail-item'}
            >
              {editingId === session.id ? (
                <input
                  className="session-rail__rename"
                  aria-label="会话名称"
                  autoFocus
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={handleRenameKey}
                  onBlur={cancel}
                />
              ) : (
                <>
                  <button
                    type="button"
                    className="session-rail__select"
                    onClick={() => onSelect(session.id)}
                    onDoubleClick={() => startEdit(session)}
                  >
                    <span className="session-rail__name">{session.name}</span>
                    <span className="session-rail__count num">{session.messageCount} 条消息</span>
                  </button>
                  <button
                    type="button"
                    className="session-rail__action"
                    aria-label={`重命名 ${session.name}`}
                    onClick={() => startEdit(session)}
                  >
                    ✎
                  </button>
                  <button
                    type="button"
                    className="session-rail__action"
                    aria-label={`删除 ${session.name}`}
                    onClick={() => onDelete(session.id)}
                  >
                    ✕
                  </button>
                </>
              )}
            </li>
          )
        })}
      </ul>
      <p className="session-rail__note">
        衍生指标(TSS / CTL / ATL / TSB…)仅在 AI 回复中产出,系统不预计算。
      </p>
    </aside>
  )
}
