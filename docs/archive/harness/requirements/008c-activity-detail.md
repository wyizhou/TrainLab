---
id: "008c"
status: verified
source_design_rev: 4
supersedes: "008b"
superseded_by: null
contract_ref: "C-8"
branch: "feat/008c-activity-detail"
---

# 指标卡 + 心率区间条视觉契约（pixel-contract 返工）

## 背景 / 目标
落成 contract C-8（返工，design_rev 3，fidelity: pixel-contract）。为指标卡与心率区间条加 `data-vc` 锚点并锁定 computed 契约（含 grid 自适应、五区配色）。原 008b 留 `completed/` 当 rev 2 历史，不改写。前序 rev 2 功能与响应式判据全部保留。

## 范围
- 做：`metric-card`、`hr-zone-bar` 镜像到对应组件根元素；命中 computed 契约达 §A 值（见 contract C-8 AC-008c-1..2）。
- 不做：FIT 字段白名单/时序双模式/Laps/心率区间边界逻辑改动（rev 2 原样保留）。

## 涉及组件 / token
MetricCard / HrZoneBar（五区段为其直接子元素）。

**token 依据（design_rev 4 re-base）**：token 唯一事实源 = v3.1 三表（表 a 颜色 / b 圆角 / c 间距，见 contract「G-token 权威源与 token 表」节）；本版补全 token 基础、目标 computed rgb/px 不变，**不新增/不修改任何 AC 判定值**。hr-zone-bar 圆角具名 token radiusZone（4px）；五区色复用 textFaint/accent/success/warn/danger。

## 验收标准（来源：contract.md C-8，Validator 只认该条目）
- [ ] **验收前置**：真实样本 `tests/fixtures/614797758_ACTIVITY.fit`（fixture_owner: human）已在 repo，无新增 human fixture。
- [ ] 前序 rev 2 判据（FIT 字段白名单 ≥8 项、时序双模式、门禁#4、Laps、心率区间边界取自设置、AC-008b-1/2）全部保留。
- [ ] **硬要求**：`metric-card`、`hr-zone-bar` 镜像到对应组件根元素。
- [ ] AC-008c-1（e2e-browser，desktop，/activities/1）：metric-card bg/border/radius/padding + grid auto-fit 已填充列 ≥130px。
- [ ] AC-008c-2（e2e-browser，desktop）：hr-zone-bar height 16 / radius 4；按容器内五段子元素顺序比 Z1–Z5 computed background-color。
- [ ] testing / lint / type。

## 备注
grid auto-fit 判法 + 五区子元素顺序验法见 contract C-8 AC-* 块 + 验法细则。依赖 001c、007c；心率区间边界续消费 014c。
