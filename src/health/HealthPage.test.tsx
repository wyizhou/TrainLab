import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { HealthPage } from './HealthPage'

const rows = () => screen.getAllByTestId('metric-row')
const pagerTotal = () =>
  Number(screen.getByTestId('pager-info').textContent!.match(/共\s*(\d+)\s*条/)![1])

describe('HealthPage', () => {
  it('renders the five sub-tabs with 睡眠 active by default', () => {
    render(<HealthPage />)
    expect(screen.getByTestId('page-health')).toBeInTheDocument()
    for (const label of ['睡眠', '体重', '静息心率', 'HRV', '习惯']) {
      expect(screen.getByRole('tab', { name: label })).toBeInTheDocument()
    }
    expect(screen.getByRole('tab', { name: '睡眠' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByTestId('panel-sleep')).toBeInTheDocument()
    expect(screen.getByTestId('sleep-stack')).toBeInTheDocument()
  })

  it('renders the 近 14 天 sleep window (14 bars) at the default width', () => {
    // jsdom defaults to a desktop-width window, so the breakpoint gate resolves to
    // 14 bars / 近 14 天 (mobile 7 is asserted by AC-009b-1 e2e).
    render(<HealthPage />)
    expect(screen.getByTestId('sleep-title')).toHaveTextContent('近 14 天')
    expect(screen.getAllByTestId('sleep-bar')).toHaveLength(14)
  })

  it('switches tabs to the matching panel and chart', async () => {
    const user = userEvent.setup()
    render(<HealthPage />)

    await user.click(screen.getByRole('tab', { name: '体重' }))
    expect(screen.getByTestId('panel-weight')).toBeInTheDocument()
    expect(screen.queryByTestId('panel-sleep')).not.toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'HRV' }))
    expect(screen.getByTestId('panel-hrv')).toBeInTheDocument()
    expect(screen.getByTestId('health-line-svg')).toBeInTheDocument()
  })

  it('meets the C-9 row lower bounds per tab', async () => {
    const user = userEvent.setup()
    render(<HealthPage />)

    // Sleep ≥14.
    expect(pagerTotal()).toBeGreaterThanOrEqual(14)

    // Weight / resting HR / HRV each ≥30.
    for (const label of ['体重', '静息心率', 'HRV']) {
      await user.click(screen.getByRole('tab', { name: label }))
      expect(pagerTotal()).toBeGreaterThanOrEqual(30)
    }
  })

  it('offers the 20/50/100 paging tiers and pages 20 by default', async () => {
    const user = userEvent.setup()
    render(<HealthPage />)

    const sizeSelect = screen.getByLabelText('每页条数')
    for (const size of ['20', '50', '100']) {
      expect(within(sizeSelect).getByRole('option', { name: `${size} 条` })).toBeInTheDocument()
    }
    expect(rows()).toHaveLength(20)

    await user.selectOptions(sizeSelect, '50')
    expect(rows()).toHaveLength(50)
  })

  it('logs habit factors by date and tracks the recorded-day count', async () => {
    const user = userEvent.setup()
    render(<HealthPage />)
    await user.click(screen.getByRole('tab', { name: '习惯' }))

    // Seed: 3 recorded days; the default date (今天) shows its stored factors.
    expect(screen.getByTestId('habit-count')).toHaveTextContent('已记录 3 天')
    expect(screen.getByRole('button', { name: '咖啡' })).toHaveAttribute('aria-pressed', 'true')

    // Switch to a fresh, unrecorded date — nothing is pre-selected.
    fireEvent.change(screen.getByLabelText('选择日期'), { target: { value: '2026-05-01' } })
    expect(screen.getByRole('button', { name: '咖啡' })).toHaveAttribute('aria-pressed', 'false')

    // Tick one factor in each of the four groups; the new date joins the count once.
    for (const label of ['咖啡', '午睡', '看书', '运动强度']) {
      await user.click(screen.getByRole('button', { name: label }))
      expect(screen.getByRole('button', { name: label })).toHaveAttribute('aria-pressed', 'true')
    }
    expect(screen.getByTestId('habit-count')).toHaveTextContent('已记录 4 天')
  })
})
