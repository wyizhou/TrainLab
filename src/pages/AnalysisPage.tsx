import { useCallback, useRef, useState, type FormEvent } from 'react'
import { ChatMessage, type ChatMessageData } from '../components/ChatMessage'
import { ScopeBar, type EffectiveScope } from '../components/ScopeBar'
import { SessionRail } from '../components/SessionRail'
import { buildRequest, runAnalysis } from '../analysis/aiReply'
import { useSessions } from '../hooks/useSessions'
import './AnalysisPage.css'

export function AnalysisPage() {
  const { sessions, activeId, createSession, selectSession, renameSession, deleteSession } =
    useSessions()
  const active = sessions.find((session) => session.id === activeId)

  const [messages, setMessages] = useState<ChatMessageData[]>([])
  const [draft, setDraft] = useState('')
  const [scope, setScope] = useState<EffectiveScope | null>(null)
  const seq = useRef(0)

  // ScopeBar owns the health / habit toggles (C-4); we mirror the latest scope
  // so each request carries the right interpretation flags.
  const handleScopeChange = useCallback((next: EffectiveScope) => setScope(next), [])

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const question = draft.trim()
    if (!question) return

    const request = buildRequest(question, {
      includeHealth: scope?.includeHealth ?? true,
      includeHabits: scope?.includeHabits ?? true,
    })
    // Front-end mock; the hidden system prompt travels in `request` but never
    // enters the message list (contract C-6).
    const reply = runAnalysis(request)

    const userId = `m${(seq.current += 1)}`
    const aiId = `m${(seq.current += 1)}`
    setMessages((prev) => [
      ...prev,
      { id: userId, role: 'user', text: question },
      { id: aiId, role: 'ai', html: reply.html, chart: reply.chart },
    ])
    setDraft('')
  }

  return (
    <div className="analysis" data-testid="page-analysis" data-vc="analysis-main">
      <SessionRail
        sessions={sessions}
        activeId={activeId}
        onCreate={createSession}
        onSelect={selectSession}
        onRename={renameSession}
        onDelete={deleteSession}
      />
      <section className="analysis__main">
        <h1>分析</h1>
        <ScopeBar onScopeChange={handleScopeChange} />
        <p>当前会话：{active?.name}</p>

        {/* Conversation thread — visual hierarchy of C-5: user > AI bubble > card. */}
        <div className="analysis__thread" data-testid="analysis-thread">
          {messages.length === 0 ? (
            <p className="analysis__hint">发送一个分析提问，例如「分析我最近的心率趋势」。</p>
          ) : (
            messages.map((message) => <ChatMessage key={message.id} message={message} />)
          )}
        </div>

        <form className="analysis__composer" onSubmit={submit} data-vc="analysis-input">
          <input
            className="analysis__input"
            data-testid="chat-input"
            aria-label="分析提问"
            placeholder="向 AI 提问以生成分析…"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
          <button type="submit" className="analysis__send" data-vc="btn-primary">
            发送
          </button>
        </form>
      </section>
    </div>
  )
}
