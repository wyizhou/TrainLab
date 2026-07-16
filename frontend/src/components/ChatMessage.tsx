import { ChartCard } from './ChartCard'
import { sanitizeHtml } from '../analysis/sanitizeHtml'
import type { ChartSpec } from '../analysis/aiReply'
import './ChatMessage.css'

// A single turn in the analysis conversation. User turns are plain text; AI
// turns carry sanitized HTML (contract C-6) plus an optional embedded chart.
export type ChatMessageData =
  | { id: string; role: 'user'; text: string }
  | { id: string; role: 'ai'; html: string; chart?: ChartSpec }
  | { id: string; role: 'typing' }

export function ChatMessage({ message }: { message: ChatMessageData }) {
  if (message.role === 'user') {
    return (
      <div className="message-row message-row--user" data-vc="message-row">
        <div className="msg msg--user" data-vc="chat-bubble-user" data-testid="msg-user">
          {message.text}
        </div>
      </div>
    )
  }

  if (message.role === 'typing') {
    return (
      <div className="message-row message-row--ai" data-vc="message-row">
        <div
          className="typing-indicator"
          data-vc="typing-indicator"
          data-testid="typing-indicator"
          role="status"
          aria-label="AI 正在输入"
        >
          <span />
          <span />
          <span />
        </div>
      </div>
    )
  }

  return (
    <div className="message-row message-row--ai" data-vc="message-row">
      <div
        className={`msg msg--ai${message.id.startsWith('welcome-') ? ' msg--welcome' : ''}`}
        data-vc="chat-bubble-ai"
        data-testid="msg-ai"
      >
        {/* The reply text lands first; it is rendered through the tag whitelist so
            injected markup (e.g. <script>) is stripped and can never execute. */}
        <div
          className="msg__html"
          data-testid="msg-ai-html"
          dangerouslySetInnerHTML={{ __html: sanitizeHtml(message.html) }}
        />
        {message.chart && (
          <ChartCard
            title={message.chart.title}
            points={message.chart.points}
            rangeLabel={message.chart.rangeLabel}
          />
        )}
      </div>
    </div>
  )
}
