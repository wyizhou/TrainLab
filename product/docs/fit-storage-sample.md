# TrainLab FIT 存储样本

生成日期：2026-07-23

解析器：`fitdecode 0.11.0`

样本来源：`test_data/new/*.fit`

本文档不是完整 FIT 导出，而是未来数据库结构的可读样本。原始 FIT
文件仍是无损事实来源；这里展示规范化后的活动、分段、传感器、专项数据和
未知消息目录。

## 展示规则

- 高频数据只显示前 3 行和后 2 行。
- `…省略 N 行…` 仅用于 Markdown 展示，不是数据库记录。
- 即使省略明细，也保留总行数、字段覆盖率和最小值/中位数/最大值。
- 时间统一保存为 UTC，同时派生 `Asia/Hong_Kong` 本地日期。
- 不展示精确 GPS 坐标、设备序列号、体重、性别和身高。
- `null` 表示该运动没有该字段或设备没有记录，不能自动解释成数值 0。

## 1. `activities`：通用活动概要

每个活动一行。结束时间由开始时间、活动时长、最后一个传感器点和最后一个
分段共同校验后得到，不能直接信任本批 FIT 的 `session.timestamp`。

| 样本 ID | 文件 | sport / sub_sport | 新加坡开始时间 | 推导结束时间（UTC） | elapsed / timer | 距离 | 心率均值/最大 | 热量 | 爬升/下降 |
|---|---|---|---|---|---:|---:|---:|---:|---:|
| A01 | `Running.fit` | running / generic | 2026-07-19 06:53:01 | 2026-07-19 01:04:34 | 7,893 / 7,750 s | 20.130 km | 161 / 184 bpm | 1,400 kcal | 80 / 83 m |
| A02 | `Bouldering.fit` | rock_climbing / bouldering | 2026-07-19 15:30:19 | 2026-07-19 09:06:47 | 5,787 / 5,787 s | null | 120 / 166 bpm | 537 kcal | null |
| A03 | `Indoor Climbing.fit` | rock_climbing / indoor_climbing | 2026-07-19 17:14:02 | 2026-07-19 10:40:16 | 5,175 / 5,175 s | null | 111 / 180 bpm | 424 kcal | 49 / 68 m |
| A04 | `hiking.fit` | hiking / generic | 2026-03-07 09:59:23 | 2026-03-07 07:36:24 | 20,221 / 20,221 s | 8.362 km | 108 / 150 bpm | 1,346 kcal | 348 / 427 m |
| A05 | `骑行.fit` | cycling / generic | 2026-02-17 16:48:57 | 2026-02-17 09:18:23 | 1,766 / 1,766 s | 8.062 km | 121 / 143 bpm | 184 kcal | 4 / 33 m |
| A06 | `力量训练.fit` | training / strength_training | 2026-03-18 06:53:45 | 2026-03-17 23:52:44 | 3,539 / 3,539 s | 0 km | 102 / 146 bpm | 233 kcal | null |

## 2. FIT message 覆盖概览

| 文件 | record | lap | split | set | workout_step | field_description | course_point | 未识别 message 行数/类型数 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `Running.fit` | 7,752 | 21 | 17 | 0 | 0 | 24 | 0 | 16,887 / 16 |
| `Bouldering.fit` | 4,848 | 1 | 34 | 0 | 0 | 0 | 0 | 11,615 / 12 |
| `Indoor Climbing.fit` | 3,016 | 1 | 10 | 0 | 0 | 0 | 0 | 10,396 / 12 |
| `hiking.fit` | 4,526 | 1 | 0 | 0 | 0 | 0 | 34 | 42,589 / 15 |
| `骑行.fit` | 428 | 2 | 0 | 0 | 0 | 0 | 0 | 3,760 / 15 |
| `力量训练.fit` | 1,970 | 0 | 58 | 58 | 32 | 0 | 0 | 7,108 / 12 |

