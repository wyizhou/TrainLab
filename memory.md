# TrainLab 项目记忆

本文件用于跨会话外置持久上下文，由主协调 Agent 根据已验证证据维护。

## 维护约定

- 只保存稳定偏好、已验证项目事实、已建立的 lint/test 命令和活动计划链接。
- 不重复任务步骤或检查点；exec plan 是任务状态的唯一事实源。
- 不保存密钥、凭据、个人健康数据、raw/FIT 内容、邮件内容、完整对话或未经验证的假设。
- 更新或删除过期事实；Validator 和 Worker 只返回发现，不直接修改本文件。

## 用户偏好

- 项目说明文档默认使用中文；路径、命令、状态枚举和协议标识符保留技术拼写。
- 开发使用根 agentForge Harness。ADHOC-0011 已获批准；本机已完成 raw-first state 切换和旧
  集中式入口归档。M7 离线 Skills 闭环与双层测试已通过独立 Validator；cron 保持关闭，外部
  MCP 自动写入仍未启用。M10 已完成一次用户明确确认的有界端到端写入验收，未授权长期自动化。
- `orchestrate-parallel-work` 只在本仓库禁用；不修改其全局安装。

## 已验证的项目事实

- 根开发 Harness 固定适配 agentForge `v0.4.4`，上游标签提交为
  `00e03cfb6e25e35967e414bea9233dc7b33929d5`。每个新任务在 exec plan 中冻结验证合同；
  Validator 的阻塞发现必须绑定既有标准，未绑定或无法判断时为 `INCONCLUSIVE`，不得触发实现修改。
- 同一失败特征采用两种实质不同修法仍失败、连续三轮不收敛或直接出现合同冲突时，任务进入
  `DIAGNOSIS_PENDING`；只有独立只读 Failure Analyst 可以读取失败历史并在实现缺陷、规划合同
  冲突、验证缺陷、环境故障和无法确定之间归因。
- TrainLab 的目标产品运行目录为 `source/`；本机工作树不再依赖集中式 `source/src` 包或统一 CLI，
  运行入口由 `source/AGENTS.md`、本地 Skills 和 SQLite 状态组成。M7 目标树已保存为本地
  `feat: complete AI skills workflow and test harness` 提交，并通过 clean checkout 合成验证。
- 当前运行库是 raw-first 六表 SQLite，不含 Orchestration/Supervisor 表和视图；旧 state/config/logs/数据库
  归档在被 Git 忽略的 `data-backup/`，不删除、不进入产品新库。
- 产品时区合同使用 `Asia/Hong_Kong`；训练规则和报告目标采用 AI + 本地 Skills 设计。M8 已在仓库外
  candidate 中完成真实 AI 日报、周报、课表、报告、邮件信封和 GTS 合同闭环；真实外部动作仍关闭。
- 私有 state、logs、FIT、raw、数据库、凭据和私有配置不得进入 Git 或 `dist/`。
- 项目不再使用或忽略根 `test_data/`；当前 Skill 合同测试不携带私人 Garmin 输入，
  私人 raw/FIT 只能留在被忽略的 state 或仓库外归档。
- 根 `references/` 只由用户主动要求维护；运行说明和 Skill 合同位于 `source/AGENTS.md`、
  `source/skills/` 与 `source/templates/`。
- 2026-08-19 M10 的4项临时Garmin测试Workout已完整创建、排期、取消和删除，残留0。Gmail
  MCP真实投递与r05本地事实链未能交付，现由A-010替换为官方Gmail REST；该变化不代表长期
  启用，cron和自动外部写入继续关闭，每次新写入仍需精确授权。
- M10 已于2026-08-20完成：4项临时Garmin测试Workout生命周期结束且残留0；官方Gmail REST
  成功闭合r07旧标题8封与r08更正标题8封，累计16封。最终Code、AI和Delivery/Data-Privacy
  Validator均PASS；正式state、Token边界和确定性重放闭合。该结果不授权长期自动发送或cron。
- M11 已于2026-08-23完成v3真实投递：7份日报和1份周报通过官方Gmail REST严格串行发送，
  8个Gmail ID、实际Message-ID、RAW/text/HTML/CID闭合；32次REST调用中send恰好8次，重放
  Provider增量0，Code与Delivery/Data-Privacy Validator均PASS。该结果不授权部署或定时运行。

## 已建立的验证命令

- `cd source && PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/code -q`
- `cd source && ruff --config skills/_shared/ruff.toml check skills tests/code`
- `cd source && ruff format --check skills tests/code`
- `cd source && mypy --config-file skills/_shared/mypy.ini skills tests/code`
- Skill JSON/agent metadata、编译和 Git ignore 门禁从 `source/` 执行；`git diff --check` 从仓库根执行；
  AI 语义验收按需执行，不读取正式 state/raw；正式运行不依赖 wheel、bundle、Supervisor 或仓库 `.venv`。

