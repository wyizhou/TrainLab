import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, vi } from 'vitest'
import { ChartCard, type ChartPoint } from './ChartCard'

const POINTS: ChartPoint[] = [
  { date: '07-05', value: 142 },
  { date: '07-07', value: 151 },
  { date: '07-09', value: 138 },
  { date: '07-11', value: 146 },
]

const originalInnerWidth = window.innerWidth

afterEach(() => {
  vi.useRealTimers()
  window.innerWidth = originalInnerWidth
})

describe('ChartCard loading resolution', () => {
  it('shows loading first, then the empty state when fewer than 2 activities', () => {
    vi.useFakeTimers()
    render(<ChartCard title="平均心率趋势" points={[POINTS[0]]} autoLoadMs={1100} />)

    const card = screen.getByTestId('chart-card')
    expect(card).toHaveAttribute('data-state', 'loading')
    expect(screen.getByText('正在读取原始数据并生成图表…')).toBeInTheDocument()

    act(() => {
      vi.advanceTimersByTime(1100)
    })

    expect(screen.getByTestId('chart-card')).toHaveAttribute('data-state', 'empty')
    expect(screen.getByText('数据不足，无法生成图表')).toBeInTheDocument()
    // Empty state is terminal — no expand affordance.
    expect(screen.queryByRole('button', { name: /展开/ })).not.toBeInTheDocument()
  })

  it('resolves loading into the collapsed chart when 2+ activities are present', () => {
    vi.useFakeTimers()
    render(<ChartCard title="平均心率趋势" points={POINTS} autoLoadMs={1100} />)

    expect(screen.getByTestId('chart-card')).toHaveAttribute('data-state', 'loading')

    act(() => {
      vi.advanceTimersByTime(1100)
    })

    expect(screen.getByTestId('chart-card')).toHaveAttribute('data-state', 'collapsed')
    expect(screen.getByTestId('chart-summary')).toHaveTextContent(
      '最近 7 天 · 4 次运动 · 平均 144 bpm · 区间 138–151',
    )
  })
})

describe('ChartCard collapse / expand', () => {
  it('expands into an axis-labelled line chart and per-activity rows', async () => {
    // Rows render on desktop/wide only (AC-005b-1); pin a desktop width so the
    // breakpoint gate resolves deterministically.
    window.innerWidth = 1280
    const user = userEvent.setup()
    render(<ChartCard title="平均心率趋势" points={POINTS} initialState="collapsed" />)

    // Collapsed: summary shown, no chart yet.
    expect(screen.queryByTestId('chart-svg')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '展开 ▼' }))

    const svg = screen.getByTestId('chart-svg')
    // Y axis: 3 ticks (max / mid / min).
    expect(within(svg).getByText('151')).toBeInTheDocument()
    expect(within(svg).getByText('145')).toBeInTheDocument()
    expect(within(svg).getByText('138')).toBeInTheDocument()
    // X axis: first / middle / last dates only.
    expect(within(svg).getByText('07-05')).toBeInTheDocument()
    expect(within(svg).getByText('07-07')).toBeInTheDocument()
    expect(within(svg).getByText('07-11')).toBeInTheDocument()
    expect(within(svg).queryByText('07-09')).not.toBeInTheDocument()

    // A polyline over all four points.
    expect(svg.querySelector('polyline')).toHaveAttribute('points')

    // Per-activity data rows: one per point.
    const rows = screen.getByTestId('chart-rows')
    expect(within(rows).getAllByRole('listitem')).toHaveLength(4)
    expect(within(rows).getByText('138 bpm')).toBeInTheDocument()
  })

  it('drops the per-activity rows on tablet, keeping only the chart', () => {
    // Tablet (<980px): the rows container is absent from the DOM (AC-005b-1),
    // while the axis note and chart svg remain.
    window.innerWidth = 768
    render(<ChartCard title="平均心率趋势" points={POINTS} initialState="expanded" />)

    expect(screen.getByTestId('chart-svg')).toBeInTheDocument()
    expect(screen.queryByTestId('chart-rows')).not.toBeInTheDocument()
  })

  it('collapses again when toggled', async () => {
    const user = userEvent.setup()
    render(<ChartCard title="平均心率趋势" points={POINTS} initialState="expanded" />)

    expect(screen.getByTestId('chart-svg')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '收起 ▲' }))

    expect(screen.getByTestId('chart-card')).toHaveAttribute('data-state', 'collapsed')
    expect(screen.queryByTestId('chart-svg')).not.toBeInTheDocument()
  })
})
