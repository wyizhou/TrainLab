import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SettingsPage } from './SettingsPage'
import { resetSettings } from './settingsStore'
import { HrZoneChart } from '../components/HrZoneChart'
import type { FitHrZoneTime } from '../activities/fitParser'

const ZONE_TIMES: FitHrZoneTime[] = [
  { zone: 1, seconds: 600 },
  { zone: 2, seconds: 900 },
  { zone: 3, seconds: 1200 },
  { zone: 4, seconds: 400 },
  { zone: 5, seconds: 120 },
]

describe('SettingsPage (C-14)', () => {
  afterEach(() => resetSettings())

  it('renders the four groups', () => {
    render(<SettingsPage />)
    for (const testid of ['settings-account', 'settings-units', 'settings-zones', 'settings-ai']) {
      expect(screen.getByTestId(testid)).toBeInTheDocument()
    }
    // AI 接口 defaults to DeepSeek and surfaces the hidden system prompt.
    expect(screen.getByLabelText('base_url')).toHaveValue('https://api.deepseek.com')
    expect(within(screen.getByTestId('settings-ai')).getByTestId('sys-prompt')).toBeInTheDocument()
  })

  // 返工 design_rev 3 (014c): pixel-contract data-vc anchors mirrored to root +
  // group + two grids (AC-014c hard req).
  it('mirrors the four pixel-contract data-vc anchors (AC-014c hard req)', () => {
    const { container } = render(<SettingsPage />)
    expect(screen.getByTestId('page-settings')).toHaveAttribute('data-vc', 'settings-page')
    // Four groups all carry the settings-group anchor.
    expect(container.querySelectorAll('[data-vc="settings-group"]')).toHaveLength(4)
    expect(container.querySelector('[data-vc="settings-account-grid"]')).not.toBeNull()
    expect(container.querySelector('[data-vc="settings-zone-grid"]')).not.toBeNull()
  })

  // 返工 design_rev 2: the 数据保留策略 group is deleted — no group, no copy, no
  // expiry auto-clean control (AC-014b-1 covers this end-to-end).
  it('has no 数据保留策略 group or expiry-cleanup control', () => {
    render(<SettingsPage />)
    expect(screen.queryByTestId('settings-retention')).not.toBeInTheDocument()
    expect(screen.queryByText('数据保留策略')).not.toBeInTheDocument()
    expect(screen.queryByText('保留期限')).not.toBeInTheDocument()
    expect(screen.queryByText('到期自动清理')).not.toBeInTheDocument()
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })

  it('rejects a mismatched new password and accepts a matching one', async () => {
    const user = userEvent.setup()
    render(<SettingsPage />)

    await user.type(screen.getByLabelText('新密码'), 'abc12345')
    await user.type(screen.getByLabelText('确认新密码'), 'abc99999')
    await user.click(screen.getByRole('button', { name: '保存密码' }))
    expect(screen.getByTestId('settings-password-error')).toHaveTextContent('不一致')

    // Correcting the confirmation clears the error and confirms the save.
    await user.clear(screen.getByLabelText('确认新密码'))
    await user.type(screen.getByLabelText('确认新密码'), 'abc12345')
    await user.click(screen.getByRole('button', { name: '保存密码' }))
    expect(screen.queryByTestId('settings-password-error')).not.toBeInTheDocument()
    expect(screen.getByText('密码已更新')).toBeInTheDocument()
  })

  it('writes 区间设定 that the detail chart (C-8) reads back', async () => {
    const user = userEvent.setup()
    const { unmount } = render(<SettingsPage />)

    const maxHr = screen.getByLabelText('MaxHR')
    await user.clear(maxHr)
    await user.type(maxHr, '205')
    await user.click(screen.getByRole('button', { name: '保存区间' }))
    expect(screen.getByText('区间已保存')).toBeInTheDocument()
    unmount()

    // The detail page's HR-zone chart reads the same store — Z5 now tops out at 205.
    render(<HrZoneChart zones={ZONE_TIMES} />)
    const rows = screen.getAllByTestId('hr-zone-row')
    expect(within(rows[4]).getByText('171–205')).toBeInTheDocument()
  })

  it('validates zone bounds are ascending positive numbers', async () => {
    const user = userEvent.setup()
    render(<SettingsPage />)

    const b1 = screen.getByLabelText('Z1 上界')
    await user.clear(b1)
    await user.type(b1, '999') // above Z2 → not ascending
    await user.click(screen.getByRole('button', { name: '保存区间' }))
    expect(screen.getByTestId('settings-zone-error')).toBeInTheDocument()
  })
})