## 当前活动计划

- 迁移恢复与 M11 r20 前置收口正在按严格串行方案执行：
  `docs/exec-plans/active/ADHOC-0017-workspace-migration-recovery.md`。
- M11 content-first v4 当前r19被公开canary阻塞：Prompt/Schema语义parity修复、909项门和Code Validator均PASS；唯一公开模型调用的wire结果通过，但day_3/day_6休息课输出空`technique_notes`，违反业务Schema非空数组约束。未自动重试，私人周报调用仍为0，正式state不变：
  `docs/exec-plans/active/M11-email-presentation-0001-readable-cid-r02.md`。

## 最近完成计划

ADHOC-0015 已将根开发 Harness 从 agentForge v0.4.2 三方适配到 v0.4.4：六个核心文件、
A-019、MIT 声明、冻结验证合同、固定 Validator 输出和失败诊断门完成；664 项测试与全部代码门、
115 项 owner-only 快照恢复演练及正式 state 9,347 项完整指纹均闭合，全新只读 high/high Validator
返回 `PASS`。计划归档至 `docs/exec-plans/completed/ADHOC-0015-agentforge-0.4.4-upgrade.md`；
快照按用户要求保留，M11 只迁移为 `DIAGNOSIS_PENDING`，未运行 Failure Analyst 或模型调用。

M11 `人类可读邮件与 CID 图表闭环` 已于2026-08-23完成并归档至
`docs/exec-plans/completed/M11-email-presentation-0001-readable-cid.md`；其v3真实投递续批归档至
`docs/exec-plans/completed/M11-email-presentation-0001-readable-cid-r01.md`。v2教练内容保持RPE/体感和
历史参考配速，不生成心率分区或目标BPM处方；v3共享OpenDesign引擎恢复日报/周报卡片、KPI、
真实图表和七日时间轴。历史活动心率分区仅使用Garmin/FIT session已记录时长，设备定义不一致时
周报不聚合。最终594项测试及Code、Design-Fidelity、Data/Privacy三类全新只读Validator全部PASS；
离线七日报一周报、8份MIME和正式state闭合；随后600项代码门与独立Code Validator通过，8封
真实Gmail严格串行完成并由Delivery/Data-Privacy Validator复验PASS。部署与定时运行未执行。

M10 `滚动七日真实端到端验收` 已于2026-08-20完成并归档至
`docs/exec-plans/completed/M10-live-e2e-0001-rolling-week.md`。7份日报、1份周报和周计划完成真实
闭环；4项临时Garmin测试Workout已创建、排期、取消和删除，残留0；r07旧标题8封与r08更正
标题8封均通过官方Gmail REST闭合，累计16个不同Gmail ID。r08最终API64/send16，含认证Profile
总Provider65；稳定重放Provider增量0。最终Code、AI、Delivery/Data-Privacy三名全新只读Validator
均PASS；正式state 9347项指纹与Token边界保持闭合。历史FAIL与r04/r05 unknown证据继续保留，
TD-0002保持deferred；M10未授权长期外部写入、Sites或cron。

M9 `单日 Garmin MCP 有界真实只读闭环` 已于 2026-08-18 完成并归档至
`docs/exec-plans/completed/M9-garmin-live-0001-bounded-daily-sync.md`。r04 Candidate 的固定单日读取
使用 8 次 MCP/9 次 Provider，新增 6 个文件并在相同输入重放时保持 Provider 为 0；r07 公开
Schema canary 与唯一 attempt 4 成功，日报、报告和 workflow receipt 的确定性重放保持 ID、SHA、
HTML 和数据库行数不变。207 项代码门及 Code、AI、Data/Privacy 三类全新只读 Validator 均 PASS；
正式 state 与 Token 保持不变，Gmail、Workout、Sites、cron 和 external actions 均为 0；M9
随后由 ADHOC-0014 完成本地交付，仍未推送，也未迁移到正式 state。

ADHOC-0014 已把 M9 保存为本地可交付版本：非私人实现提交为 `11df68d`
（`feat: complete bounded Garmin MCP daily closure`）；完整 r04 Candidate 归档于被 Git 忽略的
`data-backup/m9-delivery-20260818T121622Z/`，9,439文件、134,625,152B、聚合SHA-256闭合。
detached clean worktree 的207项测试及全部静态门通过，全新只读 Delivery Validator 返回 PASS；
正式 state、Token和远端均未修改。执行计划归档至
`docs/exec-plans/completed/ADHOC-0014-m9-local-delivery.md`。

