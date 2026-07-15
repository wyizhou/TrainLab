import { buildRequest, runAnalysis } from './aiReply'
import { SYSTEM_PROMPT } from './systemPrompt'

const FULL_SCOPE = { includeHealth: true, includeHabits: true }
const BARE_SCOPE = { includeHealth: false, includeHabits: false }

describe('buildRequest', () => {
  it('attaches the hidden system prompt to every request (C-6)', () => {
    const request = buildRequest('分析我的心率', FULL_SCOPE)
    expect(request.systemPrompt).toBe(SYSTEM_PROMPT)
    expect(request.question).toBe('分析我的心率')
    expect(request.scope).toEqual(FULL_SCOPE)
  })
})

describe('runAnalysis', () => {
  it('returns a data table, a conclusion and a chart for a trend question', () => {
    const reply = runAnalysis(buildRequest('分析我最近的心率趋势', FULL_SCOPE))
    expect(reply.html).toContain('<table>')
    expect(reply.html).toContain('结论：')
    expect(reply.chart?.points.length).toBeGreaterThanOrEqual(2)
  })

  it('emits a 7-day schedule table with an ordered list for a plan question', () => {
    const reply = runAnalysis(buildRequest('帮我制定训练计划', FULL_SCOPE))
    expect(reply.html).toContain('7 天训练计划')
    expect(reply.html).toContain('<ol>')
    // Seven weekday rows.
    expect(reply.html.match(/<tr><td>周/g)).toHaveLength(7)
  })

  it('appends health / habit interpretation only when the scope includes them', () => {
    const withBoth = runAnalysis(buildRequest('分析', FULL_SCOPE)).html
    expect(withBoth).toContain('恢复状态良好')
    expect(withBoth).toContain('习惯记录显示')

    const withNeither = runAnalysis(buildRequest('分析', BARE_SCOPE)).html
    expect(withNeither).not.toContain('恢复状态良好')
    expect(withNeither).not.toContain('习惯记录显示')
  })
})
