---
id: "008"
status: verified
source_design_rev: 1
supersedes: null
superseded_by: null
contract_ref: "C-8"
branch: "feat/008-activity-detail"
---

# 运动记录·详情 ActivityDetail + 时序双模式

## 背景 / 目标
落成 contract C-8。运动详情页，真实 FIT 解析 + 时序双模式。依赖 007。心率区间边界反向消费 C-14（先默认）。

## ⚠ 验收前置（硬，contract C-8 / Validator §7.3）
真实样本位于 `tests/fixtures/614797758_ACTIVITY.fit`（测试基础设施，已随 bootstrap 入库，源自 `design/v1.0/uploads/`）。Executor 开工时确认该文件存在；验收时若缺失，本需求判 **blocked**（非通过、非返工）。

## 范围
- 做：字段集=真实 FIT ∩ 佳明详情（缺失「--」）、指标分区标注 FIT 字段、时序双模式（降采样曲线⇄逐秒表）、心率区间条形图、Laps 表、下载 FIT（模拟）。
- 不做：轨迹地图（遗留建议，不做）、系统重算衍生指标。

## 涉及组件 / token
ActivityDetail、TimeSeriesChart、RecordTable。

## 验收标准（来源：contract.md C-8）
- [x] 首条「晨间轻松跑」为真实 FIT（`@garmin/fitsdk`）解析；缺失字段「--」；训练效果为 FIT 原始存储值。
- [x] 时序双模式：降采样曲线（跑步 8/骑行 6/游泳 2/力量 1，Y3 档 + X5 档 + 来源字段）⇄ 逐秒表（分页 20/50/100，行数=秒数）。
- [x] 心率区间图（time_in_hr_zone）边界取自设置区间设定（未落成用默认）；Laps 含平均功率列。
- [x] FIT 白名单断言（unit，≥8 项）：sport(+sub_sport)/start_time(精确)/total_timer_time/total_distance/avg_heart_rate/max_heart_rate/total_calories/avg_speed(配速换算)；total_ascent 若展示纳入；total_training_effect / total_anaerobic_training_effect 为原始存储值。容差：整数/时间戳精确，浮点按展示精度舍入。
- [x] e2e（门禁#4）：曲线⇄逐秒表 模式切换。
- [x] testing/lint/type：G-* 基线。

## 交付说明（Executor）
- 分支：`feat/008-activity-detail`（commit 7bc5939）。
- 依赖：新增 `@garmin/fitsdk@21.208.0`（runtime dependency，浏览器内解析）。
- FIT 解析：`src/activities/fitParser.ts`（summary / 逐秒 records / laps / hr-zone）。真实样本经 `?url` 资源导入 + `fetch` 在浏览器内解析（`src/activities/fitAsset.ts`），生产 `vite build` 已确认 FIT 资源随包产出。
- 列表首条 a0 的摘要值取自 FIT（`FIT_A0`，`src/activities/activityData.ts`），并由 `fitParser.test.ts` 对实时解析断言锁定（distance 5081.39 m / timer 1887.163 s / avgHr 152 / maxHr 170 / calories 344 / pace 371 / ascent 2 / TE 2.7 / 无氧 0，共 12 项 ≥8）。
- 心率区间边界：`src/activities/hrZones.ts` 的 `DEFAULT_HR_ZONES`（C-14 未落成前默认；条形长度用 FIT `time_in_hr_zone` 原始值，系统不重算）。
- 组件：`ActivityDetail` / `TimeSeriesChart`（Y 3 档 + X 5 档 + 来源字段）/ `RecordTable`（复用 `Pager`，行数=运动秒数 1890）/ `HrZoneChart`。路由 `/activities/:id`，列表行点击进入。
- 门禁结果：G-type `tsc --noEmit` 0 error；G-lint（eslint + prettier + stylelint）0；G-unit 102/102（新增 30）；e2e 7/7（含 C-8 门禁#4）；`npm run build` 通过。
- 说明：非 FIT 的 mock 记录详情页仅展示列表摘要 + 「--」，时序/分段显示空态（契约仅要求真实 FIT 那一条的完整双模式）。轨迹地图不做（范围外）。