M5 自适应教练画像与本地报告校准已通过独立 Validator；exec plan 已归档至
`docs/exec-plans/completed/M5-adaptive-coaching-0001-profile-and-preview.md`。
真实隔离库因活动覆盖不完整按合同延期，未伪造报告；预览 renderer 的 HTML/JSON、权限和无副作用回归通过。
M7 `AI + Skills 执行闭环与双层测试体系` 已通过全新集成 Validator；已建立
`feat: complete AI skills workflow and test harness` 本地提交。`source/tests/code` 的 31 项
确定性测试、Ruff、format、mypy、compile、8 个 Schema、日报资源分桶、恢复红旗和周报证据闭环
均通过；正式 `source/state`、Garmin、Gmail、Sites 和 cron 均未被修改或调用。
M8 `真实私人数据离线 AI 教练闭环` 已通过三名全新只读 Validator；固定真实窗口的 8 份日报、1 份
周报、8/16 模型前阻断、精确七日报历史选择、报告/邮件/GTS prepared、工作流回执和重放均通过。
candidate raw 为 9336 项、119992332 字节，正式 state before/after 指纹一致；Code/AI/Data-Privacy
均为 `PASS`。r31 曾因普通 `mode=ro` 读取触碰正式 SHM 的失败记录保留，不能声称整个 M8 历史从未触碰
sidecar；M8 仍未授权真实外部写入或 cron。
M8 交付已保存为本地提交 `69ed9b4`（`feat: complete real-data AI coaching closure`），未推送。
最近完成的 M4 计划已归档至
`docs/exec-plans/completed/M4-source-root-0001-product-consolidation.md`；M4 基线提交为
`bab3649`（`feat: complete source runtime migration`）。

