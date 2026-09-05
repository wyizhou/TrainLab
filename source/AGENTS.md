# TrainLab 运行 Harness

本文件只描述 `source/` 的产品运行方式，必须服从仓库根目录的 agentForge 开发 Harness、
`rules.md`、`PLANS.md` 和当前 exec plan。它不授权修改代码、修改长期目标、调用外部服务或
绕过 SQLite 状态合同。

## 每次无状态运行的读取顺序

1. 读取本文件和 `config.json`。
2. 读取私有 `goal.md`；文件缺失、权限不是 `0600` 或结构无效时立即 `blocked`。v4 周报必须由
   Host 按公开模板的1个文档标题、5个章节和19个字段解析为 `training_goal_v1`；AI 只能读取该结构化对象，
   不得读取 `goal.md` 正文、文件名、相对路径或绝对路径。
   Gmail 自投递还必须读取私有 `email.json`；首次配置时从可跟踪的空模板
   `email.module.json` 复制并填写。`email.json` 只能包含当前认证邮箱地址，必须为 `0600`
   且被 Git 忽略，缺失、占位、权限错误或地址无效时不得调用 Gmail。
3. 读取 `skills/README.md`，再只读取本次任务需要的 `SKILL.md` 和其脚本说明。
4. 读取 `state/trainlab.db` 的最近运行、输出、批准和外部动作；数据库缺失或锁不可用时停止。
5. 由脚本生成有界证据后再交给 AI。不得把完整 raw、FIT、凭据或邮件历史直接放入上下文。

测试只用于开发和验收，不是正常运行输入。确定性测试在 `tests/code/`，AI 语义验收在
`tests/ai/`；运行时不得读取这两个目录。

## 硬性训练规则

- Hansons 只作为跑步课程的缩放参考，不覆盖恢复和安全证据。
- Easy 是低负荷有氧；SOS 是有明确质量目标的高负荷课，两者不得混写。
- 跑步 SOS 与高负荷攀岩统一计入硬负荷；硬负荷最多 3 次，任意两次至少间隔 2 个日历日。
- 每天最多一个主课；不补偿错过的质量课；不在同一周同时增加距离和强度。
- 日报、周报和课表只能引用已验证输入，不能把 AI 偏好写回 `goal.md`。
- 疼痛、胸痛、晕眩、异常呼吸或明显恢复不足时，降低训练或停止训练，并记录稳定错误码。

## 数据和外部边界

- 健康与活动只作为 `state/raw/` 下的原始文件保存；SQLite 不承载健康、睡眠或活动业务事实表。
- 所有 Skill 的输入摘要、输出、批准、成功/失败/待处理状态都追加写入 `state/trainlab.db`。
- 日常 Garmin 同步只处理昨日完整数据和今日早晨结束的主睡眠，不自动回读最近 14 天。
- 补数、Garmin Workout 写入、Gmail 查询/发送和 Sites 发布必须有明确范围、批准、幂等键和对账。
- 本阶段 cron 只生成配置，不安装或启用；没有授权时不得调用 Garmin、Gmail 或 Sites。
- Garmin MCP 凭据或认证状态缺失、过期或格式不明时，Skill 必须安全停止并写入脱敏错误；
  不得猜测密码、MFA 或 token 内容。Gmail 按 A-010 使用 owner-only
  `gcp-oauth.keys.json` 与 `gmail-api-token.json`：首次授权只能由用户在系统浏览器完成，运行时
  只允许正常刷新该专用 token，并以 `0600` 临时文件、fsync 和原子改名更新；旧
  `credentials.json` 只作为 Gmail MCP 历史保留且不得读取或覆盖。
- `email.json` 不是凭据，只保存 Gmail 自投递地址；地址可以进入私有 Candidate 的精确动作
  请求以便审计，但不得进入 Git、报告正文或公开日志。

## 输入和输出

