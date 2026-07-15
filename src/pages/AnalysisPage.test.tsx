import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AnalysisPage } from './AnalysisPage'
import { SYSTEM_PROMPT } from '../analysis/systemPrompt'

function desktop() {
  return within(screen.getByTestId('session-rail-desktop'))
}

async function ask(user: ReturnType<typeof userEvent.setup>, question: string) {
  await user.type(screen.getByTestId('chat-input'), question)
  await user.click(screen.getByRole('button', { name: '发送' }))
  expect(screen.getByTestId('typing-indicator')).toBeInTheDocument()
  await waitFor(() => expect(screen.queryByTestId('typing-indicator')).not.toBeInTheDocument(), {
    timeout: 2500,
  })
}

describe('AnalysisPage session management', () => {
  it('runs the new -> rename -> delete-to-empty auto-create chain', async () => {
    const user = userEvent.setup()
    render(<AnalysisPage />)

    // Starts with the two design-baseline sessions and the first active.
    expect(desktop().getAllByTestId('session-item')).toHaveLength(2)
    expect(screen.getByRole('heading', { name: '状态评估' })).toBeInTheDocument()

    await user.click(desktop().getByText('马拉松备赛计划'))
    expect(screen.getByText(/告诉我目标赛事日期与目标成绩/)).toBeInTheDocument()
    await user.click(desktop().getByText('状态评估'))
    expect(screen.getByText(/当前默认读取最近/)).toBeInTheDocument()

    // New session becomes active.
    await user.click(desktop().getByRole('button', { name: '新建会话' }))
    expect(desktop().getAllByTestId('session-item')).toHaveLength(3)
    expect(screen.getByRole('heading', { name: '会话 3' })).toBeInTheDocument()
    expect(screen.getByText(/当前默认读取最近/)).toBeInTheDocument()

    // Inline rename of the active session.
    await user.click(desktop().getByRole('button', { name: '重命名 会话 3' }))
    const input = desktop().getByLabelText('会话名称')
    await user.clear(input)
    await user.type(input, '训练分析{Enter}')
    expect(desktop().getByText('训练分析')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '训练分析' })).toBeInTheDocument()

    // Deleting the active session falls back to the first remaining one.
    await user.click(desktop().getByRole('button', { name: '删除 训练分析' }))
    expect(desktop().getAllByTestId('session-item')).toHaveLength(2)
    expect(screen.getByRole('heading', { name: '状态评估' })).toBeInTheDocument()

    // Deleting every baseline session auto-creates a fresh one (never empty).
    await user.click(desktop().getByRole('button', { name: '删除 马拉松备赛计划' }))
    await user.click(desktop().getByRole('button', { name: '删除 状态评估' }))
    const items = desktop().getAllByTestId('session-item')
    expect(items).toHaveLength(1)
    expect(within(items[0]).queryByText('状态评估')).not.toBeInTheDocument()
  })
})

describe('AnalysisPage analysis conversation (C-6)', () => {
  it('shows the user turn, then typing, then replaces typing with the AI reply', async () => {
    const user = userEvent.setup()
    render(<AnalysisPage />)

    await user.type(screen.getByTestId('chat-input'), '分析我的恢复状态')
    await user.click(screen.getByRole('button', { name: '发送' }))

    expect(screen.getByTestId('msg-user')).toHaveTextContent('分析我的恢复状态')
    expect(screen.getByTestId('typing-indicator')).toBeInTheDocument()
    expect(screen.getAllByTestId('msg-ai')).toHaveLength(1)

    await waitFor(() => expect(screen.queryByTestId('typing-indicator')).not.toBeInTheDocument(), {
      timeout: 2500,
    })
    expect(screen.getAllByTestId('msg-ai')).toHaveLength(2)
  })

  it('keeps each session conversation independent', async () => {
    const user = userEvent.setup()
    render(<AnalysisPage />)

    await ask(user, '只属于状态评估')
    await user.click(desktop().getByText('马拉松备赛计划'))
    expect(screen.queryByText('只属于状态评估')).not.toBeInTheDocument()

    await ask(user, '只属于马拉松计划')
    await user.click(desktop().getByText('状态评估'))
    expect(screen.getByText('只属于状态评估')).toBeInTheDocument()
    expect(screen.queryByText('只属于马拉松计划')).not.toBeInTheDocument()
  })

  it('renders the question and the v3.2 HTML reply with a data table and findings', async () => {
    const user = userEvent.setup()
    render(<AnalysisPage />)

    await ask(user, '分析我最近的心率趋势')

    expect(screen.getByTestId('msg-user')).toHaveTextContent('分析我最近的心率趋势')
    const bubbles = screen.getAllByTestId('msg-ai')
    const bubble = bubbles[bubbles.length - 1]
    expect(within(bubble).getByRole('table')).toBeInTheDocument()
    expect(within(bubble).getByText(/总距离/)).toBeInTheDocument()
    expect(within(bubble).getByText(/强度分布:/)).toBeInTheDocument()
  })

  it('never leaks the hidden system prompt into the message stream', async () => {
    const user = userEvent.setup()
    render(<AnalysisPage />)

    await ask(user, '分析我最近的心率趋势')

    const thread = screen.getByTestId('analysis-thread')
    const marker = SYSTEM_PROMPT.split('\n')[0]
    expect(thread.textContent).not.toContain(marker)
  })
})
