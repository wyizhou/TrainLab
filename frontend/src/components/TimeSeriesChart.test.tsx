import { render, screen } from '@testing-library/react'
import { tickCountForWidth } from './chartTicks'
import { TimeSeriesChart } from './TimeSeriesChart'

describe('TimeSeriesChart', () => {
  it('renders the SVG with the source-field annotation', () => {
    render(
      <TimeSeriesChart
        title="心率"
        unit="bpm"
        sourceField="heart_rate"
        values={[120, 140, 150, 160]}
        timesSec={[0, 60, 120, 180]}
      />,
    )
    expect(screen.getByTestId('ts-svg')).toBeInTheDocument()
    expect(screen.getByTestId('ts-source')).toHaveTextContent('X:经过时间 · Y:bpm · heart_rate')
  })

  it('draws three Y ticks (max / mid / min) via the formatter', () => {
    render(
      <TimeSeriesChart
        title="配速"
        unit="/km"
        sourceField="enhanced_speed"
        values={[300, 360, 420]}
        timesSec={[0, 30, 60]}
        formatValue={(v) => `${Math.floor(v / 60)}'${String(Math.round(v % 60)).padStart(2, '0')}`}
      />,
    )
    // max=420 -> 7'00, min=300 -> 5'00
    expect(screen.getByText(`7'00`)).toBeInTheDocument()
    expect(screen.getByText(`5'00`)).toBeInTheDocument()
  })

  it('skips null gaps but still renders when some data is present', () => {
    render(
      <TimeSeriesChart
        title="功率"
        unit="W"
        sourceField="power"
        values={[null, 200, null, 260]}
        timesSec={[0, 1, 2, 3]}
      />,
    )
    expect(screen.getByTestId('ts-svg')).toBeInTheDocument()
  })

  it('shows an empty state when there is no numeric data', () => {
    render(
      <TimeSeriesChart
        title="海拔"
        unit="m"
        sourceField="enhanced_altitude"
        values={[null, null]}
        timesSec={[0, 1]}
      />,
    )
    expect(screen.getByTestId('ts-chart')).toHaveTextContent('当前文件未提供可验证的海拔时序数据')
  })

  it('uses the v3.4 responsive X-axis tick formula', () => {
    expect(tickCountForWidth(390)).toBe(4)
    expect(tickCountForWidth(768)).toBe(9)
    expect(tickCountForWidth(1280)).toBe(12)
  })

  it('renders distance labels and a linked selection marker', () => {
    render(
      <TimeSeriesChart
        title="心率"
        unit="bpm"
        sourceField="record.heart_rate"
        values={[120, 140, 160]}
        timesSec={[0, 60, 120]}
        distancesKm={[0, 0.5, 1]}
        linkedProgress={0.5}
      />,
    )

    expect(screen.getAllByTestId('ts-xtick')[0]).toHaveTextContent('km')
    expect(document.querySelector('.ts-chart__selection')).not.toBeNull()
  })
})
