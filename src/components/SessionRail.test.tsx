import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'
import { SessionRail } from './SessionRail'
import type { Session } from '../hooks/useSessions'

const SESSIONS: Session[] = [
  { id: 's1', name: '会话 1', messageCount: 3 },
  { id: 's2', name: '会话 2', messageCount: 0 },
]

// SessionRail renders one form or the other by breakpoint (C-3, design_rev 2):
// the desktop aside for desktop/wide, the dropdown for mobile/tablet. Drive the
// choice through window.innerWidth, matching AppLayout's dual-mode test.
function setup(overrides: Partial<Parameters<typeof SessionRail>[0]> = {}, width = 1280) {
  window.innerWidth = width
  const handlers = {
    onCreate: vi.fn(),
    onSelect: vi.fn(),
    onRename: vi.fn(),
    onDelete: vi.fn(),
  }
  render(<SessionRail sessions={SESSIONS} activeId="s1" {...handlers} {...overrides} />)
  return handlers
}

function desktopRail() {
  return within(screen.getByTestId('session-rail-desktop'))
}

describe('SessionRail', () => {
  const original = window.innerWidth
  afterEach(() => {
    window.innerWidth = original
  })

  it('renders each session with its name and message count, plus a new button', () => {
    setup()
    const items = desktopRail().getAllByTestId('session-item')
    expect(items).toHaveLength(2)
    expect(within(items[0]).getByText('会话 1')).toBeInTheDocument()
    expect(within(items[0]).getByText('3')).toBeInTheDocument()
    expect(desktopRail().getByRole('button', { name: '新建会话' })).toBeInTheDocument()
  })

  it('marks the active session with the accent-bar class', () => {
    setup()
    const items = desktopRail().getAllByTestId('session-item')
    expect(items[0]).toHaveClass('session-rail__item--active')
    expect(items[1]).not.toHaveClass('session-rail__item--active')
  })

  it('selects a session on click and creates on the new button', async () => {
    const user = userEvent.setup()
    const { onSelect, onCreate } = setup()
    await user.click(desktopRail().getByText('会话 2'))
    expect(onSelect).toHaveBeenCalledWith('s2')
    await user.click(desktopRail().getByRole('button', { name: '新建会话' }))
    expect(onCreate).toHaveBeenCalledOnce()
  })

  it('confirms an inline rename on Enter', async () => {
    const user = userEvent.setup()
    const { onRename } = setup()
    await user.click(desktopRail().getByRole('button', { name: '重命名 会话 1' }))
    const input = desktopRail().getByLabelText('会话名称')
    await user.clear(input)
    await user.type(input, '训练分析{Enter}')
    expect(onRename).toHaveBeenCalledWith('s1', '训练分析')
  })

  it('cancels an inline rename on Escape without calling onRename', async () => {
    const user = userEvent.setup()
    const { onRename } = setup()
    await user.click(desktopRail().getByRole('button', { name: '重命名 会话 1' }))
    const input = desktopRail().getByLabelText('会话名称')
    await user.type(input, '改了一半{Escape}')
    expect(onRename).not.toHaveBeenCalled()
    expect(desktopRail().getByText('会话 1')).toBeInTheDocument()
  })

  it('deletes a session via its delete button', async () => {
    const user = userEvent.setup()
    const { onDelete } = setup()
    await user.click(desktopRail().getByRole('button', { name: '删除 会话 2' }))
    expect(onDelete).toHaveBeenCalledWith('s2')
  })

  it('degrades to a dropdown selector on tablet, with no desktop aside', () => {
    setup({}, 768)
    expect(screen.queryByTestId('session-rail-desktop')).not.toBeInTheDocument()
    const mobile = screen.getByTestId('session-rail-mobile')
    const menu = within(mobile).getByLabelText('选择会话')
    expect(menu).toHaveValue('s1')
    expect(within(mobile).getAllByRole('option')).toHaveLength(2)
    expect(within(mobile).getByRole('button', { name: '新建会话' })).toBeInTheDocument()
  })

  it('degrades to a dropdown selector on mobile, with no desktop aside', () => {
    setup({}, 390)
    expect(screen.queryByTestId('session-rail-desktop')).not.toBeInTheDocument()
    expect(screen.getByTestId('session-rail-mobile')).toBeInTheDocument()
  })
})
