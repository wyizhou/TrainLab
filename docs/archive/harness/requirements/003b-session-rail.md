---
id: "003b"
status: verified
source_design_rev: 2
supersedes: "003"
superseded_by: null
contract_ref: "C-3"
branch: "feat/003b-session-rail"
---

# 分析·会话栏响应式（返工）

## 背景 / 目标
落成 contract C-3（返工，design_rev 2）。desktop 保留 212px 左栏 aside；mobile/tablet 降级为顶部下拉选择 + 新建按钮。rev 1 会话增改删功能全部保留。原 003 留 `completed/` 当 rev 1 历史，不改写。

## 范围
- 做：desktop 212px 会话 aside；mobile/tablet 顶部下拉（会话 `select` + 新建按钮）；断点切换。
- 不做：会话数据模型/重命名/删除逻辑改动（rev 1 原样保留）。

## 涉及组件 / token
SessionRail（desktop aside ⇄ mobile/tablet 下拉两形态）。

## 验收标准（来源：contract.md C-3，Validator 只认该条目）
- [ ] rev 1 功能判据保留：桌面 212px 会话栏（新建主按钮、会话项含名称+消息数、选中态左侧强调色条）；行内重命名（Enter 确认/Esc 取消）；删除当前会话切到第一个；删空自动新建。
- [ ] e2e：新建 → 重命名 → 删除至空自动新建 完整链路。
- [ ] AC-003b-1（e2e-browser，/，[mobile,tablet,desktop]）：desktop 存在 offsetWidth≈212 会话 aside；mobile/tablet 该 aside 不存在且存在会话 `select` + 新建按钮。
- [ ] testing / lint / type。

## 备注
依赖 001b。
