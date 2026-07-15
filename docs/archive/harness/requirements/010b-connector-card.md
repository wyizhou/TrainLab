---
id: "010b"
status: verified
source_design_rev: 2
supersedes: "010"
superseded_by: null
contract_ref: "C-10"
branch: "feat/010b-connector-card"
---

# 连接器卡片响应式（返工）

## 背景 / 目标
落成 contract C-10（返工，design_rev 2）。卡片 grid `minmax(min(320px,100%),1fr)`，mobile 单列堆叠、desktop 两卡同排，均不溢出。rev 1 四状态集合/间隔选项/演示初始态全部保留。原 010 留 `completed/` 当 rev 1 历史，不改写。

## 范围
- 做：连接器卡片 grid 响应式（mobile 纵向堆叠、desktop 同排）、无横向溢出。
- 不做：四状态集合/间隔选项/演示初始态逻辑改动（rev 1 原样保留）。

## 涉及组件 / token
ConnectorCard、卡片 grid token。

## 验收标准（来源：contract.md C-10，Validator 只认该条目）
- [ ] rev 1 功能判据保留：状态集合齐全（已连接/未连接/同步中/同步失败含错误块与「重试同步」）；上次同步时间、已同步数量、自动同步间隔（30 分/1 时/6 时/仅手动）；演示初始态（中国区 ETIMEDOUT、国际区未连接）。
- [ ] unit：四状态各渲染对应胶囊与按钮文案。
- [ ] AC-010b-1（e2e-browser，/connectors，[mobile,desktop]）：mobile 两卡纵向堆叠（第二卡 top > 第一卡）；desktop 两卡同排（第二卡 top==第一卡、left 不同）；两视口 `scrollWidth <= innerWidth`。
- [ ] testing / lint / type。

## 备注
依赖 001b。不要求功能 e2e（unit 覆盖），AC-010b-1 响应式 e2e-browser 为验收组成部分。
