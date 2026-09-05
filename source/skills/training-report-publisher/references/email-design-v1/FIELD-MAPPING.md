# TrainLab 邮件字段映射

> 覆盖范围：日报、周报、课程、指标、证据、趋势、扩展模块与可选图表数据。
> 规则：AI 教练结论、降级规则和停止条件原文直出；审计字段只进入底部“数据与证据”。

## 命名空间约定

- 日报 AI 教练对象暂按 `coach.*` 绑定；若真实 Schema 使用 `ai_coach.*`，仅替换路径前缀，不改变组件或显示规则。
- 同名根字段（如 `schema_version`、`status`、`summary`）按邮件类型分别绑定。
- `extra_sections[].custom` 只允许开发白名单渲染，未知类型降级为文本或隐藏。
- 所有缺失值不得替换为 0；不能确认单位时不得自行换算。

## 全字段清单

| JSON 路径 | 所属日报或周报 | 对应 UI 组件 | 显示名称 | 格式化规则 | 单位转换 | 没有数据时的行为 | 显示优先级 | 审计信息 |
|---|---|---|---|---|---|---|---|---|
| `schema_version` | 日报 | EvidenceFooter | Schema | 原字符串 | 不转换；保留原字段语义 | 显示“未提供” | 审计 | 是 |
| `status` | 日报 | SafetyHero | 报告状态 | `succeeded`→已完成；`blocked`→已阻断，同时保留英文值 | 不转换；保留原字段语义 | 缺失按阻断处理 | 主 | 否 |
| `error_code` | 日报 | SafetyHero＋EvidenceFooter | 错误代码 | 原值；仅 blocked 时前置 | 不转换；保留原字段语义 | 非 blocked 隐藏；blocked 缺失显示“未提供错误代码” | 主/审计 | 是 |
| `report_date` | 日报 | EmailHeader | 报告日期 | `YYYY-MM-DD` | 不转换；保留原字段语义 | 标题中保留日期占位并标记生成异常 | 主 | 否 |
| `review_date` | 日报 | EvidenceFooter | 复核日期 | `YYYY-MM-DD` | 不转换；保留原字段语义 | 隐藏该行 | 审计 | 是 |
| `sleep_wake_date` | 日报 | SleepCard | 睡眠归属日 | `YYYY-MM-DD` | 不转换；保留原字段语义 | 隐藏该行 | 次 | 否 |
| `safety` | 日报 | SafetyHero | 今日状态 | ready/caution/blocked＋中文文本 | 不转换；保留原字段语义 | 缺失按 caution 呈现并标记未知 | 主 | 否 |
| `summary` | 日报 | SafetyHero | 今日摘要 | 原文，不改写 | 不转换；保留原字段语义 | 显示“本次未生成摘要” | 主 | 否 |
| `provider_calls` | 日报 | EvidenceFooter | 数据调用 | 次数或来源列表；不展示凭据 | 不转换；保留原字段语义 | 空数组显示“无外部调用记录” | 审计 | 是 |
| `coach.summary` | 日报 | CoachSummary | AI 教练结论 | 原文逐字呈现 | 不转换；保留原字段语义 | 隐藏组件并写入 DataGapNotice | 主 | 否 |
| `coach.stop_conditions[]` | 日报 | CoachSummary | 停止条件 | 一项一行，保留原文顺序 | 不转换；保留原字段语义 | 空数组显示“未提供停止条件” | 主 | 否 |
| `coach.today_course` | 日报 | CourseCard | 今日课程 | 对象 | 不转换；保留原字段语义 | 缺失显示“今日未安排课程” | 主 | 否 |
| `coach.recent_trend_sha256` | 日报 | EvidenceFooter | 趋势摘要哈希 | 正文截断 8+8 字符；完整值可换行 | 不转换；保留原字段语义 | 隐藏该行 | 审计 | 是 |
| `coach.today_course.date` | 日报 | CourseCard | 日期 | `M月D日 周X` | 不转换；保留原字段语义 | 使用 `report_date`，仍无则隐藏 | 主 | 否 |
| `coach.today_course.activity_kind` | 日报 | CourseCard | 类型 | running→跑步；climbing→攀岩；rest→休息 | 不转换；保留原字段语义 | 显示“类型未知”并用中性色 | 主 | 否 |
| `coach.today_course.name` | 日报 | CourseCard | 课程名称 | 原文 | 不转换；保留原字段语义 | 显示“未命名课程” | 主 | 否 |
| `coach.today_course.purpose` | 日报 | CourseCard | 课程目的 | 原文 | 不转换；保留原字段语义 | 隐藏该行 | 主 | 否 |
| `coach.today_course.load_level` | 日报 | CourseCard | 负荷 | low/moderate/hard＋中文文字 | 不转换；保留原字段语义 | 缺失显示“负荷未标注” | 主 | 否 |
| `coach.today_course.distance_km` | 日报 | CourseCard | 距离 | 1 位小数 `km` | 统一为 km | 不显示距离单元 | 主 | 否 |
| `coach.today_course.duration_minutes` | 日报 | CourseCard | 时长 | 整数 `分钟`；≥60 可显示 `X小时Y分` | 分钟；≥60 可转 X小时Y分 | 不显示时长单元 | 主 | 否 |
| `coach.today_course.pace_min_seconds_per_km` | 日报 | CourseCard | 配速下界 | `m:ss/km` | 秒/公里 → m:ss/km | 两端任一缺失时显示已知端点，不编范围 | 次 | 否 |
| `coach.today_course.pace_max_seconds_per_km` | 日报 | CourseCard | 配速上界 | `m:ss/km` | 秒/公里 → m:ss/km | 同上 | 次 | 否 |
| `coach.today_course.heart_rate_min_bpm` | 日报 | CourseCard | 心率下界 | 整数 `bpm` | 统一为 bpm | 两端任一缺失时显示已知端点 | 次 | 否 |
| `coach.today_course.heart_rate_max_bpm` | 日报 | CourseCard | 心率上界 | 整数 `bpm` | 统一为 bpm | 同上 | 次 | 否 |
| `coach.today_course.rpe` | 日报 | CourseCard | 主观强度 | `RPE n/10` | 不转换；保留原字段语义 | 隐藏该项 | 主 | 否 |
| `coach.today_course.steps[]` | 日报 | CourseCard | 课程步骤 | 按原顺序编号 | 不转换；保留原字段语义 | 空数组隐藏步骤区 | 主 | 否 |
| `coach.today_course.steps[].name` | 日报 | CourseCard | 步骤名称 | 原文 | 不转换；保留原字段语义 | 显示“未命名步骤” | 主 | 否 |
| `coach.today_course.steps[].end_condition` | 日报 | CourseCard | 结束条件 | 原文 | 不转换；保留原字段语义 | 隐藏该行 | 主 | 否 |
| `coach.today_course.downgrade_rule` | 日报 | CourseCard | 降级规则 | 原文，不改写 | 不转换；保留原字段语义 | 显示“未提供降级规则” | 主 | 否 |
| `coach.today_course.stop_conditions[]` | 日报 | CourseCard | 停止条件 | 一项一行，原文 | 不转换；保留原字段语义 | 空数组显示“未提供停止条件” | 主 | 否 |
| `coach.today_course.garmin_mapping_status` | 日报 | CourseCard | Garmin 状态 | 原枚举＋中文说明 | 不转换；保留原字段语义 | 隐藏该行 | 次 | 否 |
| `bounded_metrics[]` | 日报 | MetricGrid | 指标集合 | 按资源类别分组 | 不转换；保留原字段语义 | 空数组隐藏 MetricGrid | 次 | 否 |
| `bounded_metrics[].name` | 日报 | MetricGrid | 指标名称 | 原名映射中文标签 | 不转换；保留原字段语义 | 无名称则不渲染该项 | 次 | 否 |
| `bounded_metrics[].value` | 日报 | MetricGrid | 指标值 | 依 `unit` 格式化 | 不转换；保留原字段语义 | `null` 显示“暂无数据” | 次 | 否 |
| `bounded_metrics[].unit` | 日报 | MetricGrid | 单位 | 统一到约定展示单位 | 不转换；保留原字段语义 | 缺失时不猜单位 | 次 | 否 |
| `bounded_metrics[].evidence_ref` | 日报 | EvidenceFooter | 证据引用 | ID 或索引 | 不转换；保留原字段语义 | 缺失时指标仍可显示，但标记“无证据引用” | 审计 | 是 |
| `bounded_metrics[].resource` | 日报 | EvidenceFooter | 资源 | 原枚举或来源名 | 不转换；保留原字段语义 | 隐藏该行 | 审计 | 是 |
| `bounded_metrics[].metric` | 日报 | MetricGrid | 指标键 | 映射为中文显示名 | 不转换；保留原字段语义 | 无映射时保留技术键于证据区 | 次/审计 | 否 |
| `bounded_metrics[].count` | 日报 | MetricGrid | 样本数 | 整数 `次` | 整数计数，不换算 | 隐藏 | 次 | 否 |
| `bounded_metrics[].minimum` | 日报 | MetricGrid | 最小值 | 跟随指标单位 | 不转换；保留原字段语义 | 隐藏 | 次 | 否 |
| `bounded_metrics[].maximum` | 日报 | MetricGrid | 最大值 | 跟随指标单位 | 不转换；保留原字段语义 | 隐藏 | 次 | 否 |
| `bounded_metrics[].average` | 日报 | MetricGrid | 平均值 | 合理小数位＋单位 | 不转换；保留原字段语义 | 隐藏 | 次 | 否 |
| `bounded_metrics[].median` | 日报 | MetricGrid | 中位数 | 合理小数位＋单位 | 不转换；保留原字段语义 | 隐藏 | 次 | 否 |
| `bounded_metrics[].aggregate` | 日报 | MetricGrid | 汇总值 | 依指标定义 | 不转换；保留原字段语义 | 无定义时仅在证据区展示原值 | 次 | 否 |
| `bounded_metrics[].duration_seconds` | 日报 | ActivitySnapshot/SleepCard | 时长 | 转 `X小时Y分` 或 `Y分Z秒` | 秒 → 小时/分钟/秒 | 隐藏 | 次 | 否 |
| `bounded_metrics[].sleep_start` | 日报 | SleepCard | 入睡时间 | `HH:mm`＋必要时日期 | 不转换；保留原字段语义 | 隐藏 | 次 | 否 |
| `bounded_metrics[].sleep_end` | 日报 | SleepCard | 醒来时间 | `HH:mm`＋必要时日期 | 不转换；保留原字段语义 | 隐藏 | 次 | 否 |
| `bounded_metrics[].sleep_wake_date` | 日报 | SleepCard | 醒来归属日 | `YYYY-MM-DD` | 不转换；保留原字段语义 | 隐藏 | 次 | 否 |
| `bounded_metrics[].stage_group_count` | 日报 | SleepCard | 睡眠阶段组数 | 整数 `组` | 整数计数，不换算 | 不生成阶段图 | 次 | 否 |
| `bounded_metrics[].completeness` | 日报 | SleepCard | 完整性 | 百分比或 verified/incomplete＋文字 | 0–1 转百分比；百分数原值保留 | 缺失显示“完整性未知” | 主 | 否 |
| `bounded_metrics[].trackpoint_count` | 日报 | EvidenceFooter | 轨迹点数 | 整数 `点`；不展示坐标 | 整数计数，不换算 | 隐藏 | 审计 | 是 |
| `bounded_metrics[].time_point_count` | 日报 | EvidenceFooter | 时间点数 | 整数 `点` | 整数计数，不换算 | 隐藏 | 审计 | 是 |
| `bounded_metrics[].sample_count` | 日报 | EvidenceFooter | 样本数 | 整数 `个` | 整数计数，不换算 | 隐藏 | 审计 | 是 |
| `bounded_metrics[].distance_km` | 日报 | ActivitySnapshot | 距离 | 2 位以内 `km` | 统一为 km | 隐藏 | 主 | 否 |
| `bounded_metrics[].duration_available` | 日报 | ActivitySnapshot | 时长可用性 | 是/否＋文字 | 不转换；保留原字段语义 | `false` 时不显示推算时长 | 次 | 否 |
| `bounded_metrics[].activity_kind` | 日报 | ActivitySnapshot | 运动类型 | running/climbing/rest 映射中文 | 不转换；保留原字段语义 | 未知用中性色 | 主 | 否 |
| `bounded_metrics[].pace_seconds_per_km` | 日报 | ActivitySnapshot | 平均配速 | `m:ss/km` | 秒/公里 → m:ss/km | 隐藏 | 主 | 否 |
| `bounded_metrics[].heart_rate_average` | 日报 | ActivitySnapshot/RecoveryCard | 平均心率 | 整数 `bpm` | 统一为 bpm | 隐藏 | 主 | 否 |
| `bounded_metrics[].heart_rate_maximum` | 日报 | ActivitySnapshot | 最高心率 | 整数 `bpm` | 统一为 bpm | 隐藏 | 主 | 否 |
| `bounded_metrics[].resting_heart_rate_bpm` | 日报 | RecoveryCard | 静息心率 | 整数 `bpm` | 统一为 bpm | 显示“暂无数据” | 主 | 否 |
| `bounded_metrics[].last_night_average` | 日报 | RecoveryCard | 昨夜平均 | 依指标单位 | 依指标原单位；HRV 使用 ms | 隐藏 | 次 | 否 |
| `bounded_metrics[].weekly_average` | 日报 | RecoveryCard | 周平均 | 依指标单位 | 依指标原单位；HRV 使用 ms | 隐藏 | 次 | 否 |
| `bounded_metrics[].last_night_5_min_high` | 日报 | RecoveryCard | 昨夜 5 分钟高值 | 依指标单位 | 依指标原单位；HRV 使用 ms | 隐藏 | 次 | 否 |
| `bounded_metrics[].vo2_max` | 日报 | RecoveryCard | VO₂ Max | 1 位小数 `ml/kg/min` | ml/kg/min | 显示“暂无数据” | 次 | 否 |
| `bounded_metrics[].weight` | 日报 | MetricGrid | 体重 | 1 位小数；按 `unit` 转 kg | 按原 unit 转 kg | 隐藏 | 次 | 否 |
| `bounded_metrics[].temperature` | 日报 | MetricGrid | 温度 | 1 位小数 `°C`；仅在单位可确认时转换 | 确认原单位后转 °C | 隐藏 | 次 | 否 |
| `bounded_metrics[].humidity` | 日报 | MetricGrid | 湿度 | 整数 `%` | 统一为 % | 隐藏 | 次 | 否 |
| `bounded_metrics[].wind_speed` | 日报 | MetricGrid | 风速 | 1 位小数；按单位转 `m/s` | 确认原单位后转 m/s | 隐藏 | 次 | 否 |
| `bounded_metrics[].units` | 日报 | EvidenceFooter | 原始单位集合 | 原对象或列表 | 不转换；保留原字段语义 | 隐藏 | 审计 | 是 |
| `bounded_metrics[].lap_count` | 日报 | ActivitySnapshot | 圈数 | 整数 `圈` | 整数计数，不换算 | 隐藏 | 次 | 否 |
| `bounded_metrics[].uncertainty` | 日报 | DataGapNotice | 不确定性 | 原文或百分比＋“存在不确定性” | 不转换；保留原字段语义 | 隐藏 | 主 | 否 |
| `bounded_metrics[].source_name` | 日报 | EvidenceFooter | 来源 | 来源显示名 | 不转换；保留原字段语义 | 显示“来源未标注” | 审计 | 是 |
| `bounded_metrics[].field_counts` | 日报 | EvidenceFooter | 字段计数 | 键值表 | 整数计数，不换算 | 隐藏 | 审计 | 是 |
| `bounded_metrics[].raw_file_id` | 日报 | EvidenceFooter | 原始文件 ID | 原值，允许断行 | 不转换；保留原字段语义 | 隐藏 | 审计 | 是 |
| `bounded_metrics[].sha256` | 日报 | EvidenceFooter | 文件哈希 | 截断展示＋完整值 | 不转换；保留原字段语义 | 隐藏 | 审计 | 是 |
| `bounded_metrics[].data_date` | 日报 | EvidenceFooter | 数据日期 | `YYYY-MM-DD` | 不转换；保留原字段语义 | 隐藏 | 审计 | 是 |
| `bounded_metrics[].format` | 日报 | EvidenceFooter | 文件格式 | `json/fit/gpx/tcx` 大写展示 | 不转换；保留原字段语义 | 隐藏 | 审计 | 是 |
| `evidence_file_count` | 日报 | EvidenceFooter | 证据文件数 | 整数 `个` | 整数计数，不换算 | 显示 0，并明确无证据文件 | 审计 | 是 |
| `evidence_resources[]` | 日报 | EvidenceFooter | 证据资源 | 一项一行 | 不转换；保留原字段语义 | 空数组显示“无可用资源” | 审计 | 是 |
| `history_daily_sha256[]` | 日报 | EvidenceFooter | 历史日报哈希 | 日期对齐，截断＋完整值 | 不转换；保留原字段语义 | 空数组隐藏 | 审计 | 是 |
| `history_daily_dates[]` | 日报 | EvidenceFooter | 历史日报日期 | `YYYY-MM-DD` | 不转换；保留原字段语义 | 空数组隐藏 | 审计 | 是 |
| `evidence_refs[]` | 日报 | EvidenceFooter | 证据引用 | 一项一行 | 不转换；保留原字段语义 | 空数组显示“无证据引用” | 审计 | 是 |
| `evidence_refs[].raw_file_id` | 日报 | EvidenceFooter | 文件 ID | 原值 | 不转换；保留原字段语义 | 显示“未提供” | 审计 | 是 |
| `evidence_refs[].sha256` | 日报 | EvidenceFooter | SHA-256 | 截断＋完整值 | 不转换；保留原字段语义 | 显示“未提供” | 审计 | 是 |
| `evidence_refs[].claim` | 日报 | EvidenceFooter | 支持结论 | 原文，不改写 | 不转换；保留原字段语义 | 显示“未说明支持结论” | 审计 | 是 |
| `recent_14_days.days_available` | 日报 | TrendSummary | 可用天数 | `n/14 天` | 整数计数，不换算 | 0 时隐藏趋势区 | 主 | 否 |
| `recent_14_days.sleep.average_hours` | 日报 | TrendSummary | 平均睡眠 | 1 位小数 `小时` | 统一为小时，保留 1 位小数 | 隐藏指标 | 主 | 否 |
| `recent_14_days.sleep.insufficient_days` | 日报 | TrendSummary | 睡眠不足天数 | 整数 `天` | 整数计数，不换算 | 隐藏指标 | 主 | 否 |
| `recent_14_days.sleep.consecutive_insufficient_days` | 日报 | TrendSummary | 连续不足 | 整数 `天` | 整数计数，不换算 | 隐藏指标 | 主 | 否 |
| `recent_14_days.recovery.caution_days` | 日报 | TrendSummary | 恢复警告天数 | 整数 `天` | 整数计数，不换算 | 隐藏指标 | 主 | 否 |
| `recent_14_days.recovery.rhr_average` | 日报 | TrendSummary | 平均 RHR | 整数 `bpm` | 统一为 bpm | 隐藏指标 | 次 | 否 |
| `recent_14_days.recovery.rhr_change` | 日报 | TrendSummary | RHR 变化 | 带正负号 `bpm`；不自动解释好坏 | 统一为 bpm | 隐藏指标 | 主 | 否 |
| `recent_14_days.recovery.hrv_average` | 日报 | TrendSummary | 平均 HRV | 整数 `ms` | 依指标原单位；HRV 使用 ms | 隐藏指标 | 次 | 否 |
| `recent_14_days.recovery.hrv_change` | 日报 | TrendSummary | HRV 变化 | 带正负号 `ms`；不自动解释好坏 | 依指标原单位；HRV 使用 ms | 隐藏指标 | 主 | 否 |
| `recent_14_days.running.distance_km` | 日报 | TrendSummary | 跑步距离 | 1 位小数 `km` | 统一为 km | 隐藏指标 | 主 | 否 |
| `recent_14_days.running.activity_count` | 日报 | TrendSummary | 跑步次数 | 整数 `次` | 整数计数，不换算 | 隐藏指标 | 次 | 否 |
| `recent_14_days.running.activity_days` | 日报 | TrendSummary | 跑步天数 | 整数 `天` | 整数计数，不换算 | 隐藏指标 | 次 | 否 |
| `recent_14_days.data_gaps[]` | 日报 | DataGapNotice | 数据缺口 | 一项一行 | 整数计数，不换算 | 空数组隐藏 | 主 | 否 |
| `recent_14_days.sha256` | 日报 | EvidenceFooter | 14 天趋势哈希 | 截断＋完整值 | 整数计数，不换算 | 隐藏 | 审计 | 是 |
| `schema_version` | 周报 | EvidenceFooter | Schema | 原字符串 | 不转换；保留原字段语义 | 显示“未提供” | 审计 | 是 |
| `status` | 周报 | WeeklyDecisionHero | 报告状态 | succeeded/blocked＋中文文本 | 不转换；保留原字段语义 | 缺失按 blocked | 主 | 否 |
| `error_code` | 周报 | WeeklyDecisionHero＋EvidenceFooter | 错误代码 | 原值 | 不转换；保留原字段语义 | 非 blocked 隐藏 | 主/审计 | 是 |
| `period` | 周报 | EmailHeader | 周期 | `YYYY-MM-DD~YYYY-MM-DD` | 不转换；保留原字段语义 | 标题保留周期占位并标记异常 | 主 | 否 |
| `summary` | 周报 | WeeklyDecisionHero | 本周总结 | 原文，不改写 | 不转换；保留原字段语义 | 显示“本次未生成周总结” | 主 | 否 |
| `provider_calls` | 周报 | EvidenceFooter | 数据调用 | 次数或来源列表；不含凭据 | 不转换；保留原字段语义 | 空数组显示“无外部调用记录” | 审计 | 是 |
| `goal_sha256` | 周报 | EvidenceFooter | 目标哈希 | 截断＋完整值 | 不转换；保留原字段语义 | 隐藏 | 审计 | 是 |
| `daily_count` | 周报 | WeeklyKPI | 日报输入数 | `n/7 份` | 整数计数，不换算 | 显示 0/7 并标记不完整 | 主 | 否 |
| `daily_summary_count` | 周报 | WeeklyKPI | 有效日报数 | `n/7 份` | 整数计数，不换算 | 显示 0/7 | 主 | 否 |
| `daily_input_sha256[]` | 周报 | EvidenceFooter | 日报输入哈希 | 与日期/序号对齐 | 不转换；保留原字段语义 | 空数组显示“无日报输入哈希” | 审计 | 是 |
| `review_output_id` | 周报 | EvidenceFooter | 周复盘输出 ID | 原值 | 不转换；保留原字段语义 | 隐藏 | 审计 | 是 |
| `activity_days` | 周报 | WeeklyKPI | 活动天数 | 整数 `天` | 整数计数，不换算 | 显示“暂无数据” | 主 | 否 |
| `sleep_complete_days` | 周报 | WeeklyKPI | 睡眠完整天数 | 整数 `天` | 整数计数，不换算 | 显示“暂无数据” | 主 | 否 |
| `evidence_consistency` | 周报 | WeeklyDecisionHero | 证据一致性 | verified/blocked＋中文文字 | 不转换；保留原字段语义 | 缺失显示“未验证” | 主 | 否 |
| `evidence_refs[]` | 周报 | EvidenceFooter | 证据引用 | 一项一行 | 不转换；保留原字段语义 | 空数组显示“无证据引用” | 审计 | 是 |
| `evidence_refs[].output_id` | 周报 | EvidenceFooter | 输出 ID | 原值 | 不转换；保留原字段语义 | 显示“未提供” | 审计 | 是 |
| `evidence_refs[].sha256` | 周报 | EvidenceFooter | SHA-256 | 截断＋完整值 | 不转换；保留原字段语义 | 显示“未提供” | 审计 | 是 |
| `evidence_refs[].claim` | 周报 | EvidenceFooter | 支持结论 | 原文，不改写 | 不转换；保留原字段语义 | 显示“未说明支持结论” | 审计 | 是 |
| `progression_decision` | 周报 | WeeklyDecisionHero | 周决定 | advance→进阶；hold→维持；deload→减量 | 不转换；保留原字段语义 | 缺失显示“未决策” | 主 | 否 |
| `progression_rule` | 周报 | WeeklyDecisionHero | 应用规则 | advance/hold/deload＋中文说明 | 不转换；保留原字段语义 | 缺失隐藏 | 主 | 否 |
| `progression_dimension` | 周报 | WeeklyDecisionHero | 推进维度 | distance→距离；intensity→强度；none→不推进 | 不转换；保留原字段语义 | 缺失显示“未标注” | 主 | 否 |
| `previous_week_distance_km` | 周报 | WeekComparison | 上周距离 | 1 位小数 `km` | 统一为 km | 只显示本周，不算变化率 | 主 | 否 |
| `current_week_distance_km` | 周报 | WeeklyKPI＋WeekComparison | 本周距离 | 1 位小数 `km` | 统一为 km | 显示“暂无数据” | 主 | 否 |
| `previous_week_intensity_score` | 周报 | WeekComparison | 上周强度 | 原量表数值＋量表名待开发确认 | 不转换；保留原字段语义 | 只显示本周，不算变化率 | 次 | 否 |
| `current_week_intensity_score` | 周报 | WeekComparison | 本周强度 | 原量表数值＋量表名待开发确认 | 不转换；保留原字段语义 | 隐藏强度比较 | 次 | 否 |
| `evidence_running_distance_km` | 周报 | EvidenceFooter | 证据跑量 | 1 位小数 `km` | 统一为 km | 隐藏 | 审计 | 是 |
| `evidence_caution_days` | 周报 | EvidenceFooter | 证据谨慎天数 | 整数 `天` | 整数计数，不换算 | 隐藏 | 审计 | 是 |
| `evidence_daily_count` | 周报 | EvidenceFooter | 证据日报数 | 整数 `份` | 整数计数，不换算 | 隐藏 | 审计 | 是 |
| `training_plan` | 周报 | PlanTimeline | 下周计划 | 对象 | 不转换；保留原字段语义 | 周报成功但缺失时显示“下周计划未生成” | 主 | 否 |
| `training_plan.schema_version` | 周报 | EvidenceFooter | 计划 Schema | 原字符串 | 不转换；保留原字段语义 | 隐藏 | 审计 | 是 |
| `training_plan.status` | 周报 | PlanTimeline | 计划状态 | 原枚举＋中文文字 | 不转换；保留原字段语义 | 非成功时隐藏可执行课表 | 主 | 否 |
| `training_plan.progression_rule` | 周报 | WeeklyDecisionHero | 计划规则 | advance/hold/deload | 不转换；保留原字段语义 | 缺失沿用周报规则；仍缺则隐藏 | 主 | 否 |
| `training_plan.progression_dimension` | 周报 | WeeklyDecisionHero | 推进维度 | distance/intensity/none | 不转换；保留原字段语义 | 缺失沿用周报维度；仍缺则隐藏 | 主 | 否 |
| `training_plan.provider_calls` | 周报 | EvidenceFooter | 计划数据调用 | 次数或来源列表 | 不转换；保留原字段语义 | 空数组隐藏 | 审计 | 是 |
| `training_plan.items[]` | 周报 | PlanTimeline | 七日课程 | 按日期升序；最多预期 7 项 | 不转换；保留原字段语义 | 空数组显示“暂无排课” | 主 | 否 |
| `training_plan.items[].date` | 周报 | CourseCard | 日期 | `M月D日 周X` | 不转换；保留原字段语义 | 无日期项移至末尾并标记 | 主 | 否 |
| `training_plan.items[].activity_kind` | 周报 | CourseCard | 类型 | running/climbing/rest 映射中文 | 不转换；保留原字段语义 | 类型未知用中性色 | 主 | 否 |
| `training_plan.items[].name` | 周报 | CourseCard | 课程名称 | 原文 | 不转换；保留原字段语义 | 显示“未命名课程” | 主 | 否 |
| `training_plan.items[].purpose` | 周报 | CourseCard | 课程目的 | 原文 | 不转换；保留原字段语义 | 隐藏 | 主 | 否 |
| `training_plan.items[].load_level` | 周报 | CourseCard | 负荷 | low/moderate/hard＋文字；hard 强标识 | 不转换；保留原字段语义 | 缺失显示“负荷未标注” | 主 | 否 |
| `training_plan.items[].garmin_mapping_status` | 周报 | CourseCard | Garmin 状态 | 原枚举＋中文说明 | 不转换；保留原字段语义 | 隐藏 | 次 | 否 |
| `training_plan.items[].distance_km` | 周报 | CourseCard | 距离 | 1 位小数 `km` | 统一为 km | 隐藏 | 主 | 否 |
| `training_plan.items[].duration_minutes` | 周报 | CourseCard | 时长 | 整数 `分钟` | 分钟；≥60 可转 X小时Y分 | 隐藏 | 主 | 否 |
| `training_plan.items[].pace_min_seconds_per_km` | 周报 | CourseCard | 配速下界 | `m:ss/km` | 秒/公里 → m:ss/km | 单端存在时显示单端 | 次 | 否 |
| `training_plan.items[].pace_max_seconds_per_km` | 周报 | CourseCard | 配速上界 | `m:ss/km` | 秒/公里 → m:ss/km | 单端存在时显示单端 | 次 | 否 |
| `training_plan.items[].heart_rate_min_bpm` | 周报 | CourseCard | 心率下界 | 整数 `bpm` | 统一为 bpm | 单端存在时显示单端 | 次 | 否 |
| `training_plan.items[].heart_rate_max_bpm` | 周报 | CourseCard | 心率上界 | 整数 `bpm` | 统一为 bpm | 单端存在时显示单端 | 次 | 否 |
| `training_plan.items[].rpe` | 周报 | CourseCard | 主观强度 | `RPE n/10` | 不转换；保留原字段语义 | 隐藏 | 主 | 否 |
| `training_plan.items[].steps[]` | 周报 | CourseCard | 课程步骤 | 按原顺序编号 | 不转换；保留原字段语义 | 空数组隐藏 | 主 | 否 |
| `training_plan.items[].steps[].name` | 周报 | CourseCard | 步骤名称 | 原文 | 不转换；保留原字段语义 | 显示“未命名步骤” | 主 | 否 |
| `training_plan.items[].steps[].end_condition` | 周报 | CourseCard | 结束条件 | 原文 | 不转换；保留原字段语义 | 隐藏 | 主 | 否 |
| `training_plan.items[].downgrade_rule` | 周报 | CourseCard | 降级规则 | 原文，不改写 | 不转换；保留原字段语义 | 显示“未提供降级规则” | 主 | 否 |
| `training_plan.items[].stop_conditions[]` | 周报 | CourseCard | 停止条件 | 一项一行，原文 | 不转换；保留原字段语义 | 空数组显示“未提供停止条件” | 主 | 否 |
| `extra_sections[]` | 日报 / 周报 | ExtraSectionRenderer | 更多观察 | 按 priority 排序 | 不转换；保留原字段语义 | 空数组隐藏整个区域 | 次 | 否 |
| `extra_sections[].id` | 日报 / 周报 | 模板键 | 模块 ID | 原值，仅用于绑定 | 不转换；保留原字段语义 | 缺失项不渲染 | 审计 | 是 |
| `extra_sections[].title` | 日报 / 周报 | 扩展卡 | 标题 | 原文 | 不转换；保留原字段语义 | 使用类型的通用中文名 | 次 | 否 |
| `extra_sections[].type` | 日报 / 周报 | 渲染器 | 类型 | 白名单枚举 | 不转换；保留原字段语义 | 未知类型降级 text 或隐藏 | 次 | 否 |
| `extra_sections[].priority` | 日报 / 周报 | 排序器 | 优先级 | 数字或 high/medium/low | 不转换；保留原字段语义 | 默认排到末尾 | 审计 | 是 |
| `extra_sections[].summary` | 日报 / 周报 | 扩展卡 | 摘要 | 原文 | 不转换；保留原字段语义 | 隐藏 | 次 | 否 |
| `extra_sections[].data` | 日报 / 周报 | 扩展卡 | 数据 | 由 type 对应渲染器处理 | 不转换；保留原字段语义 | 缺失隐藏组件 | 次 | 否 |
| `extra_sections[].unit` | 日报 / 周报 | 扩展卡 | 单位 | 原单位；仅按已知规则转换 | 不转换；保留原字段语义 | 缺失不猜单位 | 次 | 否 |
| `extra_sections[].source_refs[]` | 日报 / 周报 | EvidenceFooter | 扩展来源 | ID 列表 | 不转换；保留原字段语义 | 空数组标记“无来源引用” | 审计 | 是 |
| `extra_sections[].display_hint` | 日报 / 周报 | 模板渲染提示 | — | 仅用于模板选择，不直接展示 | 不转换；保留原字段语义 | 缺失使用默认布局 | 审计 | 是 |
| `heart_rate_zones[]` | 日报 / 周报 | StaticChart | 心率分区 | 有数据才生成堆叠条/PNG | 统一为 bpm | 空数组隐藏图表 | 次 | 否 |
| `heart_rate_zones[].zone` | 日报 / 周报 | StaticChart | 区间 | `Z1–Z5` | 统一为 bpm | 缺失项不渲染 | 次 | 否 |
| `heart_rate_zones[].label` | 日报 / 周报 | StaticChart | 区间名称 | 原文 | 统一为 bpm | 使用 zone | 次 | 否 |
| `heart_rate_zones[].min_bpm` | 日报 / 周报 | StaticChart | 下限 | 整数 `bpm` | 统一为 bpm | 不显示范围 | 次 | 否 |
| `heart_rate_zones[].max_bpm` | 日报 / 周报 | StaticChart | 上限 | 整数 `bpm` | 统一为 bpm | 不显示范围 | 次 | 否 |
| `heart_rate_zones[].duration_seconds` | 日报 / 周报 | StaticChart | 时长 | `mm:ss` 或 `h:mm:ss` | 秒 → 小时/分钟/秒 | 缺失项不参与时长图 | 次 | 否 |
| `heart_rate_zones[].percentage` | 日报 / 周报 | StaticChart | 占比 | 1 位小数 `%` | 统一为 bpm | 不根据时长自行补算，除非开发明确授权 | 次 | 否 |
| `heart_rate_zones[].color` | 日报 / 周报 | 图表渲染 | 分区颜色 | 仅接受安全调色板映射 | 统一为 bpm | 缺失使用设计令牌 | 次 | 否 |
| `sleep_stages[]` | 日报 / 周报 | StaticChart | 睡眠阶段 | 有数据才生成时间轴/PNG | 不转换；保留原字段语义 | 空数组隐藏图表 | 次 | 否 |
| `sleep_stages[].stage` | 日报 / 周报 | StaticChart | 阶段 | 映射深睡/浅睡/REM/清醒 | 不转换；保留原字段语义 | 未知值保留原枚举 | 次 | 否 |
| `sleep_stages[].start` | 日报 / 周报 | StaticChart | 开始 | `HH:mm` | 不转换；保留原字段语义 | 缺失时不画时间轴 | 次 | 否 |
| `sleep_stages[].end` | 日报 / 周报 | StaticChart | 结束 | `HH:mm` | 不转换；保留原字段语义 | 缺失时不画时间轴 | 次 | 否 |
| `sleep_stages[].duration_seconds` | 日报 / 周报 | StaticChart | 时长 | `X小时Y分` | 秒 → 小时/分钟/秒 | 缺失时不显示时长 | 次 | 否 |
| `sleep_stages[].percentage` | 日报 / 周报 | StaticChart | 占比 | 1 位小数 `%` | 0–1 转百分比；百分数原值保留 | 不自行补算 | 次 | 否 |
| `activity_series[]` | 日报 / 周报 | StaticChart | 活动序列 | 静态 PNG 2x＋fallback 表 | 不转换；保留原字段语义 | 空数组隐藏图表 | 次 | 否 |
| `activity_series[].timestamp` | 日报 / 周报 | 图表 X 轴 | 时间 | `HH:mm:ss` | 不转换；保留原字段语义 | 缺失点丢弃 | 次 | 否 |
| `activity_series[].heart_rate` | 日报 / 周报 | 图表 | 心率 | 整数 `bpm` | 统一为 bpm | 不画该序列 | 次 | 否 |
| `activity_series[].pace` | 日报 / 周报 | 图表 | 配速 | `m:ss/km` | 不转换；保留原字段语义 | 不画该序列 | 次 | 否 |
| `activity_series[].cadence` | 日报 / 周报 | 图表 | 步频 | 整数 `spm` | 不转换；保留原字段语义 | 不画该序列 | 次 | 否 |
| `activity_series[].power` | 日报 / 周报 | 图表 | 功率 | 整数 `W` | 不转换；保留原字段语义 | 不画该序列 | 次 | 否 |
| `activity_series[].elevation` | 日报 / 周报 | 图表 | 海拔 | 1 位小数 `m` | 不转换；保留原字段语义 | 不画该序列 | 次 | 否 |

## 隐私排除字段

以下信息不得进入邮件正文或示例：GPS 坐标、路线、私人地址、Token、凭据、内部配置路径。若上游 payload 包含这些字段，模板层必须丢弃，并在发送前执行敏感字段检查。

## 验收

- [ ] 上表每一行均有实际绑定或明确条件隐藏。
- [ ] 正文没有 SHA、内部 ID 的高视觉权重展示。
- [ ] `blocked` 状态仍保留 error_code 与证据引用。
- [ ] 不根据缺失数组生成心率分区、睡眠阶段或趋势图。
