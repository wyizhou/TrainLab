---
id: "001b"
status: verified
source_design_rev: 2
supersedes: "001"
superseded_by: null
contract_ref: "C-1"
branch: "feat/001b-foundation"
---

# 全局响应式基线 + 双模导航（返工）

## 背景 / 目标
落成 contract C-1（返工，design_rev 2）。v2.0 把 rev 1 单一「平板 `<980px`」断点升级为四档矩阵（mobile/tablet/desktop/wide），并引入移动端双模导航（顶部导航 ⇄ 底部固定 tab）。本条是 v2.0 全设备响应式的地基，其余 002b–014b 依赖其 BreakpointState 与导航壳。原 001 留 `completed/` 当 rev 1 历史，不改写。

## 范围
- 做：BreakpointState 四断点（`innerWidth` 驱动、resize 即时生效）；mobile 隐藏 TopNav、渲染底部固定 tab 栏 5 项；desktop 顶部导航 + 同步胶囊；主内容区 padding 按断点分级；全部路由所有断点无横向溢出。rev 1 功能面（五项导航顺序、默认落分析页、集中 token、tabular-nums）沿用。
- 不做：各业务页面内部响应式（各自 00Xb 负责）；视觉纯色值保真（G-token 承接）。

## 涉及组件 / token
BreakpointState、TopNav、BottomTabBar（新，mobile 形态）、Header、Main、主内容区 padding token。

## 验收标准（来源：contract.md C-1，Validator 只认该条目）
- [ ] rev 1 功能判据保留：build/dev 成立；导航五项顺序 分析(默认)/运动记录/健康记录/连接器/设置；`/` → 分析页；集中 token + tabular-nums。
- [ ] BreakpointState 四区间 + resize 即时生效（unit）。
- [ ] AC-001b-1..5（e2e-browser）：mobile 底部 tab 5 项且顶部导航不在 DOM / tablet 顶部导航且无底部 tab、无同步胶囊 / desktop 有同步胶囊 / 主内容 padding 分级 / 五路由双模可达 + 默认落分析页 + 每路由每视口无横向溢出。
- [ ] testing：`npm run test`、`npm run e2e`；lint：`npm run lint`；type：`npm run typecheck`。

## 备注
判定精确值（padding、tab 高度、断点边界）见 contract C-1 各 AC-* 块。门禁#6（响应式无溢出冒烟）在闭合需求处统一验，本条先满足自身 AC-001b-*。
