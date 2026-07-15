---
id: "005b"
status: verified
source_design_rev: 2
supersedes: "005"
superseded_by: null
contract_ref: "C-5"
branch: "feat/005b-chart-card"
---

# 分析·图表卡片响应式（返工）

## 背景 / 目标
落成 contract C-5（返工，design_rev 2）。展开态数据明细行仅 desktop/wide 渲染（tablet 起隐藏），展开态 svg 宽度自适应容器不溢出；视觉层级判据更新并**删除「AI 气泡最小宽 46%」**（移交 006b 气泡返工）。rev 1 四态功能保留。原 005 留 `completed/` 当 rev 1 历史，不改写。

## 范围
- 做：展开态明细行断点门控（仅 desktop/wide）；展开态 svg 自适应容器；视觉层级更新（删 46% 最小宽）。
- 不做：四态状态机/空态判据逻辑改动（rev 1 原样保留）；气泡 min/max-width（移交 006b）。

## 涉及组件 / token
ChartCard（展开态明细行、svg 容器）、视觉层级 token。

## 验收标准（来源：contract.md C-5，Validator 只认该条目）
- [ ] rev 1 功能判据保留：四态（加载/空态/折叠/展开）可判定；unit（<2 次→空态，≥2 次→折叠/展开）。
- [ ] 视觉层级更新：用户消息 > AI 气泡 > 卡片（气泡内下沉层 #0B1220）；**删除「AI 气泡最小宽 46%」**。
- [ ] e2e（门禁#5，与 006b 联合）：分析提问 → 文本先到 → 卡片加载→折叠 → 展开显示折线图。
- [ ] AC-005b-1（e2e-browser，[tablet,desktop]，前置：发提问→卡片就绪→展开）：tablet 无明细行容器（仅轴说明+图表），desktop 存在、行字号 12px、mono。
- [ ] AC-005b-2（e2e-browser，[mobile,desktop]，同前置）：展开态 svg viewBox=`0 0 340 112`，渲染宽 ≤ 容器宽。
- [ ] testing / lint / type。

## 备注
依赖 001b、004b（范围）；门禁#5 与 006b 联合流。

## 执行说明（Executor → Validator）
分支 `feat/005b-chart-card`。

- **明细行断点门控（AC-005b-1）**：rev 1 用 CSS `@media (width < 980px) { display:none }` 隐藏明细行——元素仍在 DOM。AC-005b-1 判定「tablet **不存在**明细行容器」，故改为 `useBreakpoint()` 断点条件渲染（`src/components/ChartCard.tsx`：`showRows = desktop|wide`），mobile/tablet 下 `.chart-card__rows` 真正不入 DOM；删去 `ChartCard.css` 对应 media query。与 C-3 SessionRail 同惯例（断点条件渲染，非 display:none）。
- **desktop 行 12px / mono**：`.chart-card__row` 字号 12px（既有）；行内 `.chart-card__row-date/-value` 带 `.num`（`src/design/global.css` → `--font-mono`）。e2e 直读 computed `font-size`=12px、`font-family` 匹配 `/mono/`。
- **svg 自适应（AC-005b-2）**：`viewBox=0 0 340 112` + CSS `max-width:100%`（既有 rev 1），渲染宽 ≤ 容器宽，未改。e2e 在 mobile/desktop 各读 `getBoundingClientRect().width` 断言 ≤ 容器（`.chart-card__expanded`）宽（含 0.5px 亚像素容差）。
- **视觉层级 / 删除「46% 最小宽」**：卡片下沉层 `--color-panel-deep=#0b1220`（既有）满足；层级 用户消息>AI 气泡>卡片 未变。C-5 判据「删除 AI 气泡最小宽 46%」括注**移交 C-6**，且 006b 文档（AC-006b-2）明列该删除为其交付，故本轮**不触** `ChatMessage.css`（其 `min-width: 46%` 由 006b 移除）。本需求「不做：气泡 min/max-width」与此一致。
- **测试**：单测 `ChartCard.test.tsx` 增 1 例（tablet 展开无明细行容器）、展开行用例 pin `innerWidth=1280` 保证断点确定；e2e `analysis-chart.spec.ts` 增 AC-005b-1（tablet/desktop）、AC-005b-2（mobile/desktop）两例。typecheck / lint / 172 unit / 19 e2e 全绿。
