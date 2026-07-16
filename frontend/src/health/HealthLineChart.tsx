import { useMemo } from 'react'
import './HealthLineChart.css'

// A single daily-value trend line for the health tabs (contract C-9: 体重/静息
// 心率/HRV 近 30 天曲线). The exported prototype deliberately keeps this
// card minimal: one centre guide and one raw-value polyline, without axis ticks.

export type LinePoint = { date: string; value: number }

export type HealthLineChartProps = {
  title: string
  unit: string
  points: LinePoint[]
  // A modifier slug picking the stroke colour token (see HealthLineChart.css).
  colorSlug?: string
}

const WIDTH = 300
const HEIGHT = 80
const PAD = 6

export function HealthLineChart({
  title,
  unit,
  points,
  colorSlug = 'accent',
}: HealthLineChartProps) {
  const geometry = useMemo(() => {
    if (points.length === 0) return null
    const nums = points.map((p) => p.value)
    const min = Math.min(...nums)
    const max = Math.max(...nums)
    const range = max - min || 1
    const n = points.length
    const xAt = (i: number) =>
      PAD + (n === 1 ? (WIDTH - PAD * 2) / 2 : ((WIDTH - PAD * 2) * i) / (n - 1))
    const yAt = (v: number) => PAD + (HEIGHT - PAD * 2) * (1 - (v - min) / range)

    const polyline = points.map((p, i) => `${xAt(i)},${yAt(p.value)}`).join(' ')
    return { polyline }
  }, [points])

  if (!geometry) {
    return (
      <div className="health-line health-line--empty" data-testid="health-line">
        <span className="health-line__title">{title}</span>
        <p className="health-line__empty">无数据</p>
      </div>
    )
  }

  return (
    <div className="health-line" data-vc="health-trend-card" data-testid="health-line">
      <div className="health-line__head">
        <span className="health-line__title">{title}</span>
        <span className="health-line__unit">{unit}</span>
      </div>
      <svg
        className="health-line__svg"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        width={WIDTH}
        height={130}
        preserveAspectRatio="none"
        role="img"
        aria-label={`${title}趋势曲线（${unit}）`}
        data-testid="health-line-svg"
      >
        <line className="health-line__grid" x1="0" y1="40" x2="300" y2="40" />
        <polyline
          className={`health-line__path health-line__path--${colorSlug}`}
          points={geometry.polyline}
        />
      </svg>
    </div>
  )
}
