---
id: "003c"
status: verified
source_design_rev: 4
supersedes: "003b"
superseded_by: null
contract_ref: "C-3"
branch: "feat/003c-session-rail"
---

# 会话栏 + 分析布局视觉契约（pixel-contract 返工）

## 背景 / 目标
落成 contract C-3（返工，design_rev 3，fidelity: pixel-contract）。为会话栏与分析布局 shell 加 `data-vc` 锚点并锁定 computed 契约。原 003b 留 `completed/` 当 rev 2 历史，不改写。前序 rev 2 功能（会话增改删至空自动新建）与响应式判据全部保留。

## 范围
- 做：`session-rail`、`session-rail-item`、`session-rail-item-active`、`analysis-main`、`analysis-input` 镜像到对应组件根元素；命中 computed 契约达 §A 值（见 contract C-3 AC-003c-1..4）。
- 不做：会话数据模型/重命名/删除逻辑改动（rev 2 原样保留）。

## 涉及组件 / token
SessionRail / AnalysisLayout（analysis-main 外层 flex）/ AnalysisInput。

**token 依据（design_rev 4 re-base）**：token 唯一事实源 = v3.1 三表（表 a 颜色 / b 圆角 / c 间距，见 contract「G-token 权威源与 token 表」节）；本版补全 token 基础、目标 computed rgb/px 不变，**不新增/不修改任何 AC 判定值**。

## 验收标准（来源：contract.md C-3，Validator 只认该条目）
- [ ] 前序 rev 2 判据（会话增改删至空自动新建 e2e、desktop 212px aside / mobile-tablet 顶部下拉、AC-003b-1）全部保留。
- [ ] **硬要求**：上列 5 个 `data-vc` 锚点镜像到对应组件根元素。
- [ ] AC-003c-1..4（e2e-browser，desktop）：session-rail 布局（width 212 / bg / border / radius / padding）；session-rail-item 选中/常态（前置需 ≥2 会话使常态项同屏可命中）；analysis-main（flex / gap 18 / max-width 1200 / 居中）；analysis-input（bg / border / radius / padding / 非 fixed）。
- [ ] testing / lint / type。

## 备注
AC-003c-2 前置：确保存在 ≥2 会话（默认种子或先建一个），否则常态选择器选空。精确值见 contract C-3 各 AC-* 块。依赖 001c（全局 chrome）。
