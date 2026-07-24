# 第二层：Garmin 数据采集工具层开发契约

状态：已冻结

契约版本：1

冻结日期：2026-07-23

实现状态：尚未开始

依赖契约：[01-data-foundation.md](01-data-foundation.md) v2.4

上游基线：[`garminconnect==0.3.6`](https://pypi.org/project/garminconnect/)；
活动 ORIGINAL 下载行为以
[`python-garminconnect` 固定版本源码](https://github.com/cyberjunky/python-garminconnect/blob/2ae0eb5d6e56a13bc0194e229992c3a7d855253c/garminconnect/__init__.py)
为准。

## 1. 目标

数据采集层负责将 Garmin Connect 中的健康生理数据、所有类型的已完成活动及其
附属数据，可靠地写入第一层定义的原始对象、revision、canonical、coverage 和
质量表。

它以一次性 Python API 和 CLI tools 的形式存在：

- 每次调用完成明确的一次 full、incremental、snapshot、repair 或 audit 工作后退出。
- 不启动 daemon、scheduler、worker、后台线程或永久网络监听。
- 第五层决定何时、以什么频率调用这些工具。
- 全量、增量、当天快照和修复共用同一资源目录、抓取器、解析器和入库管线。
- 相同数据重复同步为 no-op；Garmin 后续修正形成新 revision。
- 原始 JSON 和有效 FIT 先可靠落盘，再发布数据库投影；活动 ZIP 只作为受控的
  临时传输容器。

本层是 Garmin 事实的唯一运行时写入者，不分析训练含义，不生成建议或邮件。

## 2. 非目标和生命周期

本层不负责：

- 每天几点运行、每周哪天运行或错过后何时补跑。
- cron、launchd、systemd timer、常驻进程、进程守护和服务重启。
- 每日/每周健康分析、训练建议或模型上下文生成。
- Gmail 发送、回复和标签处理。
- 删除或修改 Garmin Connect 云端数据。
- 上传活动、创建 workout、训练计划或目标。
- 同步徽章、挑战、社交数据和 Garmin 未来训练计划。
- 直接修复用户的原始健康值或 FIT 记录。

一次工具调用的生命周期固定为：

```text
加载配置 → 获取单写锁 → 登录/校验身份 → 建立 run
→ 枚举工作项 → 抓取并保存原始对象 → 解析/投影/对账
→ 更新 coverage、游标、缺口和 run receipt → 释放锁 → 退出
```

网络等待、解析和大文件校验不得占用 SQLite 写事务。工具退出后不得留下后台线程。

## 3. 已冻结的核心决策

1. 公共形态是稳定 Python API 加一次性 CLI；第五层优先以子进程调用 CLI。
2. 目标实现使用 Python `>=3.12`，锁定 `garminconnect==0.3.6`。
3. `python-garminconnect` 只负责认证和调用 Garmin Connect；同步状态、重试、
   幂等、补漏、解析和入库由本层负责。
4. 本层禁用库的通用 API retry，使用自己的统一、可记录重试策略。
5. “所有健康生理数据”按语义完整覆盖，不机械重复调用别名、组合包装和可本地
   重算的重复汇总。
6. “运动数据”指所有运动类型的已完成活动，以及活动 summary、FIT、splits、
   sets、zones、weather、gear 和个人纪录；不含未来训练计划。
7. 健康生理数据以 Connect JSON 为原始事实源。
8. 活动采用 Connect JSON 与 FIT 双事实源；原始下载优先请求 `ORIGINAL`，
   安全提取并保存有效 FIT，不长期保存 ZIP。
9. FIT 是 record、lap、split、set、workout step、开发者字段和传感器流的首选来源。
10. Connect JSON 是 provider ID、名称、类型、用户修改、Garmin 后处理和
    Connect 专属附属数据的首选来源。
11. `get_activity_details` 的 chart 只在无可用 FIT 时作为降级数据，不能覆盖 FIT。
12. full 和 incremental 默认只推进到昨天；今天由 snapshot 读取并标记 partial。
13. incremental 固定重拉最近 14 个已结束日期，并限额处理历史失败和缺口。
14. 长时间 429 不让工具无限阻塞；持久化 `next_retry_at_utc` 后返回 deferred。
15. 原始对象不可变；相同哈希不重复，内容变化新增 revision。
16. Garmin 云端缺失不传播为本地删除；只有两次完整 inventory 均缺失才标记
    `provider_deleted`，本地原始证据永久保留。
17. 当前 Drive/Excel/FIT 生产同步在正式迁移前继续运行；新旧路径不得静默混用
    canonical 来源。

## 4. 公共 CLI

目标 CLI：

```text
trainlab garmin auth
trainlab garmin sync full [--health-from DATE] [--through DATE]
trainlab garmin sync incremental [--through DATE]
trainlab garmin sync snapshot [--date DATE]
trainlab garmin repair [--from DATE] [--through DATE]
                       [--resource KIND] [--activity-id ID]
                       [--strategy auto|refetch|reparse|reconcile]
trainlab garmin audit [--from DATE] [--through DATE]
trainlab garmin status
```

规则：

- 不提供 `--daemon`、`--schedule` 或任何轮询参数。
- 日期参数是 `Asia/Singapore` 本地日期，格式严格为 `YYYY-MM-DD`。
- `--through` 为包含式上界；full/incremental 不允许晚于昨天且默认昨天，
  repair/audit 不允许晚于今天。
- snapshot 的 `--date` 默认今天；历史 snapshot 仍不推进 completed cursor。
- full 的 `--health-from` 覆盖配置值，但不能早于显式允许的数据保留边界。
- repair 至少需要日期范围、resource 或 activity ID 之一，避免无界修复。
- status 只读运行表，不访问 Garmin。
- 所有命令只向 stdout 输出 `SyncReceipt` JSON，不输出健康 payload 或 FIT 内容。

### 4.1 CLI 退出码

| 退出码 | receipt 状态 | 含义 |
|---:|---|---|
| 0 | `succeeded` | 本次请求范围完成 |
| 10 | `partial` | 已取得进展，但仍有失败或未完成项 |
| 11 | `deferred` | 因长时间限流等原因安全推迟 |
| 12 | `lock_busy` | 已有另一采集工具持有单写锁 |
| 20 | `auth_required` | token 不可恢复，需要重新认证 |
| 21 | `failed` | 配置、存储或不可恢复运行错误 |

第五层必须同时检查退出码和 receipt，不得只根据“进程已退出”判断成功。

## 5. Python API 和数据类型

稳定入口：

```python
GarminCollectionTool.execute(request: SyncRequest) -> SyncReceipt
```

`SyncRequest` 固定包含：

- `mode`：`auth`、`full`、`incremental`、`snapshot`、`repair`、`audit`、
  `status`。
- `health_from_local_date`。
- `through_local_date`。
- `snapshot_local_date`。
- `resource_kinds`。
- `activity_ids`。
- `repair_strategy`：`auto`、`refetch`、`reparse`、`reconcile`。
- `invocation_id`：第五层可选传入的幂等调用标识。

`SyncReceipt` 固定包含：

- `schema_version`。
- `run_id`。
- `mode`。
- `status`：`succeeded`、`partial`、`deferred`、`failed`、
  `auth_required`、`lock_busy`。
- `requested_range` 和 `effective_range`。
- `coverage_state`：`complete` 或 `partial`。
- `counts`：`fetched`、`empty`、`unchanged`、`revised`、`failed`、
  `deferred`、`not_available`、`not_enabled`。
- `complete_through_by_resource`。
- `open_gap_count`。
- `next_retry_at_utc`。
- `errors`：只含错误 code、resource、逻辑对象和脱敏摘要。
- `started_at_utc`、`completed_at_utc`。

Python API 和 CLI 必须调用同一个 application service；CLI 不复制业务规则。
`auth` 所需秘密通过注入的交互式 credential provider 取得，不进入
`SyncRequest`；不适用于 auth/status 的日期、游标和计数字段使用 `null` 或空集合。
这些类型在实现时必须具有版本化 JSON Schema，供第五层验证。

## 6. 配置契约

目标配置至少包含：

```yaml
garmin:
  history_start_date: YYYY-MM-DD
  region: global
  token_store: state/secrets/garmin
  lookback_days: 14
  max_repair_items_per_incremental: 100
  request_min_interval_ms: 500
  request_timeout_seconds: 30
  max_attempts: 5
  retry_base_seconds: 2
  retry_max_seconds: 60
  inline_retry_after_max_seconds: 120
  rate_limit_fallback_seconds: 900
```

规则：

- `history_start_date` 是首次 full 健康同步的必填下界；Garmin 没有可靠的
  “最早健康日期”接口，不能通过最早活动日期或连续空日猜测。
- full 可以通过 `--health-from` 显式覆盖，但实际采用值必须写入 receipt。
- `region` 仅允许 `global` 或 `cn`。
- token store 必须位于允许的敏感状态目录，目录权限 `0700`、文件权限 `0600`。
- 配置和日志不得保存 Garmin 密码、MFA、access token 或 refresh token。
- 所有重试和限额值可配置，但上述值是首版默认。
- 第二层配置不得包含执行时间、星期规则或定时表达式。

## 7. 认证和账号绑定

`trainlab garmin auth` 是一次性、可交互工具：

1. 从 TTY 或仅本进程可见的安全输入读取账号和密码。
2. 需要 MFA 时只在 TTY 请求一次性验证码。
3. 登录成功后让 `python-garminconnect` 写入专用 token store。
4. 将 token 文件权限收紧为 `0600`。
5. 调用 profile/self 类接口取得稳定身份，生成 HMAC。
6. 与 `subject_identities(provider=garmin)` 对账。
7. 输出不含账号、token 和授权响应的 `SyncReceipt(mode=auth)`。

首次绑定创建 verified identity。后续登录若得到不同身份，必须返回明确
`identity_mismatch`，不能自动把另一个 Garmin 账号的数据写入现有 subject。
账号切换需要未来单独的显式 rebind 流程，不属于本契约。

正常同步只加载 token；不得在定时调用时依赖明文密码。库完成 token refresh 后仍
返回 401 时，本层结束为 `auth_required`。

## 8. 资源目录和覆盖口径

实现时使用版本化 `GarminResourceSpec` 目录。每个资源声明：

- `resource_kind`
- 对应的 `python-garminconnect` 方法
- scope：`account`、`daily`、`range`、`activity`
- required、conditional 或 ignored
- 日期分块限制
- 空值、未启用、不可用和禁止访问的判定规则
- raw object kind
- parser/adapter 版本
- 第一层投影目标
- 是否允许推进 completed cursor

### 8.1 健康生理资源

首版 required 或 conditional 资源：

| 数据族 | 采用的接口/数据 | 第一层落点 |
|---|---|---|
| 账号与设置 | user profile、user profile settings | `data_subjects`、`subject_identities`、`physiology_records` |
| 设备 | devices、primary device、device settings、last used | `devices`、`physiology_records` |
| 日汇总 | `get_user_summary` | `daily_health` |
| 步数时序 | `get_steps_data`；range steps 可作为批量校验 | `health_samples`、`daily_health` |
| 楼层 | `get_floors` | `health_samples`、`daily_health` |
| 心率 | `get_heart_rates`、`get_rhr_day` | `health_samples`、`daily_health` |
| 补水 | `get_hydration_data` | `health_samples`、`daily_health` |
| 呼吸 | `get_respiration_data` | `health_samples`、`daily_health` |
| 血氧 | `get_spo2_data` | `health_samples`、`daily_health` |
| 强度分钟 | `get_intensity_minutes_data` | `daily_health`、`physiology_metrics` |
| 压力 | `get_all_day_stress` | `health_samples`、`daily_health` |
| 全天事件 | `get_all_day_events` | `physiology_records` |
| 睡眠与小睡 | `get_sleep_data` | `sleep_sessions`、`sleep_stages`、`health_samples` |
| 生活记录 | `get_lifestyle_logging_data` | `physiology_records`、`physiology_metrics` |
| HRV | `get_hrv_data` | `health_samples`、`physiology_records` |
| Body Battery | `get_body_battery`、`get_body_battery_events` | `health_samples`、`physiology_records` |
| 身体组成 | body composition、weigh-ins | `body_measurements` |
| 血压 | blood pressure range | `body_measurements`、`physiology_records` |
| 训练准备度 | `get_training_readiness` | `physiology_records`、`physiology_metrics` |
| VO₂ Max 等 | `get_max_metrics` | `physiology_records`、`physiology_metrics` |
| 乳酸阈 | historical daily lactate threshold | `physiology_records`、`physiology_metrics` |
| 训练状态 | `get_training_status` | `physiology_records`、`physiology_metrics` |
| 跑量耐受 | daily running tolerance | `physiology_records`、`physiology_metrics` |
| 耐力/爬坡分数 | precise daily endurance/hill score | `physiology_records`、`physiology_metrics` |
| 比赛预测 | daily race predictions，按接口上限分块 | `physiology_records`、`physiology_metrics` |
| 体能年龄 | `get_fitnessage_data` | `physiology_records`、`physiology_metrics` |
| 骑行 FTP | `get_cycling_ftp` | `physiology_records`、`physiology_metrics` |
| 女性健康 | menstrual day/calendar | `physiology_records`、`physiology_metrics` |
| 孕期 | pregnancy snapshot | `physiology_records`、`physiology_metrics` |
| 营养 | food log、meals、settings | `physiology_records`、`physiology_metrics` |
| 个人纪录 | personal records | `physiology_records`、`physiology_metrics` |

设备、账号、固件或地区不支持的 conditional 资源必须记录
`not_available/not_enabled/not_supported`，不能伪造成零值或成功空记录。

### 8.2 语义去重和明确排除

以下接口不重复抓取，但必须在 resource catalog 中登记理由：

- `get_stats`：`get_user_summary` 的别名。
- `get_stats_and_body`：日汇总与 body composition 的客户端组合。
- `get_stress_data`：与 `get_all_day_stress` 使用同一源端资源。
- `get_morning_training_readiness`：从完整 training readiness 结果中筛选。
- weekly steps/stress/intensity：可由日级 canonical 数据重算。
- progress summary：可由已完成活动重算。
- last activity 和 activities-for-date 包装：由统一活动 inventory 覆盖。

明确排除：

- badges、challenges、social 数据。
- goals、workout templates、scheduled workouts、training plans。
- 活动上传、编辑和删除 API。
- golf community 独立记分与社交接口；作为 Garmin activity 出现的高尔夫活动
  仍按通用活动/FIT 同步。
- device alarms 和 solar 等非健康、非已完成活动资源。

新增、删除或改变资源语义时必须升级 resource catalog 版本并触发 coverage audit。

## 9. 原始对象身份和 revision

每个抓取结果先保存原始对象，再创建 `source_revisions`。

推荐逻辑对象 ID：

```text
garmin:account:<resource_kind>
garmin:health:<resource_kind>:<local_date>
garmin:health:<resource_kind>:<start_date>:<end_date>
garmin:activity:<activity_id>:<source_role>
garmin:inventory:activities:<run_id>:<page_no>
```

规则：

- 原始 JSON 使用稳定键序列化后计算 payload hash；原始响应文件仍保存完整内容。
- 相同 provider object ID 和相同内容哈希为 no-op。
- 相同 provider object ID、内容变化时新增 revision。
- range 响应可以由同一个 raw object 支撑多个日级逻辑 revision；每个投影保存
  source path 和 payload hash。
- HTTP 成功但空数组/空对象需要按 resource spec 判定 `empty`，不能笼统当错误。
- 解析失败时原始对象和 revision 仍保留，canonical 不切换，并建立质量问题。
- 新 JSON 字段进入 `source_field_catalog`；未知字段不阻断原始归档。

## 10. Full 同步

`sync full` 的固定行为：

1. 验证 `history_start_date`、through、token 和 subject identity。
2. 抓取 account/profile/device 资源并建立 capability 基线。
3. 为每个健康资源按其 day/range 约束生成从 health-from 到 through 的工作项。
4. 活动通过 count 与分页枚举整个账号历史，再过滤 through 之后的活动。
5. 保存每个 inventory page，并按 provider activity ID 去重。
6. 对每个活动先完成 summary + FIT 核心阶段。
7. 再补齐适用的 splits、sets、zones、weather 和 gear enrichments。
8. 解析、投影、对账并更新 coverage。
9. 对完整日期推进各资源游标。
10. 生成 receipt；失败项保留为可恢复 gap。

full 是可恢复的。重新执行相同范围时，已完成且内容未变的 item 为 no-op；不会从头
覆盖数据库。full 只有在以下条件同时满足时为 `succeeded`：

- 所有 required、当前 supported 的健康工作项为 `fetched` 或 `empty`。
- conditional 资源为 fetched/empty，或具有确定的 not_available/not_enabled/
  not_supported capability。
- 所有枚举活动完成核心阶段和适用 enrichment。
- 不存在会阻断 canonical 发布的 parser、identity 或存储错误。

`forbidden`、`partial` 和 `error` 不算完整；除非未来通过显式契约将特定资源改为
`ignored_with_reason`。

## 11. Incremental 同步

`sync incremental` 默认 through 为昨天。

每个日级资源的主范围：

```text
max(history_start_date, complete_through - 13 天) ... through
```

这保证最近 14 个已结束日期被重新抓取。规则：

- 每个 resource kind 独立计算范围和游标。
- 相同内容不创建 revision；变化内容更新 current canonical。
- coverage 为 error/partial 的日期形成或保持 open gap。
- 游标只能推进到连续的 fetched/empty/确定不可用日期，不能跨越 gap。
- 日级资源主同步完成后，按优先级和 `next_retry_at_utc` 处理最多
  `max_repair_items_per_incremental` 个到期 gap。
- gap 补漏仍使用原资源 pipeline，不存在第二套简化解析逻辑。
- account/device snapshot 每次 incremental 重新取哈希；无变化为 no-op。
- 活动重新枚举 lookback 窗口内的活动，并处理未完成活动 item。
- 旧活动的全历史删除检查不放进普通 incremental，由完整 inventory audit 负责。

incremental 不包含时间安排；第五层可以在任何时间调用。

## 12. 当天 Snapshot

`sync snapshot` 默认 date 为新加坡当天。

规则：

- 所有日级 `resource_coverage.availability_state` 写为 `partial`，即使 HTTP 成功。
- snapshot 运行成功与“当天已经完成”是两个维度；receipt 的 run status 可以是
  `succeeded`，但 `coverage_state` 必须为 `partial`。
- snapshot 不推进 completed cursor。
- 相同响应重复抓取为 no-op；当天内容变化新增 revision。
- 活动 inventory 只处理当前已经上传到 Connect 的活动。
- 尚在进行、尚未从设备同步或尚未生成可下载 FIT 的活动不视为数据缺失。
- 已发现活动但 FIT 暂不可用时保存 summary，活动核心状态为 partial；后续 snapshot
  或 incremental 再补 FIT。
- snapshot 是 Connect 最近上传状态的快照，不宣称提供手表实时传感器流。

## 13. 活动同步管线

### 13.1 Inventory 和 summary

- full 先获取活动 count，再分页抓取所有活动。
- incremental/snapshot 使用日期窗口枚举，并按 activity ID 去重。
- inventory page 原样保存，用于证明枚举过程和检测分页漂移。
- 每个 activity ID 获取活动 summary；JSON 映射 `activities` 通用字段。
- 开始时间、类型和 provider ID 校验失败时不进入后续解析。

### 13.2 ORIGINAL ZIP 和 FIT

`download_activity(..., ORIGINAL)` 返回 ZIP bytes，但 ZIP 只是临时传输容器。
固定处理顺序：

1. 将响应写入与 raw 根目录同一文件系统的受控临时目录。
2. 校验最大文件大小、ZIP 结构、CRC 和成员数量。
3. 拒绝绝对路径、`..`、符号链接和目录穿越。
4. 只将允许的普通 FIT 成员提取到临时文件，每个候选文件重新计算 SHA-256。
5. FIT 通过 CRC、session 时间和活动身份校验后，原子保存到
   `raw/garmin/fit/` 并登记为原始对象。
6. 所有候选处理完成后删除临时 ZIP 和未采用的临时文件。
7. 只有已保存的有效 FIT 才进入解析。

一个 ZIP：

- 恰好一个有效 FIT：保存并作为 `activity_fit`。
- 多个有效 FIT：逐个保存；通过 session 时间和活动身份选择，无法唯一选择时建立
  `ambiguous_activity_fit` 质量问题，不发布 FIT canonical。
- 没有有效 FIT：记录失败 item，删除临时 ZIP，进入无 FIT 降级流程。
- ZIP 损坏：记录响应大小、下载时间、错误码和脱敏摘要，删除临时 ZIP，不解压、
  不发布 FIT projection，后续可以重新抓取。

### 13.3 FIT 投影

按第一层契约解析：

- session → `activities`
- record → `activity_samples`
- lap/split/set/workout step/length/interval → `activity_segments`
- field description → `fit_metric_definitions`
- device/developer identity → `devices`、`activity_devices`、
  `activity_metric_sources`
- 攀岩 active split → `climbing_routes`
- strength active set → `strength_sets`
- course point → `course_points`
- 已识别低频 message → `activity_aux_messages`
- 未识别 message → `fit_unknown_message_catalog`

标准和开发者字段进入同一 sample 时间点，但字段来源按指标和有效时间范围记录。

### 13.4 Connect enrichments

适用资源分阶段抓取：

- activity summary
- splits
- typed splits
- split summaries
- exercise sets
- HR time in zones
- power time in zones
- weather
- activity gear

每种响应都是独立 raw object/revision/source role。typed splits 和 exercise sets 可
补充或修正攀岩线路与力量组；zones、weather、gear 等低频数据先进入活动
`extras_json/source_map_json`。未建立专项表的完整值仍保留在原始 JSON。

### 13.5 无 FIT 降级

当 ORIGINAL 下载不可用、无有效 FIT 或确定不支持时：

- 保留 activity summary 和所有 Connect enrichments。
- 可以抓取 `get_activity_details` chart，写入
  `activity_samples(stream_kind=connect_chart)`。
- coverage 和活动来源明确标为 fallback/partial。
- chart 的点数限制和抽样状态进入质量信息。
- 以后取得 FIT 时新增 `activity_fit` revision，并以 FIT 替换 canonical 传感器流；
  旧 fallback 原始对象和 revision 不删除。

## 14. JSON 与 FIT 对账

沿用第一层规则：

- provider ID、名称、活动类型和服务器元数据优先 Connect JSON。
- samples、lap、split、set、developer fields 和线路细节优先 FIT。
- Garmin 后处理的距离、时长、热量、Training Effect 等两侧都保留。
- canonical 选择写入 `source_map_json`。
- 差异超过字段容差时写 `reconciliation_results` 和必要的
  `data_quality_issues`。
- `None`、字段缺失和数值零不能合并。
- 无明确结束时间时使用 start、elapsed、timer、最后 sample 和最后 segment
  交叉推导，并记录方法与置信度。

## 15. 第二层运行表

这些表的 DDL 由第一层 initializer/migration 创建，本层是唯一运行时写入者。

### 15.1 `garmin_sync_runs`

- 粒度：一次 public tool 调用。
- 关键字段：`run_id`、`invocation_id`、`mode`、请求/实际范围、
  `resource_catalog_version`、`collector_version`、`garminconnect_version`、
  `parser_version`、`status`、各类计数、`next_retry_at_utc`、开始/完成时间。
- `invocation_id` 非空时唯一；第五层重复提交同一 invocation 不创建第二次业务运行。
- error summary 必须脱敏，不保存完整响应。

### 15.2 `garmin_sync_items`

- 粒度：某 run 中一个逻辑对象的一个 pipeline stage。
- 关键字段：`run_id`、`resource_kind`、`logical_object_key`、`stage`、
  `status`、`attempt_count`、`http_status`、`error_code`、`error_summary`、
  `next_retry_at_utc`、`source_revision_id`、开始/完成时间。
- `stage`：`discover`、`fetch`、`archive`、`extract`、`parse`、`project`、
  `reconcile`、`validate`。
- 唯一键：`(run_id, resource_kind, logical_object_key, stage)`。

### 15.3 `garmin_sync_cursors`

- 粒度：一个 subject 和 resource kind 的同步游标。
- 关键字段：`subject_id`、`resource_kind`、`complete_through_local_date`、
  `last_success_at_utc`、`last_run_id`、`catalog_version`。
- cursor 只代表连续完整范围，不代表最后一次尝试日期。

### 15.4 `garmin_sync_gaps`

- 粒度：一个待补齐的日期窗口、activity ID 或 pipeline stage。
- 关键字段：`subject_id`、`resource_kind`、逻辑对象、日期范围、`reason_code`、
  `status`、`priority`、`attempt_count`、`next_retry_at_utc`、
  `first_seen_at_utc`、`last_attempt_at_utc`、`resolved_at_utc`。
- 状态：`open`、`deferred`、`resolved`、`ignored_with_reason`。
- 同一未解决逻辑缺口不得重复插入。

### 15.5 `garmin_resource_capabilities`

- 粒度：一个 subject、设备/账号环境和 resource kind 的能力结论。
- 关键字段：`subject_id`、`resource_kind`、`capability_state`、理由、
  `first_checked_at_utc`、`last_checked_at_utc`、`next_probe_at_utc`、
  `source_revision_id`。
- 状态：`supported`、`not_enabled`、`not_available`、`not_supported`、
  `forbidden`、`unknown`。
- capability 是运行优化缓存；日级事实仍必须写入第一层 `resource_coverage`。

## 16. 幂等、游标和缺口

### 16.1 幂等

- raw SHA-256 相同：不重复存文件。
- provider logical object 与 payload hash 相同：不新增 revision。
- canonical 投影只在 active revision 或来源选择变化时更新。
- 同一个 run item 完成后重试不会重复生成 segment/sample。
- 同一 `invocation_id` 的重复第五层调用返回已有或恢复后的 receipt。

### 16.2 游标

- 每种日级资源独立游标。
- fetched、empty、not_enabled、not_available 和 not_supported 可以闭合日期。
- partial、error、forbidden 和 deferred 不能闭合日期。
- cursor 推进前必须扫描从旧 cursor 下一天到候选日期的连续 coverage。
- snapshot 永不推进 cursor。

### 16.3 缺口

缺口来源：

- 请求失败或长时间 deferred。
- HTTP 成功但响应结构不完整。
- 原始文件损坏或 FIT CRC 失败。
- parser/schema drift。
- 日期 coverage 缺失。
- 活动已发现但 summary、FIT 或 required enrichment 未完成。
- JSON/FIT 对账阻断。

缺口解决后保留历史记录并标记 resolved，不物理删除。

## 17. 重试和错误分类

创建 `Garmin` client 时设置 `retry_attempts=0`，由本层在逻辑 item 层统一重试。

### 17.1 可重试错误

- 网络连接失败、DNS、连接重置、超时。
- HTTP 408。
- HTTP 500、502、503、504 和其他明确临时 5xx。

策略：

- 最多 `max_attempts=5`。
- 指数退避从 2 秒开始，上限 60 秒，并加入随机抖动。
- 每次尝试写入同一 sync item 的 attempt 计数。

### 17.2 429

- 优先解析 `Retry-After`。
- 等待时间不超过 120 秒时，可以在本次调用内等待并重试。
- 超过 120 秒时不阻塞；写入 gap、capability/run 的
  `next_retry_at_utc`，本次返回 deferred/partial。
- 没有 Retry-After 时使用 900 秒首个冷却，后续按失败次数增长并设置上限。
- 冷却未到期时不得再次调用该 resource。

### 17.3 认证和 4xx

- client 自动 refresh 后仍 401：`auth_required`，停止新的网络工作。
- 403：`forbidden`；不重试、不伪装 not_available。
- 对 resource spec 明确允许的 404：`not_available`。
- 其他 4xx：永久 item failure，等待人工或版本修复。
- 解析器不得仅凭错误文本中的“no data”把认证或服务错误判为空。

### 17.4 非网络错误

- 磁盘、权限、数据库完整性和 subject identity mismatch 是 run 级阻断错误。
- 单个 JSON schema drift、临时 ZIP、FIT 或 projection 错误是 item 级错误；
  保留其他 item 的进展。
- 错误日志只保存类型、resource、逻辑键和脱敏摘要。

## 18. 原子性、锁和并发

- 所有 public tools 共用一个 Garmin 采集单写锁。
- 获取锁失败立即返回 `lock_busy`；不无限等待。
- 锁文件位于受控 state 目录，记录 PID、run ID 和开始时间。
- 判断陈旧锁必须同时验证持有进程，不得只按时间删除。
- 网络请求和解析在事务外进行。
- 文件先写同目录临时文件，校验、fsync 后原子重命名。
- 每个 item 使用短事务写 raw metadata、revision、projection、coverage 和状态。
- active revision 切换与 canonical 更新必须在同一事务。
- 进程崩溃后，processing item 在下一次调用中恢复或重置为 open gap。

## 19. Repair、Reparse、Reconcile 和 Audit

### 19.1 `repair --strategy auto`

根据 gap reason 选择：

- 没有原始对象或网络错误 → refetch。
- 原始对象有效但 parser/project 失败 → reparse。
- JSON/FIT 都存在但 canonical 冲突 → reconcile。
- capability 冷却未到期 → deferred，不强行请求。

### 19.2 `refetch`

- 重新调用指定 resource/date/activity。
- 相同内容为 no-op；变化内容新增 revision。
- 不删除失败 revision 或旧 raw object。

### 19.3 `reparse`

- 完全离线读取指定 raw object。
- 使用当前 parser/profile/catalog 生成影子投影。
- 通过验证后原子切换 current；失败不影响旧 canonical。

### 19.4 `reconcile`

- 不重新下载。
- 重新计算来源优先级、字段容差、结束时间和 source map。
- 生成新的 reconciliation result；只有规则版本或选择变化才更新 canonical。

### 19.5 `audit`

audit 可以读取 Garmin inventory 和本地数据库，但不修改原始健康事实。它负责：

- 扫描 resource coverage 连续性。
- 检查 cursor 是否跨过 gap。
- 比较活动 count、provider ID 集合和本地 active activities。
- 发现未完成活动 stage。
- 检查 raw JSON/FIT 文件存在性和哈希，并在抓取阶段检查临时 ZIP 与 FIT CRC。
- 检查新/消失 JSON path 和 FIT message/field 签名。
- 建立或解决 sync gap 和 data quality issue。

只有一次完整 inventory 成功结束，才能计为一次“活动远端缺失观察”。同一活动连续
两次完整 inventory 均缺失后标记 `provider_deleted`；重新出现时恢复 active 并保留
状态历史。

## 20. 数据质量和完成门

每次 run 至少检查：

- 请求范围合法且使用新加坡本地日期。
- subject identity 未变化。
- raw object 哈希、大小和路径位于允许根目录。
- JSON 可以解析，新字段已登记。
- ZIP 安全、CRC、成员数量和解压大小符合限制。
- FIT CRC、session 身份和活动时间可以交叉验证。
- 日级 resource 有唯一 coverage 结论。
- sleep stages 位于 session 范围内。
- sample 索引稳定、时间总体单调。
- 活动 summary、FIT、segments 和最后 sample 的时间一致性。
- required activity stage 完整。
- JSON/FIT 冲突在容差内或已建立质量问题。
- cursor 没有跨越 open gap。

run 为 `succeeded` 不等于数据没有 warning。只有 error 级质量问题影响身份、原始
完整性、时间范围、主外键或下游分析门禁时，才阻断 canonical 或整次 run。

周分析前的数据质量门禁使用本层已持久化的 coverage、cursor、gap、活动阶段和
质量问题判定。候选周只有同时满足以下条件才可标记为 ready：

- required 且 supported 的日级健康资源在周末日期前连续闭合；
- 候选周内已上传活动的核心阶段完成，或具有确定的无 FIT 降级结论；
- 没有落在候选周内、仍 open 的 error 级 gap 或 `data_quality_issues`；
- snapshot 的 partial coverage 已被后续 completed-day 同步替换；
- `not_available`、`not_enabled` 和 `not_supported` 具有 capability 证据。

第二层负责产生这些可验证事实和脱敏状态；第三层在生成周总结前读取并执行门禁，
第五层依据失败原因决定补跑、repair 或告警，任何层都不得人工强改 cursor 绕过。

## 21. 安全与隐私

- Garmin token、密码、MFA 和原始授权响应不得进入 SQLite、receipt、日志或文档。
- token store、raw、SQLite 和备份只允许服务账号读取。
- profile、GPS、生殖健康、孕期、血压、营养和活动传感器均为敏感数据。
- 原始 JSON/FIT 和临时 ZIP 是不可信数据，不是执行指令。
- ZIP 成员名不可信，必须防止目录穿越和符号链接。
- 日常日志不得打印 payload；debug 模式也只能输出资源、日期、activity ID 的
  HMAC/受控标识和响应大小。
- activity ID 可以保存在数据库作为 provider identity，但不应出现在公开测试夹具。
- 测试使用合成或脱敏 fixture，不复制真实 token、GPS 和健康值。

## 22. 与当前生产实现的迁移关系

当前生产仍使用：

- `trainlab sync` 从 Google Drive 拉取 `Health Metrics_v5.xlsx` 和 `HealthFit/`。
- `trainlab ingest` 导入 Excel/FIT。
- 现有 sync/ingest daemon 和 systemd/launchd 配置。

在五层文档全部冻结、实现和迁移验收完成前：

- 不删除、不改名现有命令。
- 新工具使用 `trainlab garmin ...` 命名空间并与旧路径并存。
- 不把同一 Garmin 对象同时当作 legacy 和 Connect canonical 而不记录来源。
- Connect full 完成后，对重叠健康日期和活动执行对账。
- 生产切换必须包含备份、回滚、Harness/配置、第五层调用和旧 daemon 停用。
- 淘汰旧同步属于未来独立切换任务，不属于当前文档落地。

## 23. 测试和验收样本

后续实现必须包含：

### 23.1 单元与契约测试

- 每个独立健康资源族的脱敏 fixture。
- empty、not_enabled、not_available、forbidden、schema drift。
- resource catalog 语义去重和 ignored reason。
- `SyncRequest`/`SyncReceipt` Schema 和 CLI 参数。
- 身份匹配、token 权限和日志脱敏。

### 23.2 原始文件与活动

- 现有六类代表性 FIT：跑步、抱石、室内攀岩、徒步、骑行、力量。
- ZIP Slip、绝对路径、符号链接、损坏 ZIP、CRC 错误、多个 FIT、无 FIT。
- developer fields、typed splits、exercise sets、zones、weather、gear。
- Connect chart 降级与后续 FIT 替换。

### 23.3 幂等、revision 和模式

- 相同响应重跑 no-op。
- Garmin 历史修正生成 revision 并更新 current。
- full 中断后续跑。
- incremental 重拉 14 天和限额补漏。
- 各资源游标独立且不跨 gap。
- snapshot 不推进游标；同日变化新增 revision。
- 活动上传后再次 snapshot 补齐 FIT。

### 23.4 故障与恢复

- 网络、超时、5xx 指数退避。
- 短 429 当前调用内恢复。
- 长 429 返回 deferred 并尊重 next retry。
- 401、403、允许/不允许的 404。
- 原子写中断、SQLite 事务失败、parser 崩溃和陈旧 processing item。
- 并发调用返回 lock_busy。

### 23.5 端到端验收

- 在受控真实账号上运行短日期窗口，不记录真实 payload 到测试输出。
- 立即以相同范围重跑并确认 no-op。
- 对代表性活动验证 summary、FIT、segments、samples 和 enrichments，并确认
  临时 ZIP 不会长期保留。
- 对一个不支持的健康资源验证 capability/coverage 状态。
- 工具退出后验证无 daemon、后台线程、timer 或监听端口。
- 第五层可以仅依据 receipt、运行表和 exit code 安全决定重试或告警。

## 24. 完成定义

第二层只有同时满足以下条件才从“已冻结”进入“已验证”：

1. Python API、CLI 和 receipt Schema 实现且语义一致。
2. 所有工具一次性退出，没有任何内置调度或 daemon。
3. 锁定 Python `>=3.12` 和 `garminconnect==0.3.6`，依赖与认证路径验证通过。
4. resource catalog 覆盖本文全部独立生理资源和活动附属资源，重复/排除项有理由。
5. full、incremental、snapshot、repair、audit 和 status 均通过契约测试。
6. 健康 `history_start_date`、昨天完成日和今天 partial snapshot 语义正确。
7. 原始 JSON 和 FIT 使用临时文件、校验和原子重命名；下载 ZIP 只在受控临时
   目录存在，处理完成后删除。
8. 活动远端状态和 source roles 符合第一层 v2.4。
9. 六类代表性 FIT 和 Connect enrichments 可以无损归档并生成预期投影。
10. 相同内容幂等，变化内容新增 revision，parser 升级可以离线重建。
11. 14 天重拉、逐资源游标、gap 队列和限额自动补漏工作正确。
12. 网络、5xx、429、401、403、404、损坏文件和进程中断可以确定性恢复或报告。
13. 云端活动缺失不会删除本地数据，两次完整 inventory 才确认 provider deleted。
14. receipt、日志、测试输出和数据库运行表不泄露凭据或完整健康 payload。
15. 与 legacy 数据的重叠对账、备份、回滚和未来切换路径通过验收。

## 25. 对其他层的固定接口

- 第一层 initializer/migration 创建本层声明的运行表；本层是这些表的唯一运行时
  写入者。
- 第三层只读取第一层稳定 canonical 视图和质量门禁，不直接调用 Garmin。
- 第四层不调用或修改 Garmin 采集状态。
- 第五层负责调度 CLI、传入 invocation ID、读取 receipt/exit code、观察
  `garmin_sync_runs`、cursor、gap 和 `next_retry_at_utc`。
- 第五层可以触发 repair/audit，但不得直接修改 Garmin canonical、cursor 或 gap。
- 本层不向其他层承诺 Garmin 私有 endpoint 形状；稳定边界是第一层视图、
  `SyncRequest`、`SyncReceipt` 和运行表。