这些行数用于数据质量检查，不代表所有 message 都应逐行复制进 SQLite。

## 3. `activity_samples`：高频传感器样本

建议每个时间点一行，常用字段使用明确列，运动专项和开发者字段放入同一行的
`extras_json`。一行可以同时包含来自手表、外接传感器和开发者字段的数据，
因此不能给整行绑定单一 `device_id`；来源必须按字段和有效时间范围记录在
`activity_metric_sources`。下面以跑步的 7,752 个记录点为例，GPS 只显示
是否存在。

| sample_index | timestamp_utc | HR | speed | distance | cadence | power | stance_time | vertical_oscillation | step_length | GPS |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 0 | 2026-07-18 22:53:01 | 111 bpm | 0.000 m/s | 0.00 m | 0 rpm | 0 W | null | null | null | 有 |
| 1 | 2026-07-18 22:53:02 | 110 bpm | 0.000 m/s | 0.00 m | 0 rpm | 7 W | null | null | null | 有 |
| 2 | 2026-07-18 22:53:03 | 110 bpm | 0.000 m/s | 2.40 m | 69 rpm | 7 W | null | null | null | 有 |
| … | …省略 7,747 行… | … | … | … | … | … | … | … | … | … |
| 7,750 | 2026-07-19 01:04:33 | 182 bpm | 2.771 m/s | 20,127.72 m | 88 rpm | 286 W | 261 ms | 81.4 mm | 944 mm | 有 |
| 7,751 | 2026-07-19 01:04:34 | 182 bpm | 2.771 m/s | 20,130.31 m | 88 rpm | 288 W | 261 ms | 81.4 mm | 944 mm | 有 |

### `activity_metric_sources`：字段级传感器来源

FIT 不一定提供“某个字段来自哪台设备”的明确关联。只有存在直接证据时才填写
设备；标准字段但无法关联设备时必须保留为 `device_unresolved`，不能根据字段名
猜测来自手表、胸带或功率计。

| metric_key | source_kind | device / developer | 有效范围 | 归因置信度 |
|---|---|---|---|---|
| `heart_rate` | standard_fit | device_unresolved | 整个活动 | unknown |
| `position` | standard_fit | device_unresolved | 整个活动 | unknown |
| `power` | standard_fit | device_unresolved | 整个活动 | unknown |
| `dr_gct` | developer_fit | developer_data_id=0 | 整个活动 | explicit_developer |
| `dr_total_power` | developer_fit | developer_data_id=0 | 整个活动 | explicit_developer |

如果活动中途切换设备，应拆成多个有效时间范围分别记录。原始设备序列号不在
Markdown 中展示。

### 跑步传感器字段概况

本表同时包含标准 FIT 字段与开发者字段。统计针对每个字段最终选定的 canonical
序列；若同一指标发生来源切换，还应生成按来源拆分的统计。

| 字段 | 来源 | 有值行数 | 覆盖率 | 最小值 | 中位数 | 最大值 |
|---|---|---:|---:|---:|---:|---:|
| heart_rate | standard_fit / device_unresolved | 7,752 | 100.00% | 109 bpm | 165 bpm | 184 bpm |
| enhanced_speed | standard_fit / device_unresolved | 7,752 | 100.00% | 0.000 m/s | 2.631 m/s | 2.986 m/s |
| cadence | standard_fit / device_unresolved | 7,752 | 100.00% | 0 rpm | 86 rpm | 90 rpm |
| power | standard_fit / device_unresolved | 7,750 | 99.97% | 0 W | 263 W | 357 W |
| stance_time | standard_fit / device_unresolved | 7,742 | 99.87% | 253 ms | 268 ms | 441 ms |
| vertical_oscillation | standard_fit / device_unresolved | 7,748 | 99.95% | 43.9 mm | 81.2 mm | 101.9 mm |
| vertical_ratio | standard_fit / device_unresolved | 7,738 | 99.82% | 6.43% | 8.96% | 12.91% |
| step_length | standard_fit / device_unresolved | 7,738 | 99.82% | 506 mm | 909 mm | 1,073 mm |
| temperature | standard_fit / device_unresolved | 7,752 | 100.00% | 25 °C | 29 °C | 32 °C |
| `dr_gct` | developer_data_id=0 | 7,751 | 99.99% | 246 ms | 267 ms | 1,417 ms |
| `dr_total_power` | developer_data_id=0 | 7,751 | 99.99% | 2.56 W | 244.24 W | 291.38 W |

