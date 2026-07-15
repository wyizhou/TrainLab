import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AnalysisPage } from './AnalysisPage'
import { SYSTEM_PROMPT } from '../analysis/systemPrompt'

function desktop() {
  return within(screen.getByTestId('session-rail-desktop'))
}

async function ask(user: ReturnType<typeof userEvent.setup>, question: string) {
  await user.type(screen.getByTestId('chat-input'), question)
  await user.click(screen.getByRole('button', { name: '发送' }))
}

describe('AnalysisPage session management', () => {
  it('runs the new -> rename -> delete-to-empty auto-create chain', async () => {
    const user = userEvent.setup()
    render(<AnalysisPage />)

    // Starts with one session, shown as the active conversation.
    expect(desktop().getAllByTestId('session-item')).toHaveLength(1)
    expect(screen.getByText('当前会话：会话 1')).toBeInTheDocument()

    // New session becomes active.
    await user.click(desktop().getByRole('button', { name: '新建会话' }))
    expect(desktop().getAllByTestId('session-item')).toHaveLength(2)
    expect(screen.getByText('当前会话：会话 2')).toBeInTheDocument()

    // Inline rename of the active session.
    await user.click(desktop().getByRole('button', { name: '重命名 会话 2' }))
    const input = desktop().getByLabelText('会话名称')
    await user.clear(input)
    await user.type(input, '训练分析{Enter}')
    expect(desktop().getByText('训练分析')).toBeInTheDocument()
    expect(screen.getByText('当前会话：训练分析')).toBeInTheDocument()

    // Deleting the active session falls back to the first remaining one.
    await user.click(desktop().getByRole('button', { name: '删除 训练分析' }))
    expect(desktop().getAllByTestId('session-item')).toHaveLength(1)
    expect(screen.getByText('当前会话：会话 1')).toBeInTheDocument()

    // Deleting the last session auto-creates a fresh one (never empty).
    await user.click(desktop().getByRole('button', { name: '删除 会话 1' }))
    const items = desktop().getAllByTestId('session-item')
    expect(items).toHaveLength(1)
    expect(within(items[0]).queryByText('会话 1')).not.toBeInTheDocument()
  })
})

describe('AnalysisPage analysis conversation (C-6)', () => {
  it('renders the question and an HTML reply with a data table and conclusion', async () => {
    const user = userEvent.setup()
    render(<AnalysisPage />)

    await ask(user, '分析我最近的心率趋势')

    expect(screen.getByTestId('msg-user')).toHaveTextContent('分析我最近的心率趋势')
    const bubble = screen.getByTestId('msg-ai')
    expect(within(bubble).getByRole('table')).toBeInTheDocument()
    expect(within(bubble).getByText(/结论：/)).toBeInTheDocument()
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
