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
    const focusedItem = screen.getByRole('menuitem', { name: '重命名' })
    expect(focusedItem).toHaveFocus()
    await user.click(screen.getByRole('menuitem', { name: '重命名' }))
    const input = screen.getByLabelText('运动名称')
    await user.clear(input)
    await user.type(input, '  新标题  ')
    expect(screen.getByText('7/255')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '保存名称' }))
    await waitFor(() => expect(callbacks.onRename).toHaveBeenCalledWith(activity, '新标题'))
    await waitFor(() => expect(trigger).toHaveFocus())
  })

  it('rejects empty and overlong names and disables unavailable source download', async () => {
    const user = userEvent.setup()
    render(<ActivityActions {...props()} downloadAvailable={false} />)
    await user.click(screen.getByRole('button', { name: '打开运动操作菜单' }))
    const unavailable = screen.getByRole('menuitem', { name: '原始 FIT 不可用' })
    expect(unavailable).toBeDisabled()
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
    expect(screen.getByRole('button', { name: '提交中…' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '提交中…' }))
    expect(callbacks.onRename).toHaveBeenCalledTimes(1)
    finish({ ...activity, name: '一次提交' })
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('renders the contracted rename, restore and delete dialog content and geometry', async () => {
    const user = userEvent.setup()
    render(<ActivityActions {...props()} />)
    const openMode = async (name: '重命名' | '恢复解析标题' | '删除运动') => {
      await user.click(screen.getByRole('button', { name: '打开运动操作菜单' }))
      await user.click(screen.getByRole('menuitem', { name }))
    }

    await openMode('重命名')
    expect(screen.getByRole('heading', { name: '重命名运动' })).toHaveClass(
      'activity-dialog__title',
    )
    expect(screen.getByText('当前名称：晨间跑')).toHaveClass('activity-dialog__subtitle')
    expect(screen.getByText('保存时自动忽略首尾空格 · 1–255 个字符')).toBeInTheDocument()
    expect(screen.getByText('3/255')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '取消' }).parentElement).toHaveClass(
      'activity-dialog__actions',
    )
    await user.click(screen.getByRole('button', { name: '取消' }))

    await openMode('恢复解析标题')
    expect(screen.getByText('将移除当前活动的自定义名称。')).toBeInTheDocument()
    const restoreNote = screen.getByText(/服务端实际返回的解析标题/)
    expect(restoreNote).toHaveTextContent('不会提前返回恢复后的名称')
    expect(restoreNote).toHaveClass('activity-dialog__note')
    await user.click(screen.getByRole('button', { name: '取消' }))

    await openMode('删除运动')
    expect(screen.getByText('确认删除当前活动及其关联数据。')).toBeInTheDocument()
    expect(screen.getByText('此操作不可撤销').tagName).toBe('STRONG')
    const deleteNote = screen.getByText(/名为“晨间跑”/)
    expect(deleteNote).toHaveClass('activity-dialog__note--danger')
    expect(deleteNote).toHaveTextContent('当前活动、对应导入记录和私有原文件将一起删除')
    expect(deleteNote).toHaveTextContent('导入仍在进行或删除未完成')
  })
})
