---
id: "004"
status: verified
source_design_rev: 1
supersedes: null
superseded_by: null
contract_ref: "C-4"
branch: "feat/004-scope-bar"
---

# 分析·数据范围选择器 ScopeBar

## 背景 / 目标
落成 contract C-4。分析对话的数据范围选择。

## 范围
- 做：3/7/15/30 天胶囊、选择具体运动覆盖时间范围、附带健康/习惯两开关（默认开）、实时范围摘要。
- 不做：图表渲染、AI 调用。

## 涉及组件 / token
ScopeBar。

## 验收标准（来源：contract.md C-4；不要求 e2e）
- [ ] 天数胶囊（默认 3）；「选择运动 (n)」勾选覆盖范围；两开关默认均开；底部摘要实时更新。
- [ ] unit：切换胶囊/勾选运动/开关 → 摘要与生效范围更新。
- [ ] testing/lint/type：G-* 基线。
