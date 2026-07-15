import type { ChartPoint } from '../components/ChartCard'
import { SYSTEM_PROMPT } from './systemPrompt'

// The chart embedded in an AI reply (rendered by ChartCard inside the bubble).
export type ChartSpec = {
  title: string
  rangeLabel: string
  points: ChartPoint[]
}

// Whether the reply should fold in health / habit interpretation (from ScopeBar).
export type ReplyScope = {
  includeHealth: boolean
  includeHabits: boolean
}

// One analysis turn's request payload. The hidden system prompt rides along
// here (contract C-6) but is not part of the reply the user sees.
export type AnalysisRequest = {
  systemPrompt: string
  question: string
  scope: ReplyScope
}

export type AnalysisReply = {
  // Reply markup — always fed through sanitizeHtml before it hits the DOM.
  html: string
  chart?: ChartSpec
}

// Demo heart-rate trend for the analysis reply, one point per activity, until
// real activity data (C-7 / C-8) feeds the analysis.
const TREND_POINTS: ChartPoint[] = [
  { date: '07-05', value: 142 },
  { date: '07-07', value: 151 },
  { date: '07-09', value: 138 },
  { date: '07-11', value: 146 },
]

// Seven-day training plan emitted when the question mentions「计划」.
const PLAN_DAYS: readonly [string, string, string][] = [
  ['周一', '轻松跑', '40 分钟 · Z2'],
  ['周二', '力量训练', '45 分钟 · 全身'],
  ['周三', '间歇跑', '6×800m · Z4'],
  ['周四', '恢复骑行', '50 分钟 · Z1'],
  ['周五', '休息', '拉伸放松'],
  ['周六', '长距离慢跑', '90 分钟 · Z2'],
  ['周日', '交叉训练', '游泳 30 分钟'],
]

// Interpretation paragraphs appended when the scope carries health / habits.
function interpretation(scope: ReplyScope): string {
  const parts: string[] = []
  if (scope.includeHealth) {
    parts.push('<p>结合睡眠与静息心率，本周整体恢复状态良好，可维持当前训练负荷。</p>')
  }
  if (scope.includeHabits) {
    parts.push('<p>习惯记录显示补水与拉伸达标率较高，有助于降低受伤风险。</p>')
  }
  return parts.join('')
}

function trendReply(scope: ReplyScope): AnalysisReply {
  const rows = TREND_POINTS.map((p) => `<tr><td>${p.date}</td><td>${p.value} bpm</td></tr>`).join(
    '',
  )
  const avg = Math.round(TREND_POINTS.reduce((sum, p) => sum + p.value, 0) / TREND_POINTS.length)
  const html = [
    '<h3>心率趋势分析</h3>',
    '<table><thead><tr><th>日期</th><th>平均心率</th></tr></thead>',
    `<tbody>${rows}</tbody></table>`,
    `<p>结论：所选范围内平均心率约 ${avg} bpm，趋势平稳，强度分布合理。</p>`,
    interpretation(scope),
  ].join('')
  return {
    html,
    chart: { title: '平均心率趋势', rangeLabel: '最近 7 天', points: TREND_POINTS },
  }
}

function planReply(scope: ReplyScope): AnalysisReply {
  const rows = PLAN_DAYS.map(
    ([day, session, load]) => `<tr><td>${day}</td><td>${session}</td><td>${load}</td></tr>`,
  ).join('')
  const html = [
    '<h3>7 天训练计划</h3>',
    '<table><thead><tr><th>星期</th><th>训练</th><th>时长/强度</th></tr></thead>',
    `<tbody>${rows}</tbody></table>`,
    '<ol><li>周三间歇为本周关键课，务必充分热身。</li>',
    '<li>周六长距离控制在 Z2，重在有氧积累。</li>',
    '<li>其余日以恢复为主，睡眠优先。</li></ol>',
    interpretation(scope),
  ].join('')
  return { html }
}

// Builds the request payload for one analysis turn. The hidden system prompt is
// attached here so it is "sent with every request" (contract C-6).
export function buildRequest(question: string, scope: ReplyScope): AnalysisRequest {
  return { systemPrompt: SYSTEM_PROMPT, question, scope }
}

// Front-end mock of the analysis endpoint (G-mock: no real network). A question
// mentioning「计划」returns a 7-day schedule; otherwise a trend analysis with a
// chart. Health / habit interpretation is appended per the request scope.
export function runAnalysis(request: AnalysisRequest): AnalysisReply {
  return request.question.includes('计划') ? planReply(request.scope) : trendReply(request.scope)
}
