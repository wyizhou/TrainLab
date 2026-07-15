import { useMemo } from 'react'
import './TimeSeriesChart.css'

// One downsampled time-series curve for the activity detail (contract C-8).
// Design 3.2: Y axis always 3 ticks + source-field annotation. X-axis ticks are
// binned by breakpoint (AC-008b-2): desktop 5, mobile 3 (first/middle/last).

export type TimeSeriesChartProps = {
  title: string
  unit: string
  // FIT field the series comes from, e.g. "enhanced_speed" — shown as 来源.
  sourceField: string
  // Already downsampled values; null = gap (missing sample), skipped in the line.
  values: (number | null)[]
  // Elapsed seconds for each value, used to derive the X-axis time ticks.
  timesSec: number[]
  // Number of X-axis ticks: 5 on desktop, 3 on mobile (AC-008b-2). Defaults to 5.
  xTickCount?: number
  // Formats a Y value for tick labels (e.g. pace seconds -> m'ss").
  formatValue?: (v: number) => string
}

const WIDTH = 340
const HEIGHT = 120
const PAD_LEFT = 40
const PAD_RIGHT = 10
const PAD_TOP = 12
const PAD_BOTTOM = 22
const PLOT_W = WIDTH - PAD_LEFT - PAD_RIGHT
const PLOT_H = HEIGHT - PAD_TOP - PAD_BOTTOM

function formatClock(totalSec: number): string {
  const m = Math.floor(totalSec / 60)
  const s = Math.round(totalSec % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

export function TimeSeriesChart({
  title,
  unit,
  sourceField,
  values,
  timesSec,
  xTickCount = 5,
  formatValue = (v) => `${Math.round(v)}`,
}: TimeSeriesChartProps) {
  const geometry = useMemo(() => {
    const present = values
      .map((v, i) => ({ v, i }))
      .filter((p): p is { v: number; i: number } => p.v !== null && Number.isFinite(p.v))
    if (present.length === 0) return null

    const nums = present.map((p) => p.v)
    const min = Math.min(...nums)
    const max = Math.max(...nums)
    const range = max - min || 1
    const n = values.length
    const xAt = (i: number) => PAD_LEFT + (n === 1 ? PLOT_W / 2 : (PLOT_W * i) / (n - 1))
    const yAt = (v: number) => PAD_TOP + PLOT_H * (1 - (v - min) / range)

    const coords = present.map((p) => ({ x: xAt(p.i), y: yAt(p.v) }))
    const polyline = coords.map((c) => `${c.x},${c.y}`).join(' ')

    // Evenly spaced X ticks across the full duration; count binned by breakpoint
    // (desktop 5 / mobile 3). At 3 the indices land on first / middle / last.
    const tickN = Math.min(xTickCount, n)
    const xTicks = Array.from({ length: tickN }, (_, k) => {
      const idx = Math.round((k * (n - 1)) / (tickN - 1 || 1))
      return { x: xAt(idx), sec: timesSec[idx] ?? 0 }
    })

    return { min, max, mid: (min + max) / 2, polyline, coords, xTicks }
  }, [values, timesSec, xTickCount])

  if (!geometry) {
    return (
      <div className="ts-chart ts-chart--empty" data-testid="ts-chart">
        <div className="ts-chart__head">
          <span className="ts-chart__title">{title}</span>
        </div>
        <p className="ts-chart__empty">无数据</p>
      </div>
    )
  }

  const yTicks = [
    { value: geometry.max, y: PAD_TOP },
    { value: geometry.mid, y: PAD_TOP + PLOT_H / 2 },
    { value: geometry.min, y: PAD_TOP + PLOT_H },
  ]

  return (
    <div className="ts-chart" data-testid="ts-chart">
      <div className="ts-chart__head">
        <span className="ts-chart__title">{title}</span>
        <span className="ts-chart__source num" data-testid="ts-source">
          来源：{sourceField}
        </span>
      </div>
      <svg
        className="ts-chart__svg"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        width={WIDTH}
        height={HEIGHT}
        role="img"
        aria-label={`${title}时序曲线（${unit}）`}
        data-testid="ts-svg"
      >
        {yTicks.map((tick) => (
          <g key={`y-${tick.y}`}>
            <line
              className="ts-chart__grid"
              x1={PAD_LEFT}
              y1={tick.y}
              x2={WIDTH - PAD_RIGHT}
              y2={tick.y}
            />
            <text
              className="ts-chart__tick"
              data-testid="ts-ytick"
              x={PAD_LEFT - 5}
              y={tick.y + 3}
              textAnchor="end"
            >
              {formatValue(tick.value)}
            </text>
          </g>
        ))}
        {geometry.xTicks.map((tick, k) => (
          <text
            key={`x-${k}`}
            className="ts-chart__tick"
            data-testid="ts-xtick"
            x={tick.x}
            y={HEIGHT - 6}
            textAnchor="middle"
          >
            {formatClock(tick.sec)}
          </text>
        ))}
        <polyline className="ts-chart__line" points={geometry.polyline} />
      </svg>
    </div>
  )
}
