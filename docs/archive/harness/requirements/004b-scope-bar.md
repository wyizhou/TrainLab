---
id: "004b"
status: verified
source_design_rev: 2
supersedes: "004"
superseded_by: null
contract_ref: "C-4"
branch: "feat/004b-scope-bar"
---

# 分析·范围选择器响应式 + 保真（返工，轻）

## 背景 / 目标
落成 contract C-4（返工，design_rev 2）。逻辑无变更，仅移动重排（勾选项组 mobile flex-wrap 换行）+ 保真。rev 1 从未在 mobile e2e 验证。原 004 留 `completed/` 当 rev 1 历史，不改写。

## 范围
- 做：mobile 下「附带健康记录」「附带习惯记录」两开关 flex-wrap 换行、无横向溢出；保真。
- 不做：胶囊/选择运动/开关默认/摘要联动逻辑改动（rev 1 原样保留）。

## 涉及组件 / token
ScopeBar（勾选项组 mobile 换行）。

## 验收标准（来源：contract.md C-4，Validator 只认该条目）
- [ ] rev 1 功能判据保留：3(默认)/7/15/30 天胶囊；「选择运动 (n)」展开勾选列表覆盖时间范围；两开关默认均开；底部范围摘要实时联动。
- [ ] unit：切换胶囊/勾选运动/开关 → 摘要与生效范围更新。
- [ ] AC-004b-1（e2e-browser，/，mobile）：两开关不在同一水平行（第二项 top > 第一项）；`documentElement.scrollWidth <= 390`。
- [ ] testing / lint / type。

## 备注
依赖 001b。不要求功能 e2e（unit 覆盖），但 AC-004b-1 响应式 e2e-browser 为验收组成部分。
