import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RecordTable } from './RecordTable'
import type { FitRecordPoint } from '../activities/fitParser'

function makeRecords(n: number): FitRecordPoint[] {
  return Array.from({ length: n }, (_, i) => ({
    tSec: i,
    distanceM: i * 3,
    speedMps: 3,
    paceSecPerKm: 333,
    hr: 140 + (i % 5),
    powerW: 250,
    cadenceSpm: 176,
    altitudeM: 498,
    temperatureC: 32,
    gctMs: 260,
    vertOscMm: 81,
  }))
}

describe('RecordTable', () => {
  it('pages the per-second rows 20 at a time by default (row count = seconds)', () => {
    render(<RecordTable records={makeRecords(45)} paceSport />)
    expect(screen.getAllByTestId('record-row')).toHaveLength(20)
    expect(screen.getByTestId('pager-info')).toHaveTextContent('45')
    expect(screen.getByTestId('pager-page')).toHaveTextContent('1 / 3')
  })

  it('renders 配速 for pace sports and 速度 otherwise', () => {
    const { rerender } = render(<RecordTable records={makeRecords(3)} paceSport />)
    const head = () => within(screen.getByTestId('record-table')).getAllByRole('row')[0]
    expect(head()).toHaveTextContent('配速')
    // 3 m/s -> 5'33"/km pace
    expect(screen.getAllByTestId('record-row')[0]).toHaveTextContent(`5'33"`)

    rerender(<RecordTable records={makeRecords(3)} paceSport={false} />)
    expect(head()).toHaveTextContent('速度')
    // 3 m/s -> 10.8 km/h
    expect(screen.getAllByTestId('record-row')[0]).toHaveTextContent('10.8')
  })

  it('advances pages with the shared Pager', async () => {
    const user = userEvent.setup()
    render(<RecordTable records={makeRecords(45)} paceSport />)
    await user.click(screen.getByRole('button', { name: /下一页/ }))
    expect(screen.getByTestId('pager-page')).toHaveTextContent('2 / 3')
    expect(screen.getAllByTestId('record-row')).toHaveLength(20)
  })

  it('renders "--" for missing fields', () => {
    const recs = makeRecords(1)
    recs[0].powerW = null
    render(<RecordTable records={recs} paceSport />)
    expect(screen.getByTestId('record-row')).toHaveTextContent('--')
  })
})
