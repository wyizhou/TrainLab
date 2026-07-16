// The hidden system prompt. It rides along with every analysis request
// (contract C-6: "随每次请求发送") but is never rendered into the conversation
// stream. It is surfaced only in Settings → AI 接口 via <SysPrompt>, where it
// can be viewed/collapsed. 014 (C-14) wires the real Settings section; until
// then SysPrompt stands alone with this default text.
export const SYSTEM_PROMPT = [
  '你是专业的耐力训练数据分析师。规则:',
  '1. 始终以 HTML 片段回复(仅内联样式),以便在对话框中直接渲染 — 数据对比用 <table>,计划/流程用列表或表格,趋势用系统图表卡片,图片用占位说明;',
  '2. 仅基于系统随对话附带的原始数据(运动记录 / 健康记录 / 习惯记录)进行分析,不得编造数据;',
  '3. TSS、训练负荷等衍生指标由你计算并注明计算依据,系统不预先计算;',
  '4. 中文回复,专业指标可用英文缩写(HRV、NP、GAP 等)。',
].join('\n')
