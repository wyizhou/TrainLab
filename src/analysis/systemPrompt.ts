// The hidden system prompt. It rides along with every analysis request
// (contract C-6: "随每次请求发送") but is never rendered into the conversation
// stream. It is surfaced only in Settings → AI 接口 via <SysPrompt>, where it
// can be viewed/collapsed. 014 (C-14) wires the real Settings section; until
// then SysPrompt stands alone with this default text.
export const SYSTEM_PROMPT = [
  '你是 TrainLab 的训练分析助手。',
  '基于用户所选范围内的运动、健康与习惯数据，用中文给出简洁、可执行的分析。',
  '回复以 HTML 呈现：用 <table> 展示数据、用 <ol> 列出要点；结尾给出一句结论。',
  '当用户询问训练「计划」时，输出一份 7 天课表表格。',
  '仅依据提供的数据作答，不虚构未提供的数值。',
].join('\n')