`training-coach` 可以接收用户输入，也可以接收定时 AI 的有界输入；它输出结构化总结和课表。
`training-report-publisher` 负责 HTML/邮件表现层，`gmail-sender` 负责邮件外部动作，
`garmin-training-sender` 负责已批准的 Garmin Connect My Workouts `-GTS` 模板。

M11 的可读邮件必须先通过显式 ViewModel，再渲染 owner-only HTML/text 和确定性 CID PNG；不得
把 AI/JSON 的任意键直接循环成页面，也不得为视觉完整性推导不存在的心率区间、睡眠阶段或
训练负荷。AI 自由文本摘要、证据 claim 和停止条件不得直接成为读者文字；展示摘要和来源标签
只从已验证结构化状态确定性生成。A-014、A-017 的 Gmail 批次均为已结束的历史精确授权，不得
由 `auto.txt`、定时任务或后续返工继承。当前 A-018 内容优先返工的 Gmail 发送授权为零；只允许
生成仓库外离线 Markdown 和低保真 HTML。

A-014 起，日报 VO₂ Max 只可选择截至回顾日 30 天内最新有效值，体重只可选择 14 天内最新
有效值；必须通过 `recent_health_metrics_v1` 记录测量日期、新鲜度、raw ID/SHA 和零 Provider
调用。睡眠、RHR、HRV、全天心率和活动仍按精确日期读取。历史值必须标明实际测量日期，期限内
缺失时如实显示缺失，不得阻断或联网补齐。

A-015 起，v2 教练内容不得计算或处方心率区间、目标 BPM、最大心率、阈值或 Z1–Z5；已观测
RHR、HRV、活动平均/最高心率只能作为历史事实。跑步课程使用 RPE 和体感为主要强度合同，
可比历史证据存在时才可附加非目标性质的参考配速。`hold/advance` 周默认恰好一节条件性 SOS
并优先安排星期三；`deload`、红旗或有证据的明显恢复不足可为零并记录原因，单独 `caution`
不得取消整周 SOS。两个硬负荷日日期差必须至少 3 天（周一后最早周四）；SOS 偏离星期三必须
引用理由。日报必须区分周计划原课和今日调整；周报必须给出健康、运动负荷、3–5条
观察→意义→行动洞察及连续七天详细课程。v2 仅离线 Candidate 验收，不授权任何 Provider 调用。
v2 周报只读精确七份 v2 日报和最多四份历史 v2 周总结，禁止回读 raw。历史参考配速只能来自
Host `comparable_pace_reference_v1`，适用规则见 A-015；SOS 不使用参考配速。

A-016 起，v3 展示层可以使用 Garmin/FIT 对已完成活动明确记录的 session 级心率分区时长，
并可从这些设备时长确定性计算展示占比。必须绑定活动、raw ID 和 SHA；不得从心率采样重新
划区、推导阈值或目标 BPM。该数据只进入历史活动总结和图表，课程、执行提示、降级与停止条件
继续按 A-015 使用 RPE、体感和历史参考配速。缺失、冲突或格式异常时隐藏图表。

A-018 起，v4 内容层不再由日报决定课程。日报保留健康/睡眠/恢复分析，昨日全部活动只客观
展示；今日课程必须逐字节引用周计划的 output ID/SHA，AI 不得调整、降级、取消、移动、替换或
补偿，是否执行由用户按体感自行决定。红旗安全门独立显示并阻断自动外部执行，但不改写计划。
周报只消费连续七份 `daily_completed_observation_v1` 与最多四份历史周总结，必须分析计划内外
全部实际活动和健康；简短计划对比不得过滤活动。技术复盘只使用有界 FIT/设备证据，设备心率
分区按 A-016 处理，不重算区间。周报生成唯一固定七日计划，保留 SOS、硬负荷间隔、课程步骤、
RPE、技术备注和停止条件，但不提供开始门、降级课或替代课。v4 先输出 Markdown 与扁平低保真
HTML；普通运行入口、高保真邮件和外部动作在后续明确批准前不得切换。