异常极值只用于质量提示。例如 `dr_gct=1,417 ms` 可能是起停、静止或字段语义
差异，不能直接作为跑姿结论。

## 4. `activity_segments` 与 `climbing_routes`

所有 lap、攀爬、休息、力量组等先进入通用分段表；只有确实需要专项分析的
字段再进入 `climbing_routes` 或 `strength_sets`。

### 抱石线路

共 34 个 split：17 个 `climb_active` 和 17 个 `climb_rest`。下面只展示
17 个攀爬段中的前 3 个和后 2 个。

| split_index | 开始 UTC | 时长 | 原始难度 | Font 难度 | 完成 | 热量 |
|---:|---|---:|---:|---|---|---:|
| 0 | 07:30:19 | 156.756 s | 0 | 1 | 是 | 19 kcal |
| 2 | 07:33:51 | 28.577 s | 2 | 3 | 是 | 2 kcal |
| 4 | 07:34:35 | 28.607 s | 3 | 4 | 是 | 5 kcal |
| … | …省略 12 个攀爬段… | … | … | … | … | … |
| 30 | 08:48:28 | 157.706 s | 3 | 4 | 是 | 13 kcal |
| 32 | 08:55:44 | 660.597 s | 4 | 4+ | 否 | 46 kcal |

### 室内攀岩线路

| split_index | 开始 UTC | 时长 | 原始难度 | Font 难度 | 完成 | falls | 上升 |
|---:|---|---:|---:|---|---|---:|---:|
| 0 | 09:14:02 | 244.212 s | 10 | 6a+ | 是 | 0 | 12 m |
| 2 | 09:41:29 | 208.994 s | 8 | 5c | 是 | 0 | 13 m |
| 6 | 09:53:33 | 182.089 s | 10 | 6a+ | 是 | 0 | 12 m |
| 8 | 10:14:07 | 262.407 s | 10 | 6a+ | 是 | 0 | 11 m |

难度转换值属于解析规则，数据库必须同时保留 `grade_raw`、`grade_system`
和转换后的 `grade_display`，以便未来修正规则。

## 5. `strength_sets`：力量训练组

该样本有 58 个 set：30 个 active、28 个 rest。下面展示 active set 的
前 3 个和后 2 个；休息段保留在 `activity_segments` 中。

| active_index | set_message_index | workout_step | 动作/阶段 | 时长 | 次数 | 重量 |
|---:|---:|---:|---|---:|---:|---:|
| 0 | 0 | 0 | warmup | 372.252 s | null | null |
| 1 | 1 | 1 | pull_up / 辅助引体 | 35.333 s | 6 | 33 kg |
| 2 | 3 | 1 | pull_up / 辅助引体 | 28.970 s | 6 | 29 kg |
| … | …省略 25 个 active set… | … | … | … | … | … |
| 28 | 55 | 28 | deadlift | 1.502 s | 0 | 0 kg |
| 29 | 57 | 31 | cooldown | 152.494 s | null | null |

末尾的 `0 次/0 kg` 需要标记为可疑或未填写，而不是直接用于训练量计算。

## 6. `fit_metric_definitions`：开发者传感器定义

跑步样本含 24 个 `field_description`。这些定义让动态字段能够被正确解释，
但它们本身不是传感器采样点。

