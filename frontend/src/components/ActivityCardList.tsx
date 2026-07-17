import {
  formatDistance,
  formatDuration,
  formatActivityDate,
  formatPaceOrPower,
  TYPE_DOT_SLUG,
  type Activity,
} from '../activities/activityData'
import type { ReactNode } from 'react'
import './ActivityCardList.css'

type ActivityCardListProps = {
  activities: Activity[]
  selectedIds: ReadonlySet<string>
  onToggle: (id: string) => void
  onDownload: (id: string) => void
  onOpen?: (id: string) => void
  isOpenable?: (id: string) => boolean
  isSelectable?: (id: string) => boolean
  isDownloadable?: (id: string) => boolean
  children?: ReactNode
}

// Mobile form of the activity list (contract C-7, AC-007b-1 / AC-007c-1). The
// desktop ActivityTable carries a min-width:960px grid that would overflow small
// viewports, so on mobile the table is hidden (CSS) and this card list renders
// instead. Root mirrors data-vc="activities-card-list" (AC-007c-1 硬要求). The
// page mounts this only at the mobile breakpoint, so on desktop it is absent
// from the DOM (AC-007c-1: desktop「不在 DOM」). Same selection / download / open
// callbacks as the table so rev 1 behaviour (filter, page, batch count) holds.
export function ActivityCardList({
  activities,
  selectedIds,
  onToggle,
  onDownload,
  onOpen,
  isOpenable,
  isSelectable,
  isDownloadable,
  children,
}: ActivityCardListProps) {
  return (
    <div
      className="activity-card-list"
      data-vc="activities-card-list"
      data-testid="activity-card-list"
    >
      {activities.map((a) => {
        const openable = onOpen !== undefined && (isOpenable?.(a.id) ?? true)
        const selectable = isSelectable?.(a.id) ?? true
        const downloadable = isDownloadable?.(a.id) ?? true
        return (
          <div
            key={a.id}
            className={openable ? 'activity-card' : 'activity-card activity-card--not-openable'}
            data-vc="activity-card"
            data-testid="activity-card"
            onClick={openable ? () => onOpen(a.id) : undefined}
          >
            <div className="activity-card__top">
              {selectable && (
                <input
                  type="checkbox"
                  className="activity-card__check"
                  aria-label={`选择 ${a.name}`}
                  checked={selectedIds.has(a.id)}
                  onChange={() => onToggle(a.id)}
                  onClick={(event) => event.stopPropagation()}
                />
              )}
              <span className={`activity-dot activity-dot--${TYPE_DOT_SLUG[a.type]}`} />
              <span className="activity-card__name">{a.name}</span>
              {downloadable && (
                <button
                  type="button"
                  className="activity-card__download"
                  aria-label={`下载 ${a.name} 的 FIT`}
                  onClick={(event) => {
                    event.stopPropagation()
                    onDownload(a.id)
                  }}
                >
                  FIT ↓
                </button>
              )}
            </div>

            <dl className="activity-card__metrics" data-vc="activity-card-metrics">
              <div>
                <dt>距离</dt>
                <dd className="num">{formatDistance(a.distanceKm)}</dd>
              </div>
              <div>
                <dt>时长</dt>
                <dd className="num">{formatDuration(a.durationSec)}</dd>
              </div>
              <div>
                <dt>平均心率</dt>
                <dd className="num">{a.avgHr === null ? '—' : `${a.avgHr} bpm`}</dd>
              </div>
              <div>
                <dt>配速 / 功率</dt>
                <dd className="num">{formatPaceOrPower(a)}</dd>
              </div>
            </dl>

            <div className="activity-card__foot">
              <span className="activity-card__date num">{formatActivityDate(a.date)}</span>
              <span className="activity-card__type">{a.type}</span>
              <span className="activity-card__src">{a.source}</span>
            </div>
          </div>
        )
      })}
      {children}
    </div>
  )
}
