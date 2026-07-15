---
id: "005"
status: verified
source_design_rev: 1
supersedes: null
superseded_by: null
contract_ref: "C-5"
branch: "feat/005-chart-card"
---

# 分析·图表卡片四态 ChartCard

## 背景 / 目标
落成 contract C-5。AI 回复气泡内嵌图表卡片四态。依赖 004（范围）。

## 范围
- 做：加载/空态/折叠/展开四态、340×112 折线图与轴刻度、视觉层级、平板展开态隐藏数据行。
- 不做：AI 文本/HTML 渲染（C-6）。

## 涉及组件 / token
ChartCard。

## 验收标准（来源：contract.md C-5）
- [ ] 四态可判定（加载 shimmer≈1.1s / <2 次运动空态不可展开 / 折叠一行摘要 / 展开折线图 Y3 档 X 首中末 + 数据行）。
- [ ] 视觉层级：用户消息>AI 气泡(最小宽 46%)>卡片(下沉 #0B1220)。
- [ ] 平板 `<980px` 展开态隐藏数据行仅留图表。
- [ ] unit：<2 次→空态；≥2 次→折叠/展开。
- [ ] e2e（门禁#5，与 C-6 联合）：提问→文本先到→加载→折叠→展开折线图。
- [ ] testing/lint/type：G-* 基线。

## 执行说明（Executor → Validator）
- 组件：`src/components/ChartCard.tsx` + `ChartCard.css`；单测 `ChartCard.test.tsx`（4 用例，全绿）。
- 视觉层级 demo 落在 `src/pages/AnalysisPage.tsx`（用户消息 > AI 气泡 min 46% > 下沉卡片）。AI 文本/HTML 渲染属 C-6，此处气泡内仅放占位文案 + 卡片，未做 HTML 渲染。
- 「实心蓝」取现有 token `--color-accent`（contract C-5 只写「实心蓝」，未写具体 hex；design 文档的 `#2E5C9E` 非 contract 标准）。因权限矩阵 deny 覆盖了 `src/design/`，未新增 token。
- 平板 `<980px` 展开态隐藏数据行由 CSS media query 实现（jsdom 不生效，无法 unit 断言，与既有组件同）。
- **e2e 门禁#5 未跑通、也未伪造**：该门禁为 C-5＋C-6 联合流（发送分析提问→AI 文本先到→…），依赖 C-6（006，尚未实现）的对话发送链路，无法独立跑通。本轮以 unit 覆盖四态与转换为验收基准；门禁#5 应在 006 完成时联合补跑。既有 4 条 e2e（登录/导航/会话栏）本轮仍全绿，未被本改动破坏。
- 遗留：`src/COMMIT_EDITMSG.tmp`（feat 分支工作树里的未跟踪临时提交信息文件）因 `rm` 不在 allowlist 未能删除，非任何提交的一部分，可由人工清理。