M5 已保存为本地基线提交 `0687d9f`（`feat: add adaptive coaching and local report previews`）。
M6 活动计划已被 ADHOC-0011 取消/替代；其 completed plan 保留离线优先审计
目标周活动 inventory 生命周期，正式 state、Garmin、Gmail 和邮件保持不变。M6-0002/0003
已通过独立 Validator；M6-0004 因 candidate weekly 被确定性 safety 门拒绝而 blocked，
未生成真实 daily/preview。用户已暂停继续优化；ADHOC-0009 只读来源审计已归档至
`docs/exec-plans/completed/ADHOC-0009-source-data-provenance-audit.md`。审计确认 raw 文件与
登记哈希完整闭合，但数据库还包含覆盖、生命周期、质量、实例元数据及少量无 revision 的
TrainLab 生理候选；是否恢复 M6、删除流程或另立在线核验由用户后续决定。ADHOC-0010
已归档至 `docs/exec-plans/completed/ADHOC-0010-raw-directory-taxonomy-audit.md`：raw 按来源、
格式和写入月份组织，业务语义以 revision 为准；8 个 Finder `.DS_Store` 不是 raw 证据且会
阻断严格 raw 树校验，旧 state 归档时不复制。ADHOC-0011 已归档至
`docs/exec-plans/completed/ADHOC-0011-state-raw-retention-and-tuning.md`：用户已批准 active raw
最终移除 `backup`、`gmail`、`legacy`，保留 Provider 层与 `raw/garmin`；FIT、GPX、TCX
规划直接平铺到 `raw/garmin/activities/`，文件名使用运动日期、共同活动关联哈希和格式
后缀；每个文件的内容 SHA-256 仍独立保存。ADHOC-0011 已获实施指令；切换后仍不得
调用 Provider。后续只读审计确认历史库有 53 种 Garmin JSON
语义资源，但普通同步已使用较窄白名单；请求优化和历史 raw 删除尚未成为已确认需求。
已确认的未来同步边界为项目主体本地时间每日 12:00：只取昨日完整活动与非睡眠健康数据、
以及今日早晨结束并按醒来日归属的主睡眠；取消自动 14 日历史回读。数据不完整时只记录，
只有用户明确指定并批准日期后才补数；该边界已写入 `garmin-sync` 计划脚本，正式 Provider
调用仍关闭。
用户进一步确认未来 Garmin raw 使用 `health/` 与 `activities/` 两类业务证据：健康文件按
`日期-资源-内容哈希.json` 平铺，活动文件与同 activity hash 的天气 JSON 平铺；
`activity_inventory` 仅作为可重新初始化的数据库控制状态，不建立 collection 目录；
未来取消 `activity_summary`，活动只从 FIT/GPX/TCX 确定性重建；candidate 已按该边界索引，
正式 state 已在无外部调用的条件下切换，并通过切换后独立复核；旧 state 原样归档。
用户确认未来重构时重置 `source/state/` 下除 `raw/` 外的全部旧运行状态，包括当前数据库，
且不迁移旧数据库内容；新数据库只从确认保留的健康 raw 与活动原始文件重建，inventory 等
控制状态重新初始化。ADHOC-0011 已实施；旧 state 已完整保留在本次切换归档中，可回滚但不作为
新系统数据源。
用户进一步确认下一代最小运行结构完全由 AI 与本地 Skills 驱动：私有 `goal.md` 和
`state/**` 被 Git 忽略，跟踪 `goal.module.md` 及 Garmin health/activities 的 `.gitkeep`
骨架；首批本地 Skill 为 `garmin-sync`、`training-coach`、`garmin-training-sender`、
`weekly-fitness-summary`、`gmail-sender` 和 `training-report-publisher`。其中
`garmin-training-sender` 与 `weekly-fitness-summary` 以用户点名的全局 Skill 为规格来源做
本地适配，但不修改全局原件。`training-report-publisher` 的项目骨架已建立在
`source/skills/`，引用已安装的 Data Analytics `build-report`，Sites 发布只在另有授权时调用，
不复制或修改插件原件。当前日报和周计划 HTML 将分为固定样式与开放报告邮件外壳两套保留。
`training-coach` 明确定位为类似 “Course Coach” 的教练 Skill：
接受来自用户或运行中 AI 的统一输入并标明来源；每日模式输出昨日健康、运动与昨夜睡眠
总结，每周模式输出周总结及结构化课表。课表既可由用户直接批准，也可由已获用户预授权的
定时 AI 按固定安全规则审核批准并交给
`garmin-training-sender`；定时自动运行不要求逐次人工确认，普通未授权 AI 调用则不能批准
Garmin 写入。六个本地 Skill、模板和 cron 配置已经落地；旧运行层已在切换后独立复核前移出
产品树并保留在归档中。
`garmin-sync` 将通过本地 Garmin MCP，依据 SQLite 采集状态增量获取 activities/health raw
并同步状态；`gmail-sender` 使用本地 Gmail MCP 收取和发送邮件。六个 Skill 均采用脚本优先，
把可确定、可重复的工作放入各自 `scripts/`，以减少 Token 和运行差异。早期提议的
`data-build` 已从目标中移除；`training-coach` 自带
脚本按任务窗口解析 health JSON、FIT、GPX、TCX 与天气 raw，只向 AI 提供有界证据。
用户确认未来只设置两个 `cron + codex exec` 无状态流程：每日 12:00、每周日 12:30 依次运行
`garmin-sync → training-coach → training-report-publisher → gmail-sender`；每周日依次
运行 `garmin-sync → training-coach` 每周模式、
`garmin-training-sender → training-report-publisher → gmail-sender`。每次从 AGENTS、goal、
config、文件和 SQLite 恢复，
所有结果必须落地。周流程管理的是 Garmin Connect My Workouts 中名称精确以 `-GTS` 结尾的
课程模板：先解除未来排期，再删除已确认归属的旧模板，创建并验证新模板后加入日历；不得
删除已完成运动或无关 Workout。该清理已纳入预授权定时 AI 的自动运行范围，尚未实施。
用户改为让 raw 只保留原始文件，不再把健康、睡眠和活动清洗成数据库事实表。所有 Skill 的
有界证据、每日总结、周总结、课表、最终邮件内容、Garmin Workout 合同和运行状态统一追加
写入 `source/state/trainlab.db`。首批表为 `raw_files`、`activity_inventory`、`skill_runs`、
`skill_outputs`、`approvals`、`external_actions`。因为 AI 输出无法从 raw 原样重现，数据库需
要一致性备份。六表字段、SQLite Online Backup/恢复/保留和六 Skill 输入输出/幂等合同已写入
ADHOC-0011，并已在仓库外 candidate 建立新数据库；r22 候选与切换后 `source/state` 均通过独立
Validator。正式 `source/state` 已原子切换到 r22，旧 state、旧配置/日志和退役源码原样归档在
`data-backup/adhoc0011-cutover-20260815T165449Z/`；追加不可变、摘要绑定、精确批准范围、外部动作
语义与状态机、损坏数据库隔离和锁先行恢复已补入当前运行层。
用户确认正常日报只解析当前新增 raw，并复用 SQLite 中此前 14 份日总结；正常周报使用本周期
7 份日总结和此前 4 份周总结。历史 raw 仅在总结缺失、数据矛盾、缺少必要细节、需要复核 FIT
或用户明确要求时定向读取，不做无条件历史全窗口重算。日/周总结保存结构化 JSON 与文本；
报告和邮件 HTML 由 `training-report-publisher` 作为独立、哈希绑定的输出生成，并携带来源
raw/output ID 或 SHA-256。
