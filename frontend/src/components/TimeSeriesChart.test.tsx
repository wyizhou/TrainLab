import { render, screen } from '@testing-library/react'
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
    expect(screen.getByTestId('ts-source')).toHaveTextContent('Y:bpm · X:时间 · heart_rate')
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
    expect(screen.getByTestId('ts-chart')).toHaveTextContent('无数据')
  })
})
