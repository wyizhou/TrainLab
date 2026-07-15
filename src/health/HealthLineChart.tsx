import { useMemo } from 'react'
import { shortDate } from './healthData'
import './HealthLineChart.css'

// A single daily-value trend line for the health tabs (contract C-9: 体重/静息
// 心率/HRV 近 30 天曲线). Geometry mirrors TimeSeriesChart (3 Y ticks + up to 5
// X ticks); points are pre-sliced/ordered oldest→newest by the caller.

export type LinePoint = { date: string; value: number }

export type HealthLineChartProps = {
  title: string
  unit: string
  points: LinePoint[]
  // A modifier slug picking the stroke colour token (see HealthLineChart.css).
  colorSlug?: string
  formatValue?: (v: number) => string
}

const WIDTH = 340
const HEIGHT = 130
const PAD_LEFT = 40
const PAD_RIGHT = 10
const PAD_TOP = 12
const PAD_BOTTOM = 24
const PLOT_W = WIDTH - PAD_LEFT - PAD_RIGHT
const PLOT_H = HEIGHT - PAD_TOP - PAD_BOTTOM
const X_TICKS = 5

export function HealthLineChart({
  title,
  unit,
  points,
  colorSlug = 'accent',
  formatValue = (v) => `${Math.round(v)}`,
}: HealthLineChartProps) {
  const geometry = useMemo(() => {
    if (points.length === 0) return null
    const nums = points.map((p) => p.value)
    const min = Math.min(...nums)
    const max = Math.max(...nums)
    const range = max - min || 1
    const n = points.length
    const xAt = (i: number) => PAD_LEFT + (n === 1 ? PLOT_W / 2 : (PLOT_W * i) / (n - 1))
    const yAt = (v: number) => PAD_TOP + PLOT_H * (1 - (v - min) / range)

    const polyline = points.map((p, i) => `${xAt(i)},${yAt(p.value)}`).join(' ')
    const tickCount = Math.min(X_TICKS, n)
    const xTicks = Array.from({ length: tickCount }, (_, k) => {
      const idx = Math.round((k * (n - 1)) / (tickCount - 1 || 1))
      return { x: xAt(idx), date: points[idx].date }
    })
    return { min, max, mid: (min + max) / 2, polyline, xTicks }
  }, [points])

  if (!geometry) {
    return (
      <div className="health-line health-line--empty" data-testid="health-line">
        <span className="health-line__title">{title}</span>
        <p className="health-line__empty">无数据</p>
      </div>
    )
  }

  const yTicks = [
    { value: geometry.max, y: PAD_TOP },
    { value: geometry.mid, y: PAD_TOP + PLOT_H / 2 },
    { value: geometry.min, y: PAD_TOP + PLOT_H },
  ]

  return (
    <div className="health-line" data-testid="health-line">
      <div className="health-line__head">
        <span className="health-line__title">{title}</span>
        <span className="health-line__unit num">{unit}</span>
      </div>
      <svg
        className="health-line__svg"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        width={WIDTH}
        height={HEIGHT}
        role="img"
        aria-label={`${title}趋势曲线（${unit}）`}
        data-testid="health-line-svg"
      >
        {yTicks.map((tick) => (
          <g key={`y-${tick.y}`}>
            <line
              className="health-line__grid"
              x1={PAD_LEFT}
              y1={tick.y}
              x2={WIDTH - PAD_RIGHT}
              y2={tick.y}
            />
            <text className="health-line__tick" x={PAD_LEFT - 5} y={tick.y + 3} textAnchor="end">
              {formatValue(tick.value)}
            </text>
          </g>
        ))}
        {geometry.xTicks.map((tick, k) => (
          <text
            key={`x-${k}`}
            className="health-line__tick"
            x={tick.x}
            y={HEIGHT - 7}
            textAnchor="middle"
          >
            {shortDate(tick.date)}
          </text>
        ))}
        <polyline
          className={`health-line__path health-line__path--${colorSlug}`}
          points={geometry.polyline}
        />
      </svg>
    </div>
  )
}
