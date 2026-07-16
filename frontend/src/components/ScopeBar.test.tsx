import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ScopeBar, type ScopeActivity } from './ScopeBar'

const ACTIVITIES: ScopeActivity[] = [
  { id: 'a1', date: '07-11', name: '晨间轻松跑', type: '跑步', offsetDays: 0 },
  { id: 'a2', date: '07-10', name: '力量训练', type: '力量', offsetDays: 1 },
  { id: 'a3', date: '07-08', name: '骑行通勤', type: '骑行', offsetDays: 3 },
  { id: 'a4', date: '07-05', name: '长距离慢跑', type: '跑步', offsetDays: 6 },
  { id: 'a5', date: '06-20', name: '越野跑', type: '越野跑', offsetDays: 21 },
]

function setup() {
  render(<ScopeBar activities={ACTIVITIES} />)
  return {
    summary: () => screen.getByTestId('scope-summary'),
    effective: () => screen.getByTestId('scope-effective'),
    chip: (label: string) => screen.getByRole('button', { name: label }),
  }
}

describe('ScopeBar', () => {
  it('defaults to the 3-day chip with both toggles on and a live summary', () => {
    const { summary, effective, chip } = setup()

    // 3-day chip is the active default; the others are not pressed.
    expect(chip('3 天')).toHaveAttribute('aria-pressed', 'true')
    expect(chip('7 天')).toHaveAttribute('aria-pressed', 'false')

    // Both companion toggles default on (C-4).
    expect(screen.getByRole('checkbox', { name: '附带健康记录' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: '附带习惯记录' })).toBeChecked()

    // Summary reflects the default range + both companions; effective set is
    // the activities within 3 days (offsetDays 0 and 1 → 2 activities).
    expect(summary()).toHaveTextContent('最近 3 天运动数据 + 健康记录 + 习惯记录')
    expect(effective()).toHaveTextContent('2')
  })

  it('updates the summary and effective range when a day chip changes', async () => {
    const user = userEvent.setup()
    const { summary, effective, chip } = setup()

    await user.click(chip('7 天'))

    expect(chip('7 天')).toHaveAttribute('aria-pressed', 'true')
    expect(chip('3 天')).toHaveAttribute('aria-pressed', 'false')
    expect(summary()).toHaveTextContent('最近 7 天运动数据')
    // Within 7 days: offsetDays 0, 1, 3, 6 → 4 activities.
    expect(effective()).toHaveTextContent('4')
  })

  it('lets picked activities override the day range', async () => {
    const user = userEvent.setup()
    const { summary, effective, chip } = setup()

    await user.click(screen.getByRole('button', { name: /选择运动/ }))
    const list = screen.getByTestId('scope-picklist')
    await user.click(within(list).getByRole('checkbox', { name: /晨间轻松跑/ }))

    // Picking overrides the day chips: no chip stays active, count follows picks.
    expect(chip('3 天')).toHaveAttribute('aria-pressed', 'false')
    expect(summary()).toHaveTextContent('已勾选 1 次运动')
    expect(effective()).toHaveTextContent('1')
  })

  it('clears manual picks when a day chip is chosen again', async () => {
    const user = userEvent.setup()
    const { summary, chip } = setup()

    await user.click(screen.getByRole('button', { name: /选择运动/ }))
    await user.click(screen.getByRole('checkbox', { name: /越野跑/ }))
    expect(summary()).toHaveTextContent('已勾选 1 次运动')

    await user.click(chip('15 天'))
    expect(summary()).toHaveTextContent('最近 15 天运动数据')
    expect(chip('15 天')).toHaveAttribute('aria-pressed', 'true')
  })

  it('drops a companion from the summary when its toggle is turned off', async () => {
    const user = userEvent.setup()
    const { summary } = setup()

    await user.click(screen.getByRole('checkbox', { name: '附带健康记录' }))
    expect(summary()).toHaveTextContent('最近 3 天运动数据 + 习惯记录')
    expect(summary()).not.toHaveTextContent('健康记录 + 习惯记录')

    await user.click(screen.getByRole('checkbox', { name: '附带习惯记录' }))
    expect(summary()).toHaveTextContent('最近 3 天运动数据')
    expect(summary()).not.toHaveTextContent('习惯记录')
  })
})
