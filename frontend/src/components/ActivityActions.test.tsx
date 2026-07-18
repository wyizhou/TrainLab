import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ActivityActions } from './ActivityActions'
import type { Activity } from '../activities/activityData'

const activity: Activity = {
  id: 'a0',
  date: '2026-07-18',
  type: '跑步',
  name: '晨间跑',
  distanceKm: 5,
  durationSec: 1800,
  avgHr: 150,
  paceSecPerKm: 360,
  pace100Sec: null,
  powerW: null,
  source: 'FIT上传',
}

function props() {
  return {
    activity,
    onRename: vi.fn(async (_activity: Activity, name: string) => ({ ...activity, name })),
    onRestore: vi.fn(async () => ({ ...activity, name: '解析标题' })),
    onDelete: vi.fn(async () => {}),
    onDownload: vi.fn(async () => {}),
    onFeedback: vi.fn(),
  }
}

describe('ActivityActions', () => {
  it('supports keyboard menu navigation, trim rename, and focus return', async () => {
    const user = userEvent.setup()
    const callbacks = props()
    render(<ActivityActions {...callbacks} />)
    const trigger = screen.getByRole('button', { name: '打开运动操作菜单' })
    trigger.focus()
    await user.keyboard('{Enter}')
    expect(await screen.findByRole('menu')).toHaveAttribute('data-vc', 'activity-actions-menu')
    expect(screen.getByRole('menuitem', { name: '重命名' })).toHaveFocus()
    await user.click(screen.getByRole('menuitem', { name: '重命名' }))
    const input = screen.getByLabelText('运动名称')
    await user.clear(input)
    await user.type(input, '  新标题  ')
    await user.click(screen.getByRole('button', { name: '保存名称' }))
    await waitFor(() => expect(callbacks.onRename).toHaveBeenCalledWith(activity, '新标题'))
    await waitFor(() => expect(trigger).toHaveFocus())
  })

  it('rejects empty and overlong names and disables unavailable source download', async () => {
    const user = userEvent.setup()
    render(<ActivityActions {...props()} downloadAvailable={false} />)
    await user.click(screen.getByRole('button', { name: '打开运动操作菜单' }))
    expect(screen.getByRole('menuitem', { name: '原始 FIT 不可用' })).toBeDisabled()
    await user.click(screen.getByRole('menuitem', { name: '重命名' }))
    const input = screen.getByLabelText('运动名称')
    await user.clear(input)
    await user.click(screen.getByRole('button', { name: '保存名称' }))
    expect(screen.getByRole('alert')).toHaveTextContent('不能为空')
    await user.type(input, 'x'.repeat(256))
    await user.click(screen.getByRole('button', { name: '保存名称' }))
    expect(screen.getByRole('alert')).toHaveTextContent('255')
  })

  it('skips a disabled download during arrow navigation and traps dialog focus', async () => {
    const user = userEvent.setup()
    render(<ActivityActions {...props()} downloadAvailable={false} />)
    await user.click(screen.getByRole('button', { name: '打开运动操作菜单' }))
    await user.keyboard('{ArrowDown}')
    expect(screen.getByRole('menuitem', { name: '恢复解析标题' })).toHaveFocus()
    await user.keyboard('{ArrowDown}')
    expect(screen.getByRole('menuitem', { name: '删除运动' })).toHaveFocus()
    await user.keyboard('{Enter}')
    const cancel = screen.getByRole('button', { name: '取消' })
    const submit = screen.getByRole('button', { name: '确认删除' })
    submit.focus()
    await user.keyboard('{Tab}')
    expect(cancel).toHaveFocus()
    await user.keyboard('{Shift>}{Tab}{/Shift}')
    expect(submit).toHaveFocus()
  })

  it('disables duplicate submissions while a mutation is busy', async () => {
    let finish: (value: Activity) => void = () => {}
    const callbacks = props()
    callbacks.onRename = vi.fn(
      () =>
        new Promise<Activity>((resolve) => {
          finish = resolve
        }),
    )
    const user = userEvent.setup()
    render(<ActivityActions {...callbacks} />)
    await user.click(screen.getByRole('button', { name: '打开运动操作菜单' }))
    await user.click(screen.getByRole('menuitem', { name: '重命名' }))
    await user.clear(screen.getByLabelText('运动名称'))
    await user.type(screen.getByLabelText('运动名称'), '一次提交')
    const submit = screen.getByRole('button', { name: '保存名称' })
    await user.click(submit)
    expect(screen.getByRole('button', { name: '保存中…' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '保存中…' }))
    expect(callbacks.onRename).toHaveBeenCalledTimes(1)
    finish({ ...activity, name: '一次提交' })
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })
})
