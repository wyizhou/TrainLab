import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ActivityCardList } from './ActivityCardList'
import type { Activity } from '../activities/activityData'

const ROWS: Activity[] = [
  {
    id: 'a0',
    date: '2026-07-11',
    type: '跑步',
    name: '晨间轻松跑',
    distanceKm: 5.08,
    durationSec: 1885,
    avgHr: 152,
    paceSecPerKm: 371,
    pace100Sec: null,
    powerW: null,
    source: '佳明CN',
  },
  {
    id: 'a3',
    date: '2026-07-08',
    type: '力量',
    name: '下肢力量',
    distanceKm: null,
    durationSec: 3300,
    avgHr: 112,
    paceSecPerKm: null,
    pace100Sec: null,
    powerW: null,
    source: '佳明CN',
  },
]

describe('ActivityCardList', () => {
  it('renders one card per activity with its metrics, "--" where absent', () => {
    render(
      <ActivityCardList
        activities={ROWS}
        selectedIds={new Set()}
        onToggle={() => {}}
        onDownload={() => {}}
      />,
    )
    const cards = screen.getAllByTestId('activity-card')
    expect(cards).toHaveLength(2)

    const run = within(cards[0])
    expect(run.getByText('晨间轻松跑')).toBeInTheDocument()
    expect(run.getByText('5.08 km')).toBeInTheDocument()
    expect(run.getByText('31:25')).toBeInTheDocument()
    expect(run.getByText(`6'11"/km`)).toBeInTheDocument()

    // Strength card: distance and pace/power collapse to "--".
    const strength = within(cards[1])
    expect(strength.getAllByText('--')).toHaveLength(2)
  })

  it('reflects selection and fires the toggle / download callbacks', async () => {
    const user = userEvent.setup()
    const onToggle = vi.fn()
    const onDownload = vi.fn()
    render(
      <ActivityCardList
        activities={ROWS}
        selectedIds={new Set(['a0'])}
        onToggle={onToggle}
        onDownload={onDownload}
      />,
    )

    expect(screen.getByRole('checkbox', { name: '选择 晨间轻松跑' })).toBeChecked()

    await user.click(screen.getByRole('checkbox', { name: '选择 下肢力量' }))
    expect(onToggle).toHaveBeenCalledWith('a3')

    await user.click(screen.getByRole('button', { name: '下载 晨间轻松跑 的 FIT' }))
    expect(onDownload).toHaveBeenCalledWith('a0')
  })

  it('opens a card on tap but not when the checkbox is clicked', async () => {
    const user = userEvent.setup()
    const onOpen = vi.fn()
    render(
      <ActivityCardList
        activities={ROWS}
        selectedIds={new Set()}
        onToggle={() => {}}
        onDownload={() => {}}
        onOpen={onOpen}
      />,
    )

    await user.click(screen.getByRole('checkbox', { name: '选择 晨间轻松跑' }))
    expect(onOpen).not.toHaveBeenCalled()

    await user.click(screen.getByText('晨间轻松跑'))
    expect(onOpen).toHaveBeenCalledWith('a0')
  })
})
