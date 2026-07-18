import {
  formatDistance,
  formatDuration,
  formatActivityDate,
  formatPaceOrPower,
  TYPE_DOT_SLUG,
  type Activity,
} from '../activities/activityData'
import type { ReactNode } from 'react'
import './ActivityTable.css'

type ActivityTableProps = {
  activities: Activity[]
  selectedIds: ReadonlySet<string>
  onToggle: (id: string) => void
  onDownload: (id: string) => void
  onOpen?: (id: string) => void
  isOpenable?: (id: string) => boolean
  isSelectable?: (id: string) => boolean
  isDownloadable?: (id: string) => boolean
  renderActions?: (activity: Activity) => ReactNode
  children?: ReactNode
}

// Presentational list for the current page slice (contract C-7). Selection,
// filtering and paging state live in the page above; this only renders rows.
export function ActivityTable({
  activities,
  selectedIds,
  onToggle,
  onDownload,
  onOpen,
  isOpenable,
  isSelectable,
  isDownloadable,
  renderActions,
  children,
}: ActivityTableProps) {
  return (
    // Root mirrors data-vc="activities-table" (C-7 AC-007c-1 硬要求): the scroll
    // container carries the panel bg / borderPanel / radiusCard + overflow-x auto;
    // the inner __grid holds the min-width:960px column track. Hidden on mobile
    // via CSS (@media width<640) so ActivityCardList takes over below the break.
    <div className="activity-table" data-vc="activities-table" data-testid="activity-table">
      <div className="activity-table__grid">
        <div
          className="activity-table__row activity-table__row--head"
          data-vc="activities-table-header"
          role="row"
        >
          <span />
          <span>日期</span>
          <span>类型</span>
          <span>名称</span>
          <span>距离</span>
          <span>时长</span>
          <span>平均心率</span>
          <span>配速 / 功率</span>
          <span>来源</span>
          <span />
        </div>

        {activities.map((a) => {
          const openable = onOpen !== undefined && (isOpenable?.(a.id) ?? true)
          const selectable = isSelectable?.(a.id) ?? true
          const downloadable = isDownloadable?.(a.id) ?? true
          return (
            <div
              key={a.id}
              className={
                openable
                  ? 'activity-table__row'
                  : 'activity-table__row activity-table__row--not-openable'
              }
              role="row"
              data-vc="activity-table-row"
              data-testid="activity-row"
              onClick={openable ? () => onOpen(a.id) : undefined}
            >
              {selectable ? (
                <input
                  type="checkbox"
                  className="activity-table__check"
                  aria-label={`选择 ${a.name}`}
                  checked={selectedIds.has(a.id)}
                  onChange={() => onToggle(a.id)}
                  onClick={(event) => event.stopPropagation()}
                />
              ) : (
                <span aria-hidden="true" />
              )}
              <span className="activity-table__date num">{formatActivityDate(a.date)}</span>
              <span className="activity-table__type">
                <span className={`activity-dot activity-dot--${TYPE_DOT_SLUG[a.type]}`} />
                {a.type}
              </span>
              <span className="activity-table__name">{a.name}</span>
              <span className="num">{formatDistance(a.distanceKm)}</span>
              <span className="num">{formatDuration(a.durationSec)}</span>
              <span className="num">{a.avgHr === null ? '—' : `${a.avgHr} bpm`}</span>
              <span className="num">{formatPaceOrPower(a)}</span>
              <span className="activity-table__src">{a.source}</span>
              {renderActions ? (
                renderActions(a)
              ) : downloadable ? (
                <button
                  type="button"
                  className="activity-table__download"
                  aria-label={`下载 ${a.name} 的 FIT`}
                  onClick={(event) => {
                    event.stopPropagation()
                    onDownload(a.id)
                  }}
                >
                  FIT ↓
                </button>
              ) : (
                <span aria-hidden="true" />
              )}
            </div>
          )
        })}
        {children}
      </div>
    </div>
  )
}
