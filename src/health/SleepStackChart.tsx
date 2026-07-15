import { useMemo } from 'react'
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

const WIDTH = 340
const HEIGHT = 150
const PAD_LEFT = 34
const PAD_RIGHT = 8
const PAD_TOP = 10
const PAD_BOTTOM = 22
const PLOT_W = WIDTH - PAD_LEFT - PAD_RIGHT
const PLOT_H = HEIGHT - PAD_TOP - PAD_BOTTOM

const STAGES = [
  { key: 'deepMin', label: '深睡', slug: 'deep' },
  { key: 'lightMin', label: '浅睡', slug: 'light' },
  { key: 'remMin', label: 'REM', slug: 'rem' },
] as const

export function SleepStackChart({ records, title }: SleepStackChartProps) {
  const geometry = useMemo(() => {
    if (records.length === 0) return null
    const max = Math.max(...records.map((r) => r.totalMin)) || 1
    const n = records.length
    const slot = PLOT_W / n
    const barW = Math.max(3, slot * 0.6)
    const bars = records.map((r, i) => {
      const cx = PAD_LEFT + slot * (i + 0.5)
      let yBottom = PAD_TOP + PLOT_H
      const segs = STAGES.map((stage) => {
        const h = (r[stage.key] / max) * PLOT_H
        yBottom -= h
        return { slug: stage.slug, y: yBottom, h }
      })
      return { x: cx - barW / 2, segs, date: r.date, showLabel: i % 3 === 0 }
    })
    return { bars, barW, maxHours: max / 60 }
  }, [records])

  if (!geometry) {
    return (
      <div className="sleep-stack sleep-stack--empty" data-testid="sleep-stack">
        <p className="sleep-stack__title" data-testid="sleep-title">
          {title}
        </p>
        <p className="sleep-stack__empty">无数据</p>
      </div>
    )
  }

  // Representative stacked column carrying the pixel-contract data-vc anchors
  // (C-9 AC-009c-1) — one bar for the latest night, segment heights proportional
  // to each stage's minutes (flex-grow, so no bare px leaks past G-token). deep
  // (bottom, radiusSleepDeep) · light (mid, radius 0) · rem (top, radiusSleepRem).
  // The multi-bar SVG chart below is unchanged (rev 2 / AC-009b bar-count intact).
  const latest = records[records.length - 1]

  return (
    <div className="sleep-stack" data-testid="sleep-stack">
      <p className="sleep-stack__title" data-testid="sleep-title">
        {title}
      </p>
      <div className="sleep-stack__vc" data-testid="sleep-vc-bar">
        <span
          className="sleep-stack__vc-seg sleep-stack__vc-seg--rem"
          data-vc="sleep-chart-bar-rem"
          style={{ flexGrow: latest.remMin }}
        />
        <span
          className="sleep-stack__vc-seg sleep-stack__vc-seg--light"
          data-vc="sleep-chart-bar-light"
          style={{ flexGrow: latest.lightMin }}
        />
        <span
          className="sleep-stack__vc-seg sleep-stack__vc-seg--deep"
          data-vc="sleep-chart-bar-deep"
          style={{ flexGrow: latest.deepMin }}
        />
      </div>
      <svg
        className="sleep-stack__svg"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        width={WIDTH}
        height={HEIGHT}
        role="img"
        aria-label={`${title}睡眠分期堆叠柱`}
        data-testid="sleep-stack-svg"
      >
        <text className="sleep-stack__tick" x={PAD_LEFT - 5} y={PAD_TOP + 3} textAnchor="end">
          {geometry.maxHours.toFixed(1)}h
        </text>
        <text className="sleep-stack__tick" x={PAD_LEFT - 5} y={PAD_TOP + PLOT_H} textAnchor="end">
          0
        </text>
        {geometry.bars.map((bar) => (
          <g key={bar.date} data-testid="sleep-bar">
            {bar.segs.map((seg) => (
              <rect
                key={seg.slug}
                className={`sleep-stack__seg sleep-stack__seg--${seg.slug}`}
                x={bar.x}
                y={seg.y}
                width={geometry.barW}
                height={Math.max(0, seg.h)}
              />
            ))}
            {bar.showLabel && (
              <text
                className="sleep-stack__tick"
                x={bar.x + geometry.barW / 2}
                y={HEIGHT - 6}
                textAnchor="middle"
              >
                {shortDate(bar.date)}
              </text>
            )}
          </g>
        ))}
      </svg>
      <ul className="sleep-stack__legend" data-testid="sleep-legend">
        {STAGES.map((stage) => (
          <li key={stage.slug} className="sleep-stack__key">
            <span className={`sleep-stack__swatch sleep-stack__swatch--${stage.slug}`} />
            {stage.label}
          </li>
        ))}
      </ul>
    </div>
  )
}
