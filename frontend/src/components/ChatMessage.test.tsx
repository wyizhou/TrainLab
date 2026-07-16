import { render, screen, within } from '@testing-library/react'
import { ChatMessage, type ChatMessageData } from './ChatMessage'

describe('ChatMessage', () => {
  it('renders a user turn as plain text', () => {
    render(<ChatMessage message={{ id: 'u1', role: 'user', text: '分析我的心率' }} />)
    expect(screen.getByTestId('msg-user')).toHaveTextContent('分析我的心率')
  })

  it('renders AI HTML (table) inside the bubble', () => {
    const message: ChatMessageData = {
      id: 'a1',
      role: 'ai',
      html: '<table><tbody><tr><td>07-05</td><td>142 bpm</td></tr></tbody></table>',
    }
    render(<ChatMessage message={message} />)
    const bubble = screen.getByTestId('msg-ai')
    expect(within(bubble).getByRole('table')).toBeInTheDocument()
    expect(within(bubble).getByText('142 bpm')).toBeInTheDocument()
  })

  it('strips injected <script> so it never lands in the DOM (C-6)', () => {
    const flag = '__chat_msg_exec_flag'
    ;(window as unknown as Record<string, unknown>)[flag] = false
    const message: ChatMessageData = {
      id: 'a2',
      role: 'ai',
      html: `<p>安全</p><script>window['${flag}'] = true</script>`,
    }
    const { container } = render(<ChatMessage message={message} />)
    expect(container.querySelector('script')).toBeNull()
    expect((window as unknown as Record<string, unknown>)[flag]).toBe(false)
    expect(screen.getByText('安全')).toBeInTheDocument()
  })

  it('renders an embedded ChartCard when the reply carries a chart', () => {
    const message: ChatMessageData = {
      id: 'a3',
      role: 'ai',
      html: '<p>趋势</p>',
      chart: {
        title: '平均心率趋势',
        rangeLabel: '最近 7 天',
        points: [
          { date: '07-05', value: 142 },
          { date: '07-11', value: 146 },
        ],
      },
    }
    render(<ChatMessage message={message} />)
    expect(screen.getByTestId('chart-card')).toBeInTheDocument()
  })
})