当前 v4 的 VC-002 健康合同要求每个健康日恰好包含睡眠、RHR、HRV、全天心率、VO₂ Max 和
体重六类唯一事实。每项只能是 `available`、`missing` 或 `insufficient_data`：有效值必须带
严格类型、日期、单位和完整 raw ID/SHA；真正没有记录才可标记缺失且不得保留值或 raw 引用；
已有 raw 但损坏、字段不全、日期/单位异常或冲突时必须标记数据不足并保留 raw 血缘。技术指标
引用必须精确绑定自己的 activity ID、raw ID、raw SHA 和 metric code，不得跨活动复用。

当前 v4 的 VC-008 模型输入使用 `m11_v4_weekly_model_context_v2`。`goal.md` 只在 Host 边界按
`goal.module.md` 的1个标题、5个章节和19个有序字段解析，
模型 Context 仅包含固定结构的 `training_goal_v1` 业务值。模型输入禁止文件名和任何相对、绝对
路径；只有 `跑步/攀岩`、`RHR/HRV`、`min/km` 三个业务斜杠写法，以及严格Schema验证后
`max_metrics:vo2_max` available事实的`unit`和`value.unit`同时为精确`ml/kg/min`时可以通过。
该单位出现在其他指标、其他字段、普通文本、变形值或附加后缀中仍必须阻断。Context、Prompt 与
权威 Schema 任一漂移时必须在创建模型 attempt 前停止，模型调用保持 0。训练强度只接受1–5
整数或`N/5，非空说明`，只将整数N交给模型；Prompt模板和目标模板均绑定仓库权威SHA。

VC-009保留仓库外owner-only模型工作目录的隔离设计。因该目录故意不是Git worktree，
Codex Runner必须精确使用一次`--skip-git-repo-check`，并在intent中绑定该命令合同。
该参数不得改变`--ephemeral`、`--ignore-user-config`、只读沙箱、权威Schema、模型输入隐私前检
或零Provider/外部动作边界。

VC-010继承VC-009的隔离、隐私和零外部动作边界，并收敛周模型与Host职责。模型只输出
`weekly_model_decision_v1`，不得输出周期、日期或Host运行状态；计划固定为`day_1..day_7`，
跑步/攀岩课程分别强制`warmup/main/recovery/cooldown`四个步骤对象，休息课程只含
`checklist`。Host从已验证Context注入三套周期和七个计划日期，生成`weekly_ai_result_v4`。
业务Schema是结构唯一来源，Codex wire只能由确定性投影删除`$schema`、`$id`、
`minLength`、`maxLength`、`minItems`、`maxItems`、`pattern`、`format`、`minimum`和
`maximum`；其他不支持关键词必须阻断，且不能改变字段、required、variants、enum/const或本地
引用拓扑。Prompt 的机器结构只能来自唯一规范 JSON 语义块；该语义块必须从业务/Host Schema
确定性提取并在 Candidate 与 Runner 前检中自动比对根字段、七个槽位、课程类型、步骤和 Host
字段，任一漂移必须在模型调用前停止。模型文本和未来课程禁止数字BPM及
心率区间处方；Reader只从已验证健康/活动字段确定性展示历史RHR、平均/最高心率及其日期/raw
血缘。Runner保存wire结果，完成Host、业务和Reader四层校验后才发布AI结果；Finalizer只能读取
Candidate内结果。公开合成canary和私人周报各最多调用一次Codex，均不自动重试。

任何脚本失败都必须使用稳定错误码写入 SQLite，而不是只打印一段不可恢复的文本。Skill run
状态只能使用 `pending/running/succeeded/failed/blocked/interrupted/cancelled`；外部动作另行使用
`prepared/in_progress/failed_safe/unknown/succeeded`，其中 `failed_safe` 和 `unknown` 均不是 Skill
run 状态。脚本应优先
完成可重复的哈希、窗口、Schema、权限、幂等和报告渲染工作，AI 只负责解释和受约束的决策。