| field_name | native message | field number | base type | unit |
|---|---|---:|---|---|
| `dr_s_distance` | session | 160 | float32 | m |
| `dr_s_avg_cadence` | session | 162 | float32 | spm |
| `dr_s_avg_gct` | session | 164 | float32 | ms |
| … | …省略 19 个定义… | … | … | … |
| `dr_v_ILR` | record | 15 | float32 | bw/s |
| `dr_body_Y_PIF` | record | 20 | float32 | g |

## 7. `fit_unknown_message_catalog`：未知消息目录

这里只保存目录、字段签名和出现次数；未知消息的完整原始值继续保存在 FIT
文件中，避免将小型二进制文件膨胀成巨量 JSON。

| 文件 | global message | 出现次数 | 当前处理 |
|---|---:|---:|---|
| `Running.fit` | 233 | 7,908 | 原始 FIT 保留，登记字段签名 |
| `Running.fit` | 534 | 7,752 | 原始 FIT 保留，登记字段签名 |
| `Bouldering.fit` | 233 | 5,792 | 原始 FIT 保留，登记字段签名 |
| `Bouldering.fit` | 534 | 5,789 | 原始 FIT 保留，登记字段签名 |
| `Indoor Climbing.fit` | 233 | 5,190 | 原始 FIT 保留，登记字段签名 |
| `Indoor Climbing.fit` | 534 | 5,175 | 原始 FIT 保留，登记字段签名 |
| `hiking.fit` | 233 | 20,226 | 原始 FIT 保留，登记字段签名 |
| `hiking.fit` | 534 | 20,222 | 原始 FIT 保留，登记字段签名 |
| `骑行.fit` | 233 | 1,780 | 原始 FIT 保留，登记字段签名 |
| `骑行.fit` | 534 | 1,767 | 原始 FIT 保留，登记字段签名 |
| `力量训练.fit` | 233 | 3,545 | 原始 FIT 保留，登记字段签名 |
| `力量训练.fit` | 534 | 3,540 | 原始 FIT 保留，登记字段签名 |

解析器升级并认识这些 message 后，可以从原始 FIT 重新解析，写入正式的
传感器或专项表。

## 8. 本批样本的数据质量提示

| 严重度 | 发现 | 影响 | 建议 |
|---|---|---|---|
| 高 | 六个样本的 `session.timestamp` 均等于开始时间 | 直接写入会令结束时间错误 | 使用活动时长、最后 record 和最后 segment 交叉推导 |
| 高 | 当前导入器没有处理 split、set、workout_step、field_description 和 course_point | 丢失攀岩线路、力量组和开发者传感器语义 | 扩展解析器并记录 parser/profile 版本 |
| 中 | `hiking.fit` 的 course point 时间属于更早的路线定义 | 可能被误当成当次活动轨迹 | course/navigation 数据与 activity sample 分开保存 |
| 中 | 跑步 `dr_gct` 存在 1,417 ms 极值 | 可能扭曲跑姿汇总 | 起停过滤后再计算分位数，保留原始值 |
| 中 | 力量训练末尾存在 `0 次/0 kg` | 可能错误降低训练量 | 标记为缺失/可疑，不能自动当作有效零值 |
| 中 | 各文件存在大量未知 Garmin message | 新设备字段暂时不可分析 | 保存原始 FIT、字段签名和解析器版本，支持重解析 |
| 中 | 标准 FIT 传感器字段不总能关联具体设备 | 可能把胸带、手表或外接功率计错误归因 | 使用字段级来源；无直接证据时标为 `device_unresolved` |

## 9. 面向 AI 的读取方式

正常日报或周报不直接加载成千上万行传感器数据，而是按以下顺序读取：

1. `activities` 通用概要。
2. 与运动类型对应的 `climbing_routes`、`strength_sets` 或跑步特征。
3. `activity_features` 中预计算的区间、分位数、趋势和质量标记。
4. 只有出现异常或需要技术复盘时，才读取限定时间窗口的
   `activity_samples`。

这样既保留完整分析能力，也能控制数据库查询量和模型上下文大小。
