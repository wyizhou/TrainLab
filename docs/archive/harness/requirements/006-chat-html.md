---
id: "006"
status: verified
source_design_rev: 1
supersedes: null
superseded_by: null
contract_ref: "C-6"
branch: "feat/006-chat-html"
---

# 分析·AI 回复 HTML + 隐藏系统提示词

## 背景 / 目标
落成 contract C-6。AI 回复 HTML 渲染 + 隐藏系统提示词。依赖 005。反向消费 C-14 AI 接口分组（先默认，014 落成后接入）。

## 范围
- 做：HTML 渲染（表格/有序列表）、计划提问输出 7 天课表、附带健康/习惯追加解读、隐藏系统提示词（不入对话流，设置页可查看）、渲染安全白名单。
- 不做：真实 API 调用（前端模拟）。

## 涉及组件 / token
ChatMessage、SysPrompt。

## 验收标准（来源：contract.md C-6）
- [ ] HTML 渲染表格/列表；计划提问 7 天课表；附带解读段落；系统提示词随请求发送但不显示，设置页可查看/收起。
- [ ] 渲染转义/白名单，注入脚本不执行。
- [ ] unit：mock 分析请求 → 含数据表格与结论；系统提示词不在消息流 DOM；`<script>` 不执行。
- [ ] e2e：见 C-5 门禁#5 联合流。
- [ ] testing/lint/type：G-* 基线。

## 执行说明
- **e2e 门禁#5（C-5＋C-6 联合流）在本需求（006）验收时补跑。** C-5（ChartCard，需求 005）落成时该联合 e2e 因 C-6 未实现而延后（005 以 unit 判定通过）。Validator 验收 006 时须跑通门禁#5：「发送分析提问 → AI 气泡文本先到 → 卡片加载→折叠就绪 → 展开显示折线图」，**追溯覆盖 005 已延后的 C-5 e2e**。此 e2e 不通过则 006 不通过。

## 验收记录（Validator，2026-07-11）
- G-lint：`npm run lint` 0 error / 0 warning（含 prettier check）——通过。
- G-type：`npm run typecheck`（tsc --noEmit）0 error——通过。
- G-unit：`npm run test`（Vitest）13 文件 / 55 测试全绿；含 C-6 专项 aiReply / sanitizeHtml（`<script>` 不执行）/ ChatMessage / SysPrompt（系统提示词不入消息流 DOM）——通过。
- e2e 门禁#5（C-5＋C-6 联合流）：`playwright test tests/e2e/analysis-chart.spec.ts` 1 passed——分析提问 → AI 气泡文本（表格）先到 → 卡片 loading→collapsed → 展开显示折线 svg。**追溯覆盖 005 延后的 C-5 e2e**。
- 结论：全绿。feat/006-chat-html 合并入 main，需求迁 completed/ 置 verified，分支删除。
