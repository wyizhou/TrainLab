import { shortDate, type SleepRecord } from './healthData'
import './SleepStackChart.css'

// Stacked sleep-stage bars (contract C-9). Each column is one night; segments
// stack 深 (bottom) → 浅 → REM (top). Records arrive ordered oldest→newest from
// the caller, already windowed to the breakpoint's bar count (mobile 7 / tablet+
// desktop 14, AC-009b-1) — one bar per record. The window size is carried in the
// caller-supplied `title` (含「近 7/14 天」) so it stays in sync with the count.

export type SleepStackChartProps = {
  records: SleepRecord[]
  title: string
}

const STAGES = [
  { key: 'deepMin', label: '深睡', slug: 'deep' },
  { key: 'lightMin', label: '浅睡', slug: 'light' },
  { key: 'remMin', label: 'REM', slug: 'rem' },
] as const

export function SleepStackChart({ records, title }: SleepStackChartProps) {
  if (records.length === 0) {
    return (
      <div className="sleep-stack sleep-stack--empty" data-testid="sleep-stack">
        <p className="sleep-stack__title" data-testid="sleep-title">
          {title}
        </p>
        <p className="sleep-stack__empty">无数据</p>
      </div>
    )
  }

  return (
    <div className="sleep-stack" data-vc="sleep-chart" data-testid="sleep-stack">
      <div className="sleep-stack__head">
        <p className="sleep-stack__title" data-testid="sleep-title">
          {title}睡眠结构
        </p>
        <ul className="sleep-stack__legend" data-testid="sleep-legend">
          {STAGES.map((stage) => (
            <li key={stage.slug} className="sleep-stack__key">
              <span className={`sleep-stack__swatch sleep-stack__swatch--${stage.slug}`} />
              {stage.label}
            </li>
          ))}
        </ul>
      </div>
      <div className="sleep-stack__bars" data-vc="sleep-chart-bars">
        {records.map((record) => (
          <div className="sleep-stack__bar-slot" data-testid="sleep-bar" key={record.date}>
            <div className="sleep-stack__bar">
              <span
                className="sleep-stack__seg sleep-stack__seg--rem"
                data-vc="sleep-chart-bar-rem"
                style={{ height: `${record.remMin / 4}px` }}
              />
              <span
                className="sleep-stack__seg sleep-stack__seg--light"
                data-vc="sleep-chart-bar-light"
                style={{ height: `${record.lightMin / 4}px` }}
              />
              <span
                className="sleep-stack__seg sleep-stack__seg--deep"
                data-vc="sleep-chart-bar-deep"
                style={{ height: `${record.deepMin / 4}px` }}
              />
            </div>
            <span className="sleep-stack__date num">{shortDate(record.date).slice(3)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
