import { useEffect, useMemo, useState } from 'react'
import './ScopeBar.css'

export type ScopeActivity = {
  id: string
  date: string
  name: string
  type: string
  // Days ago the activity happened (0 = today). Used to resolve the day-range filter.
  offsetDays: number
}

export type EffectiveScope = {
  rangeDays: number
  pickedIds: string[]
  includeHealth: boolean
  includeHabits: boolean
  // The activities that fall inside the effective range (picked overrides the day chips).
  activities: ScopeActivity[]
  summary: string
}

type ScopeBarProps = {
  activities?: ScopeActivity[]
  onScopeChange?: (scope: EffectiveScope) => void
  hideSummary?: boolean
}

// C-4: the four day-range chips; 3 is the default.
const RANGE_DAYS = [3, 7, 15, 30] as const
const DEFAULT_RANGE = 3

// Standalone demo dataset so the bar renders inside the analysis shell before
// real activity data (C-7 / C-8) is wired in. offsetDays spans the chips so the
// day filter is observable.
const DEFAULT_ACTIVITIES: ScopeActivity[] = [
  { id: 'a1', date: '07-11', name: '晨间轻松跑', type: '跑步', offsetDays: 0 },
  { id: 'a2', date: '07-10', name: '力量训练', type: '力量', offsetDays: 1 },
  { id: 'a3', date: '07-08', name: '骑行通勤', type: '骑行', offsetDays: 3 },
  { id: 'a4', date: '07-05', name: '长距离慢跑', type: '跑步', offsetDays: 6 },
  { id: 'a5', date: '06-30', name: '游泳', type: '游泳', offsetDays: 11 },
  { id: 'a6', date: '06-20', name: '越野跑', type: '越野跑', offsetDays: 21 },
]

export function ScopeBar({
  activities = DEFAULT_ACTIVITIES,
  onScopeChange,
  hideSummary = false,
}: ScopeBarProps) {
  const [rangeDays, setRangeDays] = useState<number>(DEFAULT_RANGE)
  const [pickedIds, setPickedIds] = useState<string[]>([])
  const [includeHealth, setIncludeHealth] = useState(true)
  const [includeHabits, setIncludeHabits] = useState(true)
  const [pickOpen, setPickOpen] = useState(false)

  // Picking specific activities overrides the day range; selecting a day chip
  // clears the manual picks (matches the design source of truth).
  const selectRange = (days: number) => {
    setRangeDays(days)
    setPickedIds([])
  }

  const togglePick = (id: string) => {
    setPickedIds((prev) => (prev.includes(id) ? prev.filter((pid) => pid !== id) : [...prev, id]))
  }

  const scopedActivities = useMemo(
    () =>
      pickedIds.length > 0
        ? activities.filter((a) => pickedIds.includes(a.id))
        : activities.filter((a) => a.offsetDays < rangeDays),
    [activities, pickedIds, rangeDays],
  )

  const summary = useMemo(() => {
    const parts = [
      pickedIds.length > 0 ? `已勾选 ${pickedIds.length} 次运动` : `最近 ${rangeDays} 天运动数据`,
    ]
    if (includeHealth) parts.push('健康记录')
    if (includeHabits) parts.push('习惯记录')
    return parts.join(' + ')
  }, [pickedIds, rangeDays, includeHealth, includeHabits])

  const scope = useMemo<EffectiveScope>(
    () => ({
      rangeDays,
      pickedIds,
      includeHealth,
      includeHabits,
      activities: scopedActivities,
      summary,
    }),
    [rangeDays, pickedIds, includeHealth, includeHabits, scopedActivities, summary],
  )

  useEffect(() => {
    onScopeChange?.(scope)
  }, [scope, onScopeChange])

  return (
    <div className="scope-bar" data-testid="scope-bar">
      <div className="scope-bar__row" data-vc="analysis-controls">
        <span className="scope-bar__label">数据范围</span>
        {RANGE_DAYS.map((days) => {
          const active = pickedIds.length === 0 && days === rangeDays
          const chipClass = active ? 'scope-bar__chip scope-bar__chip--active' : 'scope-bar__chip'
          return (
            <button
              key={days}
              type="button"
              className={chipClass}
              // G-fidelity: mirror the pixel-contract anchor onto the chip root so
              // Keep the visual-contract selector stable for C-4 AC-004c-1 checks.
              data-vc={active ? 'scope-chip-selected' : 'scope-chip'}
              aria-pressed={active}
              onClick={() => selectRange(days)}
            >
              {days} 天
            </button>
          )
        })}
        <button
          type="button"
          className={
            pickedIds.length > 0
              ? 'scope-bar__picker scope-bar__picker--active'
              : 'scope-bar__picker'
          }
          aria-expanded={pickOpen}
          data-vc="activity-picker-trigger"
          onClick={() => setPickOpen((open) => !open)}
        >
          选择运动 (<span className="num">{pickedIds.length}</span>)
        </button>

        <div className="scope-bar__toggles">
          <label className="scope-bar__toggle">
            <input
              type="checkbox"
              checked={includeHealth}
              onChange={(event) => setIncludeHealth(event.target.checked)}
            />
            附带健康记录
          </label>
          <label className="scope-bar__toggle">
            <input
              type="checkbox"
              checked={includeHabits}
              onChange={(event) => setIncludeHabits(event.target.checked)}
            />
            附带习惯记录
          </label>
        </div>
      </div>

      {pickOpen && (
        <ul className="scope-bar__picklist" data-vc="activity-picker" data-testid="scope-picklist">
          {activities.map((activity) => (
            <li key={activity.id} className="scope-bar__pickrow">
              <label className="scope-bar__pickitem">
                <input
                  type="checkbox"
                  checked={pickedIds.includes(activity.id)}
                  onChange={() => togglePick(activity.id)}
                />
                <span className="scope-bar__pickdate num">{activity.date}</span>
                <span className="scope-bar__pickname">{activity.name}</span>
                <span className="scope-bar__picktype">{activity.type}</span>
              </label>
            </li>
          ))}
        </ul>
      )}

      {!hideSummary && (
        <div className="scope-bar__summary" data-testid="scope-summary">
          当前范围：{summary}
          <span className="scope-bar__effective" data-testid="scope-effective">
            （生效 <span className="num">{scopedActivities.length}</span> 次运动）
          </span>
        </div>
      )}
    </div>
  )
}
