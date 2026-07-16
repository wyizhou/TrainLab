import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { ChatMessage, type ChatMessageData } from '../components/ChatMessage'
import { ScopeBar, type EffectiveScope } from '../components/ScopeBar'
import { SessionRail } from '../components/SessionRail'
import { buildRequest, runAnalysis } from '../analysis/aiReply'
import { useSessions } from '../hooks/useSessions'
import { useBreakpoint } from '../hooks/useBreakpoint'
import './AnalysisPage.css'

const WELCOME_HTML =
  '<p>你好!我基于已存储的<strong>原始数据</strong>(运动 / 健康 / 习惯 + 你的区间设定)做分析。TSS、CTL/ATL/TSB 等衍生指标会在回复中计算并注明依据,系统不预存任何计算结果。</p><p>当前默认读取最近 <strong>3 天</strong>数据,已附带健康与习惯记录。</p>'
const MARATHON_WELCOME_HTML =
  '<p>这是「马拉松备赛计划」会话。告诉我目标赛事日期与目标成绩,我会基于你的原始训练数据在回复中生成周期化计划。</p>'

function welcomeMessage(sessionId: string): ChatMessageData {
  return {
    id: `welcome-${sessionId}`,
    role: 'ai',
    html: sessionId === 's2' ? MARATHON_WELCOME_HTML : WELCOME_HTML,
  }
}

export function AnalysisPage() {
  const breakpoint = useBreakpoint()
  const isRail = breakpoint === 'desktop' || breakpoint === 'wide'
  const {
    sessions,
    activeId,
    createSession,
    selectSession,
    renameSession,
    deleteSession,
    setMessageCount,
  } = useSessions()
  const active = sessions.find((session) => session.id === activeId)

  const [messagesBySession, setMessagesBySession] = useState<Record<string, ChatMessageData[]>>({
    s1: [welcomeMessage('s1')],
    s2: [welcomeMessage('s2')],
  })
  const [draft, setDraft] = useState('')
  const [scope, setScope] = useState<EffectiveScope | null>(null)
  const seq = useRef(0)
  const replyTimers = useRef(new Set<ReturnType<typeof setTimeout>>())
  const messages = messagesBySession[activeId] ?? []

  useEffect(
    () => () => {
      for (const timer of replyTimers.current) clearTimeout(timer)
      replyTimers.current.clear()
    },
    [],
  )

  useEffect(() => {
    setMessagesBySession((previous) => {
      let changed = false
      const next = { ...previous }
      for (const session of sessions) {
        if (!(session.id in next)) {
          next[session.id] = [welcomeMessage(session.id)]
          changed = true
        }
      }
      return changed ? next : previous
    })
  }, [sessions])

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
    const typingId = `m${(seq.current += 1)}`
    setMessageCount(activeId, messages.length + 1)
    setMessagesBySession((prev) => {
      const current = prev[activeId] ?? []
      const next = [
        ...current,
        { id: userId, role: 'user', text: question } as ChatMessageData,
        { id: typingId, role: 'typing' } as ChatMessageData,
      ]
      return { ...prev, [activeId]: next }
    })
    setDraft('')

    const timer = setTimeout(() => {
      setMessagesBySession((prev) => {
        const current = prev[activeId] ?? []
        const next = current.map((message) =>
          message.id === typingId
            ? ({ id: aiId, role: 'ai', html: reply.html, chart: reply.chart } as ChatMessageData)
            : message,
        )
        return { ...prev, [activeId]: next }
      })
      setMessageCount(activeId, messages.length + 2)
      replyTimers.current.delete(timer)
    }, 1400)
    replyTimers.current.add(timer)
  }

  const handleDraftKey = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      event.currentTarget.form?.requestSubmit()
    }
  }

  const sessionNavigation = (
    <SessionRail
      sessions={sessions}
      activeId={activeId}
      onCreate={createSession}
      onSelect={selectSession}
      onRename={renameSession}
      onDelete={deleteSession}
    />
  )

  return (
    <div className="analysis" data-testid="page-analysis" data-vc="analysis-main">
      {isRail && sessionNavigation}
      <section className="analysis__main" data-vc="analysis-conversation">
        {!isRail && sessionNavigation}
        <header className="analysis__header" data-vc="analysis-header">
          <h1>{active?.name}</h1>
          <p>AI 读取已存储的原始数据进行分析 · TSS / CTL / ATL / TSB 等衍生指标仅在回复中产出</p>
        </header>

        {/* Conversation thread — visual hierarchy of C-5: user > AI bubble > card. */}
        <div className="analysis__thread" data-vc="analysis-messages" data-testid="analysis-thread">
          {messages.map((message) => (
            <ChatMessage key={message.id} message={message} />
          ))}
        </div>

        <form className="analysis__composer" onSubmit={submit} data-vc="analysis-input">
          <ScopeBar onScopeChange={handleScopeChange} hideSummary />
          <div className="analysis__compose-row" data-vc="analysis-compose-row">
            <textarea
              className="analysis__input"
              data-testid="chat-input"
              aria-label="分析提问"
              rows={2}
              placeholder="向 AI 提问,例如:分析我最近的有氧状态 / 帮我生成下周训练计划…"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={handleDraftKey}
            />
            <button type="submit" className="analysis__send" data-vc="btn-primary">
              发送
            </button>
          </div>
          <div className="analysis__scope-summary">当前范围:{scope?.summary}</div>
        </form>
      </section>
    </div>
  )
}
