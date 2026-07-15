---
id: "006c"
status: verified
source_design_rev: 4
supersedes: "006b"
superseded_by: null
contract_ref: "C-6"
branch: "feat/006c-chat-html"
---

# 对话气泡视觉契约（pixel-contract 返工）

## 背景 / 目标
落成 contract C-6（返工，design_rev 3，fidelity: pixel-contract）。为 AI/用户气泡加 `data-vc` 锚点并锁定 computed 契约（独立面板背景+边框，非裸文字）。原 006b 留 `completed/` 当 rev 2 历史，不改写。前序 rev 2 功能与响应式判据全部保留。

## 范围
- 做：`chat-bubble-ai`、`chat-bubble-user` 镜像到对话气泡组件根元素；命中 computed 契约达 §A 值（见 contract C-6 AC-006c-1..3），含 max-width 断点分级。
- 不做：HTML 渲染/计划表格/系统提示/转义白名单逻辑改动（rev 2 原样保留）。

## 涉及组件 / token
ChatMessage（AI / 用户两态气泡）。

**token 依据（design_rev 4 re-base）**：token 唯一事实源 = v3.1 三表（表 a 颜色 / b 圆角 / c 间距，见 contract「G-token 权威源与 token 表」节）；本版补全 token 基础、目标 computed rgb/px 不变，**不新增/不修改任何 AC 判定值**。

## 验收标准（来源：contract.md C-6，Validator 只认该条目）
- [ ] 前序 rev 2 判据（HTML 渲染/计划表格/系统提示不入流/转义白名单 unit、尾角不对称 4px、移除 46% 最小宽、AC-006b-1/2）全部保留。
- [ ] **硬要求**：`chat-bubble-ai`、`chat-bubble-user` 镜像到对话气泡组件根元素。
- [ ] AC-006c-1..3（e2e-browser）：AI 气泡完整契约（bg / border / radius 14/14/14/4 / padding / color）；用户气泡（实心蓝 / 无边框 / radius 14/14/4/14 / padding / color）；max-width 断点分级（desktop 实测 82%/68%，tablet/mobile authored 复核）。
- [ ] testing / lint / type。

## 备注
max-width 验法（百分比 vs 像素 ±1px）见 contract C-6 AC-006c-3 + 验法细则。依赖 001c、005c。

## 验收记录（Validator, 2026-07-14）
被测分支 `feat/006c-chat-html`。逐条对照 contract C-6：
- G-lint ✓（0 error/warning，含 G-token 裸值 0）、G-type ✓（tsc 0 error）、G-unit ✓（39 files / 183 tests 全绿，含 rev1/rev2 功能判据：ChatMessage / sanitizeHtml / aiReply / SysPrompt）。
- AC-006b-1（尾角不对称 4px）、AC-006b-2（移除 46% 最小宽 + mobile max-width 100%）→ analysis-bubble.spec 通过。
- data-vc 硬要求：`chat-bubble-ai`、`chat-bubble-user` 锚点均命中（computed 断言未选空）。
- AC-006c-1（AI 气泡 bg rgb(18,26,40)/borderPanel 1px rgb(34,48,73)/radius 14-14-14-4/pad 13-16/color rgb(230,235,244)）✓
- AC-006c-2（用户气泡 bg rgb(46,92,158)/border none/radius 14-14-4-14/pad 12-14/color rgb(230,235,244)）✓
- AC-006c-3（max-width 分档 AI 82/92/100%、user 68/80/94%，desktop 实测 + tablet/mobile authored 复核，±1px）✓
- e2e 全套 46/46 通过，含门禁#5（analysis-chart 联合流）、门禁#6（responsive-nav）无回归。
结论：**PASS**，合并 `feat/006c-chat-html` → `main`（no-ff），删除已合并分支。
