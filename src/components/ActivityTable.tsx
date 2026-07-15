import {
  formatDistance,
  formatDuration,
  formatPaceOrPower,
  TYPE_DOT_SLUG,
  type Activity,
} from '../activities/activityData'
import './ActivityTable.css'

type ActivityTableProps = {
  activities: Activity[]
  selectedIds: ReadonlySet<string>
  onToggle: (id: string) => void
  onDownload: (id: string) => void
  onOpen?: (id: string) => void
}

// Presentational list for the current page slice (contract C-7). Selection,
// filtering and paging state live in the page above; this only renders rows.
export function ActivityTable({
  activities,
  selectedIds,
  onToggle,
  onDownload,
  onOpen,
}: ActivityTableProps) {
  return (
    // Root mirrors data-vc="activities-table" (C-7 AC-007c-1 硬要求): the scroll
    // container carries the panel bg / borderPanel / radiusCard + overflow-x auto;
    // the inner __grid holds the min-width:960px column track. Hidden on mobile
    // via CSS (@media width<640) so ActivityCardList takes over below the break.
    <div className="activity-table" data-vc="activities-table" data-testid="activity-table">
      <div className="activity-table__grid">
        <div className="activity-table__row activity-table__row--head" role="row">
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

        {activities.map((a) => (
          <div
            key={a.id}
            className="activity-table__row"
            role="row"
            data-testid="activity-row"
            onClick={() => onOpen?.(a.id)}
          >
            <input
              type="checkbox"
              className="activity-table__check"
              aria-label={`选择 ${a.name}`}
              checked={selectedIds.has(a.id)}
              onChange={() => onToggle(a.id)}
              onClick={(event) => event.stopPropagation()}
            />
            <span className="activity-table__date num">{a.date}</span>
            <span className="activity-table__type">
              <span className={`activity-dot activity-dot--${TYPE_DOT_SLUG[a.type]}`} />
              {a.type}
            </span>
            <span className="activity-table__name">{a.name}</span>
            <span className="num">{formatDistance(a.distanceKm)}</span>
            <span className="num">{formatDuration(a.durationSec)}</span>
            <span className="num">{a.avgHr}</span>
            <span className="num">{formatPaceOrPower(a)}</span>
            <span className="activity-table__src">{a.source}</span>
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
          </div>
        ))}
      </div>
    </div>
  )
}
