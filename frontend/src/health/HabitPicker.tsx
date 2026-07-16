import { useMemo, useState } from 'react'
import {
  generateHabitSeed,
  HABIT_GROUPS,
  HEALTH_TODAY,
  selectedFactorCount,
  type HabitRecords,
} from './healthData'
import './HabitPicker.css'

// Habit factor logger (contract C-9). Pick a date (defaults to 当天), toggle the
// four time-of-day factor groups; selections are stored per date (供 AI 作关联因
// 子) and the 已记录计数 reflects how many dates have any factor recorded.
// Storage is in-component demo state (G-mock, no backend).

export function HabitPicker() {
  const [records, setRecords] = useState<HabitRecords>(generateHabitSeed)
  const [date, setDate] = useState<string>(HEALTH_TODAY)

  const selected = useMemo(() => new Set(records[date] ?? []), [records, date])
  const count = selectedFactorCount(records, date)

  const toggle = (factorId: string) => {
    setRecords((prev) => {
      const current = new Set(prev[date] ?? [])
      if (current.has(factorId)) current.delete(factorId)
      else current.add(factorId)
      return { ...prev, [date]: Array.from(current) }
    })
  }

  return (
    <div className="habit-picker" data-testid="habit-picker">
      <div className="habit-picker__bar" data-vc="habit-date-toolbar">
        <label className="habit-picker__date">
          日期
          <input
            type="date"
            aria-label="选择日期"
            value={date}
            max={HEALTH_TODAY}
            onChange={(event) => setDate(event.target.value)}
          />
        </label>
        <span className="habit-picker__today">{date === HEALTH_TODAY ? '今天' : ''}</span>
        <span className="habit-picker__count" data-testid="habit-count">
          已记录 <span className="num">{count}</span> 项
        </span>
      </div>

      <div className="habit-picker__groups" data-vc="habit-groups">
        {HABIT_GROUPS.map((group) => (
          <section key={group.id} className="habit-picker__group" data-vc="habit-group">
            <h2 className="habit-picker__legend">
              <span className={`habit-picker__dot habit-picker__dot--${group.id}`} />
              {group.label}
            </h2>
            <div className="habit-picker__chips">
              {group.factors.map((factor) => {
                const on = selected.has(factor.id)
                return (
                  <button
                    key={factor.id}
                    type="button"
                    aria-pressed={on}
                    className={
                      on ? 'habit-picker__chip habit-picker__chip--on' : 'habit-picker__chip'
                    }
                    onClick={() => toggle(factor.id)}
                  >
                    {factor.label}
                  </button>
                )
              })}
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}
