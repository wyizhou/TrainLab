# TrainLab 项目记忆

本文件用于跨会话外置持久上下文，由主协调 Agent 根据已验证证据维护。

## 维护约定

- 只保存稳定偏好、已验证项目事实、已建立的 lint/test 命令和活动计划链接。
- 不重复任务步骤或检查点；exec plan 是任务状态的唯一事实源。
- 不保存密钥、凭据、个人健康数据、raw/FIT 内容、邮件内容、完整对话或未经验证的假设。
- 更新或删除过期事实；Validator 和 Worker 只返回发现，不直接修改本文件。

## 用户偏好

- 项目说明文档默认使用中文；路径、命令、状态枚举和协议标识符保留技术拼写。
- 开发使用根 agentForge Harness。当前产品仍从 `source/index.py` 运行，但用户已确认下一代
  `source/` 将改为完全由 `source/AGENTS.md` 与六个本地 Skills 驱动；这是已规划、尚未实施
  的替代方向。
- `orchestrate-parallel-work` 只在本仓库禁用；不修改其全局安装。

## 已验证的项目事实

- 根开发 Harness 固定适配 agentForge `v0.4.2`，上游标签提交为
  `ccc934ece6b7b64368c08bc3ce431678511ecfa3`。
- TrainLab 的唯一产品工程位于 `source/`；产品包为 `source/src/`，直接入口为
  `source/index.py`，默认实例根为 `source/`，显式 `TRAINLAB_INSTANCE_ROOT` 可覆盖。
- Foundation v4 新库不含 Orchestration/Supervisor 表和视图；旧 state/config/logs/数据库
  归档在被 Git 忽略的 `data-backup/`，不删除、不进入产品新库。
- 产品时区合同使用 `Asia/Hong_Kong`；运行时教练 Harness v2 已加入课程、教练画像、
  睡眠半开区间和跑攀硬负荷合同。
- 私有 state、logs、FIT、raw、数据库、凭据和私有配置不得进入 Git 或 `dist/`。
- 项目不再使用或忽略根 `test_data/`；六类 Garmin FIT 测试输入由
  `tests/fixtures/synthetic_fit.py` 确定性生成，私人测试资料只能留在仓库外。
- 根 `references/` 只由用户主动要求维护；产品说明和运行资料位于 `source/docs/`。

## 已建立的验证命令

- `cd source && python3.12 tools/verify_repository_quality.py all`
- `cd source && python3.12 -m pytest`
- Ruff、format-check、mypy、schema 和 source-layout 门禁均从 `source/` 执行；正式运行
  不依赖 wheel、bundle、Supervisor 或仓库 `.venv`。

## 最近完成计划

M5 自适应教练画像与本地报告校准已通过独立 Validator；exec plan 已归档至
`docs/exec-plans/completed/M5-adaptive-coaching-0001-profile-and-preview.md`。
真实隔离库因活动覆盖不完整按合同延期，未伪造报告；预览 renderer 的 HTML/JSON、权限和无副作用回归通过。
最近完成的 M4 计划已归档至
`docs/exec-plans/completed/M4-source-root-0001-product-consolidation.md`；M4 基线提交为
`bab3649`（`feat: complete source runtime migration`）。

