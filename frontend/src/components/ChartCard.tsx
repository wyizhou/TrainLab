import { useEffect, useMemo, useState } from 'react'
import { useBreakpoint } from '../hooks/useBreakpoint'
import './ChartCard.css'

// One activity's headline metric (default: average heart rate in bpm).
export type ChartPoint = {
  date: string
  value: number
}

// The card walks: loading -> (empty | collapsed) and collapsed <-> expanded.
// Empty is terminal (not expandable). See contract C-5.
export type ChartState = 'loading' | 'empty' | 'collapsed' | 'expanded'

type ChartCardProps = {
  title: string
  points: ChartPoint[]
  unit?: string
  // Prefix of the collapsed one-line summary, e.g. "最近 7 天".
  rangeLabel?: string
  // Delay before the loading state resolves; the reply text lands first (~1.1s).
  autoLoadMs?: number
  // Force a starting state (skips the loading timer) — used by tests/demos.
  initialState?: ChartState
}

// Fewer than this many activities in range -> the empty state (C-5).
const MIN_ACTIVITIES = 2

// SVG plot geometry (contract C-5: 340×112 line chart).
const WIDTH = 340
const HEIGHT = 112
const PAD_LEFT = 34
const PAD_RIGHT = 10
const PAD_TOP = 10
const PAD_BOTTOM = 20
const PLOT_W = WIDTH - PAD_LEFT - PAD_RIGHT
const PLOT_H = HEIGHT - PAD_TOP - PAD_BOTTOM

type Geometry = {
  min: number
  max: number
  mid: number
  coords: { x: number; y: number; point: ChartPoint }[]
  polyline: string
  // First / middle / last indices for the X-axis ticks.
  xTicks: number[]
}

function computeGeometry(points: ChartPoint[]): Geometry {
  const values = points.map((p) => p.value)
  const min = Math.min(...values)
  const max = Math.max(...values)
  // Guard a flat series so it draws a centred line instead of dividing by zero.
  const range = max - min || 1
  const n = points.length

  const coords = points.map((point, i) => {
    const x = PAD_LEFT + (n === 1 ? PLOT_W / 2 : (PLOT_W * i) / (n - 1))
    const y = PAD_TOP + PLOT_H * (1 - (point.value - min) / range)
    return { x, y, point }
  })

  const polyline = coords.map(({ x, y }) => `${x},${y}`).join(' ')

  // First, middle, last — deduped so short series don't repeat a tick.
  const last = n - 1
  const middle = Math.floor(last / 2)
  const xTicks = [...new Set([0, middle, last])]

  return { min, max, mid: Math.round((min + max) / 2), coords, polyline, xTicks }
}

