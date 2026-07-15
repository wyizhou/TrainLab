---
id: "008b"
status: verified
source_design_rev: 2
supersedes: "008"
superseded_by: null
contract_ref: "C-8"
branch: "feat/008b-activity-detail"
---

# 运动详情响应式（返工）

## 背景 / 目标
落成 contract C-8（返工，design_rev 2）。mobile 逐秒表 / Laps 行转卡片、无 min-width 大表溢出；时序图表 X 轴刻度按断点分档、图表不溢出。rev 1 FIT 字段白名单/时序双模式/心率区间图/Laps 平均功率全部保留。原 008 留 `completed/` 当 rev 1 历史，不改写。

## 验收前置（硬，已满足）
真实样本 `tests/fixtures/614797758_ACTIVITY.fit`（`fixture_owner: human`，245KB）已在 repo，无新增 human fixture、无 blocked 风险；FIT 字段白名单断言（≥8 项）原样保留。

## 范围
- 做：mobile 逐秒表卡片模式（无 `min-width:820px` 元素）、Laps 每圈一卡、无横向溢出；时序图 X 轴 desktop 5 档 / mobile 3 档、Y 轴恒 3 档、svg 不溢出容器。
- 不做：FIT 解析/字段白名单/双模式切换逻辑改动（rev 1 原样保留）。

## 涉及组件 / token
ActivityDetail、TimeSeriesChart、RecordTable、LapsTable。

## 验收标准（来源：contract.md C-8，Validator 只认该条目）
- [ ] rev 1 功能判据保留：字段集=真实 FIT ∩ 佳明详情、首条「晨间轻松跑」、缺失显「--」；指标分区标 FIT 字段名、训练效果为原始存储值；时序双模式；心率区间条形图；Laps 平均功率列 + 下载主按钮。
- [ ] FIT 字段白名单断言（unit，≥8 项）：sport / start_time / total_timer_time / total_distance / avg_heart_rate / max_heart_rate / total_calories / avg_speed 等，容差见 contract C-8。
- [ ] e2e（门禁#4）：降采样曲线 ⇄ 逐秒表 模式切换。
- [ ] AC-008b-1（e2e-browser，/activities/1，mobile，前置：切换至逐秒数据表）：逐秒表卡片模式无 `min-width:820px` 元素；Laps 每圈一卡；`scrollWidth <= 390`。
- [ ] AC-008b-2（e2e-browser，[mobile,desktop]）：desktop X 轴 5 档、mobile 3 档、Y 轴恒 3 档；每张 svg 渲染宽 ≤ 容器宽。
- [ ] testing / lint / type。

## 备注
依赖 001b、007b（列表首条）；心率区间边界读 014b 设置。