M5 已保存为本地基线提交 `0687d9f`（`feat: add adaptive coaching and local report previews`）。
M6 活动计划当前位于
`docs/exec-plans/active/M6-activity-evidence-0001-lifecycle-and-preview.md`；离线优先审计
目标周活动 inventory 生命周期，正式 state、Garmin、Gmail 和邮件保持不变。M6-0002/0003
已通过独立 Validator；M6-0004 因 candidate weekly 被确定性 safety 门拒绝而 blocked，
未生成真实 daily/preview。用户已暂停继续优化；ADHOC-0009 只读来源审计已归档至
`docs/exec-plans/completed/ADHOC-0009-source-data-provenance-audit.md`。审计确认 raw 文件与
登记哈希完整闭合，但数据库还包含覆盖、生命周期、质量、实例元数据及少量无 revision 的
TrainLab 生理候选；是否恢复 M6、删除流程或另立在线核验由用户后续决定。ADHOC-0010
已归档至 `docs/exec-plans/completed/ADHOC-0010-raw-directory-taxonomy-audit.md`：raw 按来源、
格式和写入月份组织，业务语义以 revision 为准；8 个 Finder `.DS_Store` 不是 raw 证据且会
阻断严格 raw 树校验，尚未删除。当前需求草案位于
`docs/exec-plans/active/ADHOC-0011-state-raw-retention-and-tuning.md`：用户已确认 active raw
最终移除 `backup`、`gmail`、`legacy`，保留 Provider 层与 `raw/garmin`；FIT、GPX、TCX
规划直接平铺到 `raw/garmin/activities/`，文件名使用运动日期、共同活动关联哈希和格式
后缀；每个文件的内容 SHA-256 仍独立保存。具体关联和实施方式留待后续分析，未获明确
实施指令前不得修改 state 或现有产品代码。后续只读审计确认历史库有 53 种 Garmin JSON
语义资源，但普通同步已使用较窄白名单；请求优化和历史 raw 删除尚未成为已确认需求。
已确认的未来同步边界为项目主体本地时间每日 12:00：只取昨日完整活动与非睡眠健康数据、
以及今日早晨结束并按醒来日归属的主睡眠；取消自动 14 日历史回读。数据不完整时只记录，
只有用户明确指定并批准日期后才补数。该要求目前只写入规划，尚未实施。
用户进一步确认未来 Garmin raw 使用 `health/` 与 `activities/` 两类业务证据：健康文件按
`日期-资源-内容哈希.json` 平铺，活动文件与同 activity hash 的天气 JSON 平铺；
`activity_inventory` 仅作为可重新初始化的数据库控制状态，不建立 collection 目录；
未来取消 `activity_summary`，活动只从 FIT/GPX/TCX 确定性重建。以上仍是规划，尚未实施。
用户确认未来重构时重置 `source/state/` 下除 `raw/` 外的全部旧运行状态，包括当前数据库，
且不迁移旧数据库内容；新数据库只从确认保留的健康 raw 与活动原始文件重建，inventory 等
控制状态重新初始化。该要求不授权现在删除 state，也不替代 raw 内部整理需求。
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
Garmin 写入。以上除报告 Skill 骨架外仍是需求规划，尚未实施运行替代。
`garmin-sync` 将通过本地 Garmin MCP，依据 SQLite 采集状态增量获取 activities/health raw
并同步状态；`gmail-sender` 使用本地 Gmail MCP 收取和发送邮件。六个 Skill 均采用脚本优先，
把可确定、可重复的工作放入各自 `scripts/`，以减少 Token 和运行差异。早期提议的
`data-build` 已从目标中移除；`training-coach` 自带
脚本按任务窗口解析 health JSON、FIT、GPX、TCX 与天气 raw，只向 AI 提供有界证据。
用户确认未来只设置两个 `cron + codex exec` 无状态流程：每日 12:00 依次运行
`garmin-sync → training-coach → training-report-publisher → gmail-sender`；每周日 12:00 依次
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
ADHOC-0011，并已通过全新高风险 Validator；尚未实施数据库或 state 变更。
用户确认正常日报只解析当前新增 raw，并复用 SQLite 中此前 14 份日总结；正常周报使用本周期
7 份日总结和此前 4 份周总结。历史 raw 仅在总结缺失、数据矛盾、缺少必要细节、需要复核 FIT
或用户明确要求时定向读取，不做无条件历史全窗口重算。日/周总结保存结构化 JSON 与文本；
报告和邮件 HTML 由 `training-report-publisher` 作为独立、哈希绑定的输出生成，并携带来源
raw/output ID 或 SHA-256。