export function ChartCard({
  title,
  points,
  unit = 'bpm',
  rangeLabel = '最近 7 天',
  autoLoadMs = 1100,
  initialState,
}: ChartCardProps) {
  const [state, setState] = useState<ChartState>(initialState ?? 'loading')

  // C-5 (design_rev 2): the expanded per-activity data rows render only on
  // desktop/wide. Gating is breakpoint-conditional (not CSS display:none) so
  // the rows container is truly absent from the DOM below 980px (AC-005b-1).
  const breakpoint = useBreakpoint()
  const showRows = breakpoint === 'desktop' || breakpoint === 'wide'

  const enough = points.length >= MIN_ACTIVITIES

  // While loading, resolve to the collapsed chart (or the empty state when
  // there is too little data) after the reply text has had time to land.
  useEffect(() => {
    if (state !== 'loading') return
    const timer = setTimeout(() => setState(enough ? 'collapsed' : 'empty'), autoLoadMs)
    return () => clearTimeout(timer)
  }, [state, enough, autoLoadMs])

  const geometry = useMemo(() => (enough ? computeGeometry(points) : null), [enough, points])

  const summary = useMemo(() => {
    if (!geometry) return ''
    const avg = Math.round(
      geometry.coords.reduce((sum, c) => sum + c.point.value, 0) / points.length,
    )
    return `${rangeLabel} · ${points.length} 次运动 · 平均 ${avg} ${unit} · 区间 ${geometry.min}–${geometry.max}`
  }, [geometry, points.length, rangeLabel, unit])

  if (state === 'loading') {
    return (
      <div
        className="chart-card chart-card--loading"
        data-vc="chart-card"
        data-testid="chart-card"
        data-state="loading"
      >
        <div className="chart-card__loading">
          <span className="chart-card__spinner" aria-hidden="true" />
          <span className="chart-card__loading-text">正在读取原始数据并生成图表…</span>
        </div>
      </div>
    )
  }

  if (state === 'empty') {
    return (
      <div
        className="chart-card chart-card--empty"
        data-vc="chart-card"
        data-testid="chart-card"
        data-state="empty"
      >
        <span className="chart-card__empty-icon" aria-hidden="true">
          ▦
        </span>
        <div className="chart-card__empty-body">
          <p className="chart-card__empty-title">数据不足，无法生成图表</p>
          <p className="chart-card__empty-reason">
            所选范围内运动少于 {MIN_ACTIVITIES} 次，无法绘制趋势曲线。
          </p>
          <p className="chart-card__empty-hint">建议扩大时间范围或勾选更多运动后重试。</p>
        </div>
      </div>
    )
  }

  const expanded = state === 'expanded'

  return (
    <div
      className="chart-card"
      data-vc="chart-card"
      data-testid="chart-card"
      data-state={expanded ? 'expanded' : 'collapsed'}
    >
      <div className="chart-card__header" data-vc="chart-card-header">
        <span className="chart-card__icon" aria-hidden="true">
          📊
        </span>
        <span className="chart-card__title">{title}</span>
        {!expanded && (
          <p className="chart-card__summary num" data-testid="chart-summary">
            {summary}
          </p>
        )}
        <button
          type="button"
          className="chart-card__toggle"
          aria-expanded={expanded}
          onClick={() => setState(expanded ? 'collapsed' : 'expanded')}
        >
          {expanded ? '收起 ▲' : '展开 ▼'}
        </button>
      </div>

      {expanded && geometry && (
        <div
          className="chart-card__expanded"
          data-vc="chart-card-expanded"
          data-testid="chart-expanded"
        >
          <p className="chart-card__axis-note">Y:{unit} · X:日期</p>

          <svg
            className="chart-card__svg"
            viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
            width={WIDTH}
            height={HEIGHT}
            role="img"
            aria-label={`${title}趋势折线图`}
            data-testid="chart-svg"
          >
            {/* Y axis: 3 ticks (max / mid / min). */}
            {[
              { value: geometry.max, y: PAD_TOP },
              { value: geometry.mid, y: PAD_TOP + PLOT_H / 2 },
              { value: geometry.min, y: PAD_TOP + PLOT_H },
            ].map((tick) => (
              <g key={`y-${tick.y}`}>
                <line
                  className="chart-card__grid"
                  x1={PAD_LEFT}
                  y1={tick.y}
                  x2={WIDTH - PAD_RIGHT}
                  y2={tick.y}
                />
                <text className="chart-card__tick" x={PAD_LEFT - 4} y={tick.y + 3} textAnchor="end">
                  {tick.value}
                </text>
              </g>
            ))}

            {/* X axis: first / middle / last date ticks. */}
            {geometry.xTicks.map((i) => (
              <text
                key={`x-${i}`}
                className="chart-card__tick"
                x={geometry.coords[i].x}
                y={HEIGHT - 6}
                textAnchor="middle"
              >
                {geometry.coords[i].point.date}
              </text>
            ))}

            <polyline className="chart-card__line" points={geometry.polyline} />
            {geometry.coords.map(({ x, y, point }) => (
              <circle key={point.date} className="chart-card__dot" cx={x} cy={y} r={2.5} />
            ))}
          </svg>

          {/* Per-activity data rows; desktop/wide only — absent from the DOM
              below 980px (breakpoint-gated above). */}
          {showRows && (
            <ul className="chart-card__rows" data-testid="chart-rows">
              {geometry.coords.map(({ point }) => (
                <li key={point.date} className="chart-card__row">
                  <span className="chart-card__row-date num">{point.date}</span>
                  <span className="chart-card__row-value num">
                    {point.value} {unit}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
