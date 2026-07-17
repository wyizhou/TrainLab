import { useEffect, useMemo, useRef, useState } from 'react'
import { tickCountForWidth } from './chartTicks'
import './TimeSeriesChart.css'

export type TimeSeriesChartProps = {
  title: string
  unit: string
  sourceField: string
  values: Array<number | null>
  timesSec: number[]
  distancesKm?: Array<number | null>
  formatValue?: (value: number) => string
  tone?: string
  linkedProgress?: number | null
}

const WIDTH = 720
const HEIGHT = 220
const PAD_LEFT = 52
const PAD_RIGHT = 14
const PAD_TOP = 16
const PAD_BOTTOM = 42
const PLOT_WIDTH = WIDTH - PAD_LEFT - PAD_RIGHT
const PLOT_HEIGHT = HEIGHT - PAD_TOP - PAD_BOTTOM

function formatClock(totalSeconds: number): string {
  const rounded = Math.max(0, Math.round(totalSeconds))
  const hours = Math.floor(rounded / 3600)
  const minutes = Math.floor((rounded % 3600) / 60)
  const seconds = rounded % 60
  return hours
    ? `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
    : `${minutes}:${String(seconds).padStart(2, '0')}`
}

export function TimeSeriesChart({
  title,
  unit,
  sourceField,
  values,
  timesSec,
  distancesKm,
  formatValue = (value) => `${Math.round(value)}`,
  tone = 'accent',
  linkedProgress = null,
}: TimeSeriesChartProps) {
  const rootRef = useRef<HTMLDivElement>(null)
  const [containerWidth, setContainerWidth] = useState(360)
  const [hoverIndex, setHoverIndex] = useState<number | null>(null)

  useEffect(() => {
    const root = rootRef.current
    if (!root) return
    const update = () => setContainerWidth(root.getBoundingClientRect().width || 360)
    update()
    if (!globalThis.ResizeObserver) return
    const observer = new ResizeObserver(update)
    observer.observe(root)
    return () => observer.disconnect()
  }, [])

  const geometry = useMemo(() => {
    const present = values
      .map((value, index) => ({ value, index }))
      .filter(
        (point): point is { value: number; index: number } =>
          point.value !== null && Number.isFinite(point.value),
      )
    if (present.length === 0) return null

    const numeric = present.map((point) => point.value)
    const min = Math.min(...numeric)
    const max = Math.max(...numeric)
    const range = max - min || 1
    const count = values.length
    const xAt = (index: number) =>
      PAD_LEFT + (count === 1 ? PLOT_WIDTH / 2 : (PLOT_WIDTH * index) / (count - 1))
    const yAt = (value: number) => PAD_TOP + PLOT_HEIGHT * (1 - (value - min) / range)
    const coords = present.map((point) => ({
      x: xAt(point.index),
      y: yAt(point.value),
      index: point.index,
    }))
    const ticks = Math.min(tickCountForWidth(containerWidth), Math.max(1, count))
    const xTicks = Array.from({ length: ticks }, (_, tickIndex) => {
      const index = Math.round((tickIndex * (count - 1)) / (ticks - 1 || 1))
      return {
        x: xAt(index),
        index,
        seconds: timesSec[index] ?? 0,
        distanceKm: distancesKm?.[index] ?? null,
      }
    })
    return {
      min,
      max,
      mid: (min + max) / 2,
      coords,
      polyline: coords.map((point) => `${point.x},${point.y}`).join(' '),
      xTicks,
      xAt,
    }
  }, [containerWidth, distancesKm, timesSec, values])

  if (!geometry) {
    return (
      <div
        ref={rootRef}
        className="ts-chart ts-chart--empty"
        data-testid="ts-chart"
        data-vc="activity-specialized-chart"
      >
        <div className="ts-chart__head">
          <span className="ts-chart__title">{title}</span>
          <span className="ts-chart__source">{sourceField}</span>
        </div>
        <p className="ts-chart__empty">当前文件未提供可验证的{title}时序数据</p>
      </div>
    )
  }

  const hovered = hoverIndex === null ? null : values[hoverIndex]
  const hoverX = hoverIndex === null ? 0 : geometry.xAt(hoverIndex)
  const linkedX =
    linkedProgress === null
      ? null
      : PAD_LEFT + PLOT_WIDTH * Math.max(0, Math.min(1, linkedProgress))
  const yTicks = [
    { value: geometry.max, y: PAD_TOP },
    { value: geometry.mid, y: PAD_TOP + PLOT_HEIGHT / 2 },
    { value: geometry.min, y: PAD_TOP + PLOT_HEIGHT },
  ]

  return (
    <div
      ref={rootRef}
      className={`ts-chart ts-chart--${tone}`}
      data-testid="ts-chart"
      data-vc="activity-specialized-chart"
      onPointerMove={(event) => {
        const rect = event.currentTarget.getBoundingClientRect()
        const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width))
        setHoverIndex(Math.round(ratio * Math.max(0, values.length - 1)))
      }}
      onPointerLeave={() => setHoverIndex(null)}
    >
      <div className="ts-chart__head">
        <span className="ts-chart__title">{title}趋势</span>
        <span className="ts-chart__source" data-testid="ts-source">
          X:经过时间{distancesKm ? ' · 累计距离' : ''} · Y:{unit} ·{' '}
          <span className="num">{sourceField}</span>
        </span>
      </div>
      <svg
        className="ts-chart__svg"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
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
              x={PAD_LEFT - 7}
              y={tick.y + 3}
              textAnchor="end"
            >
              {formatValue(tick.value)}
            </text>
          </g>
        ))}
        <g data-vc="activity-chart-x-axis" data-testid="activity-chart-x-axis">
          {geometry.xTicks.map((tick, index) => (
            <text
              key={`x-${index}`}
              className="ts-chart__tick ts-chart__tick--x"
              data-testid="ts-xtick"
              x={tick.x}
              y={HEIGHT - 12}
              textAnchor={
                index === 0 ? 'start' : index === geometry.xTicks.length - 1 ? 'end' : 'middle'
              }
            >
              {formatClock(tick.seconds)}
              {tick.distanceKm !== null ? ` · ${tick.distanceKm.toFixed(2)} km` : ''}
            </text>
          ))}
        </g>
        <polyline className="ts-chart__line" points={geometry.polyline} />
        {linkedX !== null && (
          <line
            className="ts-chart__selection"
            data-vc="activity-chart-linked-selection"
            x1={linkedX}
            x2={linkedX}
            y1={PAD_TOP}
            y2={PAD_TOP + PLOT_HEIGHT}
          />
        )}
        {hoverIndex !== null && hovered !== null && (
          <line
            className="ts-chart__crosshair"
            data-testid="chart-crosshair"
            x1={hoverX}
            x2={hoverX}
            y1={PAD_TOP}
            y2={PAD_TOP + PLOT_HEIGHT}
          />
        )}
      </svg>
      {hoverIndex !== null && hovered !== null && (
        <div className="ts-chart__tooltip" role="status" data-testid="chart-tooltip">
          {formatClock(timesSec[hoverIndex] ?? 0)}
          {distancesKm?.[hoverIndex] !== null && distancesKm?.[hoverIndex] !== undefined
            ? ` · ${distancesKm[hoverIndex]!.toFixed(2)} km`
            : ''}
          {' · '}
          {formatValue(hovered)} {unit}
        </div>
      )}
    </div>
  )
}
