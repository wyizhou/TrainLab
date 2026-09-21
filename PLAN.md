# PLAN.md

- 总体状态：[exec]
- 总目标及确认依据：用户2026-09-15明确启动本地React/FastAPI Web、三小时Garmin同步、兼容AI接口、三模式Context，以及既有FIT/records/报告功能。ADHOC-0031承接系统集成，ADHOC-0024～0028保持原编号；B0～B7本地/合成范围已完成，历史失败、公共合同累计修复和环境恢复证据保留；最终B7独立验证通过，主Agent核快照并复跑pytest 196通过、Python/前端门禁及`git diff --check`通过。脚手架和旧CI交付已完成，PR #20随后经另行授权合并；旧M12及更早产品不自动恢复。
- 允许修改的范围：新产品位于source，依本次明确目标实现代码/Schema/Prompt/本地配置和测试并同步当前协调记录；保留四表、全文报告、完整采样、UTC及私人数据边界。不恢复旧工程，不改全局配置/仓库设置，不新增或主动运行远端CI。首次真实同步、AI实调用与留存按ADHOC-0031的待确认事项闭合后执行，不自动合并本功能PR。
- 整体验收标准：本次按ADHOC-0031用户目标及ADHOC-0024～0028已确认设计，在完整实施合同明确后做功能级和集成级本地独立验证、主验收及适用交付；未运行的实服务检查单列，不把规划、脚手架或Git成功当产品通过。ADHOC-0029/0030原合同、受验快照及历史结果不改写。

## 功能总览

| 编号 | 状态 | 功能与预期结果 | 验收标准 | 依赖 | 执行计划链接 |
| --- | --- | --- | --- | --- | --- |
| ADHOC-0035 | [exec] | 官方a313e63的README及完整项目角色适配；不保留旧.pi自定义 | H35-01～06；精确安装、实际接入、保护、独立及主验收与依赖PR | 用户完全替换.pi授权；基于PR #22头07cc516 | [执行计划](exec-plans/active/ADHOC-0035-agentsmd-role-adapter.md) |
| ADHOC-0034 | [completed] | 升级最新agentsmd并行Harness及项目技能，保留业务记录 | H34-01～07；来源/固定组合独立验证及主验收，不恢复业务 | 用户2026-09-20要求；[客观要求](exec-plans/evidence/ADHOC-0034/requirements.md) | [执行计划](exec-plans/completed/ADHOC-0034-agentsmd-parallel.md) |
| ADHOC-0029 | [completed] | 最新agentsmd及全部协调记录迁移，退出旧入口 | AC-01..10；本地迁移、独立复验与主验收通过 | 用户八项要求与本地分支授权 | [执行计划](exec-plans/completed/ADHOC-0029-agentsmd-upgrade.md) |
| ADHOC-0030 | [completed] | 旧CI退役，当前公开工作区已提交/推送并创建PR #20，不合并main | RC-0030-01 AC-01..06；独立与主验收通过，完整Git树与实际PR头核对完成 | 已完成迁移及用户新交付授权；沿用同一功能分支 | [执行计划](exec-plans/completed/ADHOC-0030-retire-ci-and-publish.md) |
| ADHOC-0031 | [completed] | 本机8080 Web/API、三小时同步、AI工具循环与三模式Context，接通既有FIT/报告功能 | U31-01～06；本地/合成完整正常/错误/边界、独立验证与主验收通过；真实外部检查单列未验证 | ADHOC-0024～0028；首次同步/AI配置/触发留存已确认 | [执行计划](exec-plans/completed/ADHOC-0031-local-web-system.md) |
| ADHOC-0032 | [exec] | Playwright Chrome Web验收、真实Garmin及认证维护；两区Web登录/2FA GUI、真实有界同步及既有Web/Context错误修复已通过；AI模型实测暂停 | AU32-01～06及GUI32-01～06：GUI完整操作/安全HTTP/维护生命周期须Chrome实际验证；Garmin有界同步/下载/入库及真实认证无证据不通过；AI继续暂停；既有Web/Context错误须修复并验证 | ADHOC-0031 PR #21；用户2026-09-18最新授权 | [执行计划](exec-plans/active/ADHOC-0032-real-garmin-and-web-e2e.md) |
| ADHOC-0023 | [exec] | FIT/报告当前决定及实施边界，非产品代码 | 不丢已批准设计、不猜未知项 | 用户已确认设计 | [执行计划](exec-plans/active/ADHOC-0023-fit-data-classification-discussion.md) |
| ADHOC-0024 | [completed] | activities十二列＋records四列，完整FIT入库 | 完整/缺失/顺序/事务；默认123；独立复验与主复核通过 | ADHOC-0023及目录/容量条件；ADHOC-0031 B0相关前置同批修复 | [执行计划](exec-plans/completed/ADHOC-0024-fit-sqlite-parser.md) |
| ADHOC-0025 | [completed] | 唯一get_running_records(activity_id)，只跑步返回全部采样 | 真实sport和本次作用域、只读/全量/超限明确失败；独立复验与主复核通过 | ADHOC-0024 | [执行计划](exec-plans/completed/ADHOC-0025-fit-running-query-tool.md) |
| ADHOC-0026 | [completed] | 本地tools README与唯一采样工具及本轮要求的受限资料读取一致 | 参数/返回/错误/权限与实际Schema一致；资料读取不开放任意文件；本阶段不冒称B5资料工具已接通；独立复验与主复核通过 | ADHOC-0024、ADHOC-0025、ADHOC-0031 Context接线 | [执行计划](exec-plans/completed/ADHOC-0026-tools-ai-index.md) |
| ADHOC-0027 | [completed] | activties_report：activity_id、运动start_time_utc、全文本summary | 关联活动/运动时间、全文保真、失败回滚；独立复验与主复核通过 | ADHOC-0024 | [执行计划](exec-plans/completed/ADHOC-0027-activity-ai-report.md) |
| ADHOC-0028 | [completed] | weekly_report：自增id、run_time_utc、全文本summary | 实际T往前七天、多活动总结、统一时间锚；独立复验与主复核通过 | ADHOC-0024、ADHOC-0027；本轮明确由程序取七天运动总结给Context | [执行计划](exec-plans/completed/ADHOC-0028-weekly-ai-report.md) |

## 当前关注

- 当前唯一任务（2026-09-21）：ADHOC-0035。候选及原实际工作区已安装同版7文件；三角色实际接入、最终两组合独立验证及主完整本地验收已接受，主上下文由主直接核（不冒称子独立取证）。准备15项最小增量提交/推送，尚未交付本功能PR。业务仍暂停；本分支仅增加适配和必要记录，不复制原工作区ADHOC-0033源码或整份业务计划。依赖PR #22仍未合并；无自动合并/远端CI授权。下方记录保留原基准状态，不是继续旧任务的指令。详细进度见本功能执行计划。
- 前轮任务（2026-09-20）：ADHOC-0034升级官方37520a5脚手架。8文件候选已正式交回并由主核对，主已构造C34/Cuse及各自最小记录增量，完整交接材料已由全新Validator复验及主亲验通过，同版Harness已受控落到原实际目录；已单独交付[PR #22](https://github.com/wyizhou/TrainLab/pull/22)，未合并，本计划已归档。下一步等待用户确认合并或新需求，不自动恢复旧业务。原用户工作区的ADHOC-0033及其未提交产品/证据继续暂停保护，不将其源码或整份计划带入本分支。此分支基于实际已合并PR21的origin/main af09e3f；下方旧关注/状态保留基准当时记录，不是继续执行或重复合并的指令。详细进度以本功能执行计划为准。
- 当前关注：ADHOC-0032基础认证模块及两区Web登录/2FA/运行期维护GUI已完成独立验证、主Agent实际Chrome验收与本机页面交付；用户已在正式GUI完成真实认证。2026-09-18主Agent继续原授权有界Garmin检查：CLI可重载持久认证，`maintain --once`退出0且未到刷新期，`sync-once`退出0，最近7天下载5个真实FIT并入库，activities=5、records=22995；G2、T2、T9已完成。随后用户授权修复两个既有Context/资料问题AU32-V1-002/003，已修复并通过主Agent补充验收：目标10项、web+ai 62项、全量pytest 326项、ruff、非editable mypy、前端14项/typecheck/build、默认Chrome2项和认证Chrome24项均通过；环境失败记录保留。PR #21已更新到`4126ead`并评论交付，GitHub显示可干净合并；G3及整体功能仍[exec]，等待用户确认无问题后转入AI相关。AI继续暂停，未合并PR #21。
- 已确认事项：首次同步最近七天，UTC日期+FIT字节SHA命名；AI私有配置在states/ai.json，允许真实请求且数据不限、暂不设上限；活动总结中国时区每日凌晨4点自动触发，允许新增配置表，无活动周总结入库`本周无任何运动记录`，多轮历史仅内存。2026-09-18用户进一步确认：每日进程按上次状态补齐到当前的所有空缺活动总结；周报按中国时区每周日15:00执行，窗口为上周日15:00到本周日15:00，周报前先运行一次同类运动总结补跑且不与定时进程冲突；第一个版本不做分段查询和records配额，AI需要时给对应running活动全量records。不重问四表/UTC/全量records、Garmin指定认证文件使用或按需龙豆资料读取。
- 整体暂停原因：临时整体暂停已解除；AI仍单独暂停。认证基础模块、本地Web GUI、真实有界Garmin同步和两个既有Web/Context错误修复均已通过；PR已更新且可干净合并，等待用户确认无问题后进入AI相关，不预写合并通过。
- 恢复条件：安全GUI、真实Garmin有界检查和AU32-V1-002/003修复已满足，PR #21已更新；下一步由用户确认本PR无问题后开始AI相关。任何产品后续改动仍须全新独立验证。AI参数与实调用待用户确认，合并另行确认。

## 项目已有边界与当前设计

- 四类不变：基本情况、整场FIT摘要、原生lap/split/set、设备与采样。所有受支持单项运动默认给AI第1/2/3类；铁三排除，只有真实sport=running可调用唯一采样工具，子类不设白名单。
- states/data.db为目标库，共四张业务表；SQLite自增系统表不是业务元数据表。所有绝对时刻字段存UTC，显示时转换用户时区；时长/偏移不是时区时间。已有Schema与合成SQLite入库检查，未创建正式数据库或完成实际工具/API业务接线。
- activities十二列、records四列及联合键/原顺序、完整解析与合法缺失不造值已确认；不恢复被否决的has_running、parse_status、session_count、parser_version、data_revision、quality_json。
- activties_report保留用户拼写，运动开始时间与AI生成时间不同；weekly_report自增id＋实际run_time_utc＋全文本summary，覆盖T往前七天，不再用活动ID/自然周键。summary不替代FIT事实summary_json。
- 根只承载开发Harness/Git元数据，source仍为唯一产品工程。本次采用source内产品模块/脚本、前端和工具索引，不申请根tools例外；前端构建直接输出后端专用web目录，不恢复集中source/src、source/index.py或旧发布bundle/dist层。
- 不恢复orchestrate-parallel-work、旧控制面或旧runner。不安装/复制项目技能到仓库外，不改全局配置；用户另行指定的操作另行明确。references仅按用户主动专题请求维护，不自动沉淀普通开发结论。
- FIT、GPS、数据库、raw、报告、目标、凭据/Token及私人配置不进入Git。states仅放行三个.gitkeep和虚构Goal-example.md。测试用合成数据；正式FIT/Goal/凭据及业务Provider另按精确授权，不因脚手架升级读取。
- Gmail仍只用官方REST，本轮不增加邮件/健康/训练写入。Garmin按本次明确目标使用指定认证文件、检查新活动和可用认证刷新；首次真实下载范围尚待确定，刷新需要人工登录/MFA时明确提示，不猜凭据、不绕过验证，不继承历史外部动作许可。
- 旧CI的source依赖/测试入口已被用户删除；唯一旧workflow已在ADHOC-0030按用户授权删除，不新增或主动运行远端CI，不把缺失检查当通过。新实现沿用Python3.12/pytest/Ruff/mypy并同批落实适用本地测试/配置，不能以删弱断言换绿灯。
- 新开发协作只按当前AGENTS与角色模板。旧Failure Analyst、强制八字段、多层状态和旧每模块自动推送等开发协议不再生效；历史受审合同仅作证据，不能拼接为当前新要求。
- 根README为用户要求原样采用的上游通用说明及MIT许可，不表示TrainLab全部历史产品以MIT重新许可；旧来源和许可原文在公开历史快照保全。

## 历史功能与未结束事项（非当前执行队列）

以下按新模板状态展示原事实：只有原范围完成才记[completed]；已取消/暂停的已启动任务记[exec]，原未执行的M11-0019交接保留[plan]，均注明停止原因，不改判为通过、不重新纳入待办。历史后置Git未核实的ADHOC-0016单列暂停。原阶段/任务与问题编号、源验收/失败全文可从各执行计划证据索引读取。

| 编号 | 状态 | 功能与预期结果 | 验收标准 | 依赖 | 执行计划链接 |
| --- | --- | --- | --- | --- | --- |
| ADHOC-0018 | [exec] | ADHOC-0018：data精简与FIT按运动年份命名；旧清理最后验收为INCONCLUSIVE，未完成。用户已改用states/activities，旧路线不恢复。 | 原授权范围/原验收结论，见原件；不是本次复验 | 原私人保全基准缺失/删除后无法补证；没有恢复旧清理任务授权。 | [执行计划](exec-plans/active/ADHOC-0018-data-fit-year-cleanup.md) |
| M12 | [exec] | M12：新旧系统收敛与 FIT-only 每周系统；原M12实现/验收曾开展，现因用户转向直接API而暂停。 | 原授权范围/原验收结论，见原件；不是本次复验 | 旧产品源码由用户删除；不续跑旧CLI、R7、模型或外部动作。 | [执行计划](exec-plans/active/M12-fit-weekly-0001-rebuild.md) |
| ADHOC-0001 | [completed] | 升级并严格适配 agentForge 0.4.2；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 | 原授权范围/原验收结论，见原件；不是本次复验 | 历史前置条件保留于原件 | [执行计划](exec-plans/completed/ADHOC-0001-agentforge-0.4.2-upgrade.md) |
| ADHOC-0002 | [completed] | 审计并精简 TrainLab 根目录生成物与辅助目录；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 | 原授权范围/原验收结论，见原件；不是本次复验 | 历史前置条件保留于原件 | [执行计划](exec-plans/completed/ADHOC-0002-repository-root-cleanup.md) |
| ADHOC-0003 | [completed] | 删除根目录无用生成物和崩溃文件；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 | 原授权范围/原验收结论，见原件；不是本次复验 | 历史前置条件保留于原件 | [执行计划](exec-plans/completed/ADHOC-0003-generated-and-crash-artifact-cleanup.md) |
| ADHOC-0004 | [completed] | 厘清辅助目录职责并迁移第三方许可声明；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 | 原授权范围/原验收结论，见原件；不是本次复验 | 历史前置条件保留于原件 | [执行计划](exec-plans/completed/ADHOC-0004-support-directory-classification.md) |
| ADHOC-0005 | [completed] | Gmail 与 Garmin 认证健康检查；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 | 原授权范围/原验收结论，见原件；不是本次复验 | 历史前置条件保留于原件 | [执行计划](exec-plans/completed/ADHOC-0005-authentication-health-check.md) |
| ADHOC-0006 | [completed] | 同步已验证的 Garmin token；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 | 原授权范围/原验收结论，见原件；不是本次复验 | 历史前置条件保留于原件 | [执行计划](exec-plans/completed/ADHOC-0006-garmin-token-sync.md) |
| ADHOC-0007 | [exec] | 增量更新、补发日报周计划并监测 12 小时；用户已取消/替代的历史任务；已发生的局部成果和失败保留，取消不等于完整验收通过。 | 原授权范围/原验收结论，见原件；不是本次复验 | 已取消，不纳入当前待办；只有用户另行改变目标并授权才可重新规划。 | [执行计划](exec-plans/active/ADHOC-0007-production-backfill-and-monitor.md) |
| ADHOC-0008 | [completed] | 简化 TrainLab 仓库并形成单一可部署产物；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 | 原授权范围/原验收结论，见原件；不是本次复验 | 历史前置条件保留于原件 | [执行计划](exec-plans/completed/ADHOC-0008-runtime-bundle-and-repository-simplification.md) |
| ADHOC-0009 | [completed] | source 开发、数据与数据库来源审计；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 | 原授权范围/原验收结论，见原件；不是本次复验 | 历史前置条件保留于原件 | [执行计划](exec-plans/completed/ADHOC-0009-source-data-provenance-audit.md) |
| ADHOC-0010 | [completed] | raw 目录分层与用途审计；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 | 原授权范围/原验收结论，见原件；不是本次复验 | 历史前置条件保留于原件 | [执行计划](exec-plans/completed/ADHOC-0010-raw-directory-taxonomy-audit.md) |
| ADHOC-0011 | [completed] | 需求草案：source 运行结构、Skills 与 state 数据整理；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 | 原授权范围/原验收结论，见原件；不是本次复验 | 历史前置条件保留于原件 | [执行计划](exec-plans/completed/ADHOC-0011-state-raw-retention-and-tuning.md) |
| ADHOC-0012 | [completed] | 当前运行架构完成度与技术债审计；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 | 原授权范围/原验收结论，见原件；不是本次复验 | 历史前置条件保留于原件 | [执行计划](exec-plans/completed/ADHOC-0012-current-runtime-tech-debt-audit.md) |
| ADHOC-0013 | [completed] | Garmin/Gmail MCP 与运行适配状态核对；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 | 原授权范围/原验收结论，见原件；不是本次复验 | 历史前置条件保留于原件 | [执行计划](exec-plans/completed/ADHOC-0013-mcp-and-runtime-adapter-audit.md) |
| ADHOC-0014 | [completed] | M9 本地完整交付；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 | 原授权范围/原验收结论，见原件；不是本次复验 | 历史前置条件保留于原件 | [执行计划](exec-plans/completed/ADHOC-0014-m9-local-delivery.md) |
| ADHOC-0015 | [completed] | 升级 agentForge v0.4.4 并迁移 M11 诊断状态；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 | 原授权范围/原验收结论，见原件；不是本次复验 | 历史前置条件保留于原件 | [执行计划](exec-plans/completed/ADHOC-0015-agentforge-0.4.4-upgrade.md) |
| ADHOC-0016 | [exec] | 适配 agentForge 最新开发脚手架；原记录仅确认治理实现与独立验证；归档时后置提交/推送尚未核实。原completed表述的适用范围不扩大。 | 原授权范围/原验收结论，见原件；不是本次复验 | 历史后置Git交付缺少本文件内核实结果；不恢复推送，不改判原治理PASS。 | [执行计划](exec-plans/active/ADHOC-0016-agentforge-governance-update.md) |
| ADHOC-0017 | [completed] | CONSOLIDATE-20260914：单目录整合与 API 改造前旧版基线；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 | 原授权范围/原验收结论，见原件；不是本次复验 | 历史前置条件保留于原件 | [执行计划](exec-plans/completed/ADHOC-0017-consolidate-pre-api-baseline.md) |
| ADHOC-0019 | [completed] | ADHOC-0019：Goal保留、主目录检查点及采用next代码；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 | 原授权范围/原验收结论，见原件；不是本次复验 | 历史前置条件保留于原件 | [执行计划](exec-plans/completed/ADHOC-0019-adopt-next-before-api.md) |
| ADHOC-0020 | [completed] | ADHOC-0020：记录 states / activities 数据目录决策；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 | 原授权范围/原验收结论，见原件；不是本次复验 | 历史前置条件保留于原件 | [执行计划](exec-plans/completed/ADHOC-0020-states-activities-decisions.md) |
| ADHOC-0021 | [completed] | Garmin FIT 官方解析资料整理；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 | 原授权范围/原验收结论，见原件；不是本次复验 | 历史前置条件保留于原件 | [执行计划](exec-plans/completed/ADHOC-0021-garmin-fit-reference.md) |
| ADHOC-0022 | [completed] | 龙豆传感器资料与真实跑步 FIT 对照；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 | 原授权范围/原验收结论，见原件；不是本次复验 | 历史前置条件保留于原件 | [执行计划](exec-plans/completed/ADHOC-0022-longdou-real-fit-reference.md) |
| M1-0001 | [completed] | install the agentForge development Harness；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 | 原授权范围/原验收结论，见原件；不是本次复验 | 历史前置条件保留于原件 | [执行计划](exec-plans/completed/M1-agentforge-migration-0001-development-harness.md) |
| M1-0002 | [completed] | move the sole TrainLab product source into product/；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 | 原授权范围/原验收结论，见原件；不是本次复验 | 历史前置条件保留于原件 | [执行计划](exec-plans/completed/M1-product-root-0002-source-migration.md) |
| M1-0003 | [completed] | move local runtime data and switch product root；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 | 原授权范围/原验收结论，见原件；不是本次复验 | 历史前置条件保留于原件 | [执行计划](exec-plans/completed/M1-runtime-root-0003-data-switch.md) |
| M10-0001..M10-0005 | [completed] | M10 滚动七日真实端到端验收；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 | 原授权范围/原验收结论，见原件；不是本次复验 | 历史前置条件保留于原件 | [执行计划](exec-plans/completed/M10-live-e2e-0001-rolling-week.md) |
| M11-0015 | [completed] | M11 v3 八封 Gmail 真实投递；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 | 原授权范围/原验收结论，见原件；不是本次复验 | 历史前置条件保留于原件 | [执行计划](exec-plans/completed/M11-email-presentation-0001-readable-cid-r01.md) |
| M11-0016..M11-0019 | [exec] | M11 v4 内容优先日报、技术周报与固定周计划；用户已取消/替代的历史任务；已发生的局部成果和失败保留，取消不等于完整验收通过。 | 原授权范围/原验收结论，见原件；不是本次复验 | 已取消，不纳入当前待办；只有用户另行改变目标并授权才可重新规划。 | [执行计划](exec-plans/active/M11-email-presentation-0001-readable-cid-r02.md) |
| M11-0001..M11-0014 | [completed] | 人类可读日报/周报与私有 CID 图表闭环；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 | 原授权范围/原验收结论，见原件；不是本次复验 | 历史前置条件保留于原件 | [执行计划](exec-plans/completed/M11-email-presentation-0001-readable-cid.md) |
| M2-0001 | [completed] | 将 TrainLab 完整迁移到 agentForge 0.4.2 根项目布局；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 | 原授权范围/原验收结论，见原件；不是本次复验 | 历史前置条件保留于原件 | [执行计划](exec-plans/completed/M2-agentforge-root-layout-0001-project-migration.md) |
| M3-0001 | [completed] | 用合成 FIT 夹具替代私人 test_data；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 | 原授权范围/原验收结论，见原件；不是本次复验 | 历史前置条件保留于原件 | [执行计划](exec-plans/completed/M3-test-fixtures-0001-synthetic-fit-migration.md) |
| M4 | [completed] | M4 `source/` 工程、健康数据重建与教练 Harness v2；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 | 原授权范围/原验收结论，见原件；不是本次复验 | 历史前置条件保留于原件 | [执行计划](exec-plans/completed/M4-source-root-0001-product-consolidation.md) |
| M5 | [completed] | M5 自适应教练画像与本地报告校准；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 | 原授权范围/原验收结论，见原件；不是本次复验 | 历史前置条件保留于原件 | [执行计划](exec-plans/completed/M5-adaptive-coaching-0001-profile-and-preview.md) |
| M6 | [exec] | M6 活动证据一致性与真实报告预览（已被 ADHOC-0011 取代）；用户已取消/替代的历史任务；已发生的局部成果和失败保留，取消不等于完整验收通过。 | 原授权范围/原验收结论，见原件；不是本次复验 | 已取消，不纳入当前待办；只有用户另行改变目标并授权才可重新规划。 | [执行计划](exec-plans/active/M6-activity-evidence-0001-lifecycle-and-preview.md) |
| M7 | [completed] | M7 AI + Skills 执行闭环与双层测试体系；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 | 原授权范围/原验收结论，见原件；不是本次复验 | 历史前置条件保留于原件 | [执行计划](exec-plans/completed/M7-ai-skills-0001-runtime-closure.md) |
| M8 | [completed] | M8 真实私人数据离线 AI 教练闭环；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 | 原授权范围/原验收结论，见原件；不是本次复验 | 历史前置条件保留于原件 | [执行计划](exec-plans/completed/M8-real-data-0001-ai-coach-closure.md) |
| M9-0001..M9-0005 | [completed] | M9 单日 Garmin MCP 有界真实只读闭环；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 | 原授权范围/原验收结论，见原件；不是本次复验 | 历史前置条件保留于原件 | [执行计划](exec-plans/completed/M9-garmin-live-0001-bounded-daily-sync.md) |

## 原Roadmap阶段与叶子任务迁移

保留PLANS中全部既有叶子编号、目标、依赖和取消事实。这里只是历史范围登记，不恢复被替代的目标、旧代码/外部调用或原自动Git交付方式；其余原批准范围全文在[历史快照](exec-plans/evidence/ADHOC-0029/history.zip)的PLANS.md条目及[映射清单](exec-plans/evidence/ADHOC-0029/roadmap-mapping.json)中保全。

| 编号 | 状态 | 功能与预期结果 | 验收标准 | 依赖 | 执行计划链接 |
| --- | --- | --- | --- | --- | --- |
| M12-0001 | [completed] | M12-0001 保护检查点、冻结与统一归档：检查点及恢复归档完成；旧入口退役/测试映射独立PASS；旧物理代码随替代模块迁移 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | 用户批准 | [执行计划](exec-plans/active/M12-fit-weekly-0001-rebuild.md) |
| M12-0002 | [completed] | M12-0002 FIT 新库与同步：内部新库/导入/分页/同步恢复已独立PASS并推送；真实全历史同步留0006 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M12-0001 | [执行计划](exec-plans/active/M12-fit-weekly-0001-rebuild.md) |
| M12-0003 | [exec] | M12-0003 解析与 AI 边界及旧系统收敛：0003a–m已交付；VC-005首批资源/周输入/安全接替双平台3049项及独立验收PASS，提交推送/CI与其余旧CLI退出待完成；旧M9失败原因未确定并永久保留 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M12-0002 | [执行计划](exec-plans/active/M12-fit-weekly-0001-rebuild.md) |
| M12-0004 | [plan] | M12-0004 周分析与发布：固定跑步计划、Markdown/PDF、Gmail REST/Garmin | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M12-0003 | [执行计划](exec-plans/active/M12-fit-weekly-0001-rebuild.md) |
| M12-0005 | [plan] | M12-0005 Python 调度与离线验收：定时、补发、恢复、完整独立验收 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M12-0004 | [执行计划](exec-plans/active/M12-fit-weekly-0001-rebuild.md) |
| M12-0006 | [plan] | M12-0006 真实验收与切换：历史同步及下个正常周日真实闭环、正式切换 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M12-0005 | [执行计划](exec-plans/active/M12-fit-weekly-0001-rebuild.md) |
| M1-0001 | [completed] | M1-0001 落地开发 Harness：根治理文件；旧 `.orchestration` 清理 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | none | [执行计划](exec-plans/completed/M1-agentforge-migration-0001-development-harness.md) |
| M1-0002 | [completed] | M1-0002 建立唯一产品源码：`product/`、CI、构建工具 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M1-0001 | [执行计划](exec-plans/completed/M1-product-root-0002-source-migration.md) |
| M1-0003 | [completed] | M1-0003 迁移运行数据并切换根路径：本地 state/config/logs、LaunchAgent 路径 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M1-0002 | [执行计划](exec-plans/completed/M1-runtime-root-0003-data-switch.md) |
| M2-0001 | [completed] | M2-0001 将 TrainLab 完整迁移到 agentForge 根项目布局：`product/` → 根项目树；治理、CI、构建、本地运行路径 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M1、ADHOC-0001 | [执行计划](exec-plans/completed/M2-agentforge-root-layout-0001-project-migration.md) |
| M3-0001 | [completed] | M3-0001 用合成 FIT 夹具替代私人 test_data：`tests/fixtures/`、7 个 Garmin 测试模块、测试支持代码、`test_data/` 清理 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M2 | [执行计划](exec-plans/completed/M3-test-fixtures-0001-synthetic-fit-migration.md) |
| M4-0001 | [completed] | M4-0001 source 工程与历史运行层清理：`source/`、CI、ignore、旧 Orchestration 清理 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M3、ADHOC-0008 | [执行计划](exec-plans/completed/M4-source-root-0001-product-consolidation.md) |
| M4-0002 | [completed] | M4-0002 Foundation v4 离线 Garmin 重建：`source/tools`、候选 state、`data-backup` 归档 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M4-0001 | [执行计划](exec-plans/completed/M4-source-root-0001-product-consolidation.md) |
| M4-0003 | [completed] | M4-0003 运行时教练 Harness v2 与课程合同：`source/src/resources/harness`、analysis 合同/测试 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M4-0002 | [执行计划](exec-plans/completed/M4-source-root-0001-product-consolidation.md) |
| M4-0004 | [completed] | M4-0004 原子切换私人数据与独立验收：source 实例入口、验证证据、计划归档 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M4-0003 | [执行计划](exec-plans/completed/M4-source-root-0001-product-consolidation.md) |
| M5-0001 | [completed] | M5-0001 保存 M4 单一本地基线：Git 基线提交 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M4 | [执行计划](exec-plans/completed/M5-adaptive-coaching-0001-profile-and-preview.md) |
| M5-0002 | [completed] | M5-0002 AI 教练画像管理与确认应用：`source/src/coaching`、CLI、私有 profile state、画像测试 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M5-0001 | [执行计划](exec-plans/completed/M5-adaptive-coaching-0001-profile-and-preview.md) |
| M5-0003 | [completed] | M5-0003 动态周容量与排课合同：`source/src/analysis`、运行时 schema、容量/排课测试 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M5-0002 | [执行计划](exec-plans/completed/M5-adaptive-coaching-0001-profile-and-preview.md) |
| M5-0004 | [completed] | M5-0004 隔离数据库报告预览：`source/src/analysis`、预览 CLI、隔离预览测试 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M5-0003 | [执行计划](exec-plans/completed/M5-adaptive-coaching-0001-profile-and-preview.md) |
| M6-0001 | [exec] | M6-0001 保存 M5 单一本地基线：本地 Git 提交 | 历史范围；不自动恢复。已取消/替代，非当前待办。原批准标准原文保留，不重判历史。 | M5 | [执行计划](exec-plans/active/M6-activity-evidence-0001-lifecycle-and-preview.md) |
| M6-0002 | [exec] | M6-0002 审计并统一 inventory 生命周期证据：`source/src/garmin`、`source/tools`、生命周期测试 | 历史范围；不自动恢复。已取消/替代，非当前待办。原批准标准原文保留，不重判历史。 | M6-0001 | [执行计划](exec-plans/active/M6-activity-evidence-0001-lifecycle-and-preview.md) |
| M6-0003 | [exec] | M6-0003 candidate 离线修复与完整性验证：candidate-only 数据工具和测试 | 历史范围；不自动恢复。已取消/替代，非当前待办。原批准标准原文保留，不重判历史。 | M6-0002 | [执行计划](exec-plans/active/M6-activity-evidence-0001-lifecycle-and-preview.md) |
| M6-0004 | [exec] | M6-0004 真实周报、日报和 HTML/JSON 预览：candidate-only 预览证据和测试 | 历史范围；不自动恢复。已取消/替代，非当前待办。原批准标准原文保留，不重判历史。 | M6-0003 | [执行计划](exec-plans/active/M6-activity-evidence-0001-lifecycle-and-preview.md) |
| ADHOC-0011-0001 | [completed] | ADHOC-0011-0001 保存当前 M6 工作区保护提交：Git 本地保护提交 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M6 | [执行计划](exec-plans/completed/ADHOC-0011-state-raw-retention-and-tuning.md) |
| ADHOC-0011-0002 | [completed] | ADHOC-0011-0002 建立 source Harness、Skills、模板和 SQLite 工具：`source/AGENTS.md`、`source/skills`、模板、共享脚本、SQLite Schema | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | ADHOC-0011-0001 | [执行计划](exec-plans/completed/ADHOC-0011-state-raw-retention-and-tuning.md) |
| ADHOC-0011-0003 | [completed] | ADHOC-0011-0003 candidate raw 重组和新数据库建立：仓库外 candidate、脱敏迁移收据 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | ADHOC-0011-0002 | [执行计划](exec-plans/completed/ADHOC-0011-state-raw-retention-and-tuning.md) |
| ADHOC-0011-0004 | [completed] | ADHOC-0011-0004 归档旧 state、原子切换和离线验证：`data-backup` 归档、`source/state`、只读 cron 配置 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | ADHOC-0011-0003 | [执行计划](exec-plans/completed/ADHOC-0011-state-raw-retention-and-tuning.md) |
| M7-0001 | [completed] | M7-0001 保存基线并更新测试治理：本地基线提交、A-009、AGENTS/CI/计划 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | ADHOC-0011 | [执行计划](exec-plans/completed/M7-ai-skills-0001-runtime-closure.md) |
| M7-0002 | [completed] | M7-0002 状态合同与唯一自动入口：`source/skills/_shared`、SQLite 测试 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M7-0001 | [执行计划](exec-plans/completed/M7-ai-skills-0001-runtime-closure.md) |
| M7-0003 | [completed] | M7-0003 六个 Skills 离线业务闭环：Skill 脚本、schemas、candidate-only workflow | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M7-0002 | [执行计划](exec-plans/completed/M7-ai-skills-0001-runtime-closure.md) |
| M7-0004 | [completed] | M7-0004 code 与 AI 双层测试：`source/tests/code`、`source/tests/ai` | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M7-0003 | [执行计划](exec-plans/completed/M7-ai-skills-0001-runtime-closure.md) |
| M7-0005 | [completed] | M7-0005 独立验证与第二个本地提交：验证收据、最终本地提交、计划归档 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M7-0004 | [执行计划](exec-plans/completed/M7-ai-skills-0001-runtime-closure.md) |
| M8-0001 | [completed] | M8-0001 冻结基线、Roadmap 与反绿灯规则：Roadmap、active exec plan、治理记录 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M7 | [执行计划](exec-plans/completed/M8-real-data-0001-ai-coach-closure.md) |
| M8-0002 | [completed] | M8-0002 真实健康/活动解析与片段证据：`source/skills`、Schemas、code tests | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M8-0001 | [执行计划](exec-plans/completed/M8-real-data-0001-ai-coach-closure.md) |
| M8-0003 | [completed] | M8-0003 真正 AI 日报/周报提交与幂等：`source/skills`、AI tests | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M8-0002 | [执行计划](exec-plans/completed/M8-real-data-0001-ai-coach-closure.md) |
| M8-0004 | [completed] | M8-0004 Candidate 真实日期闭环：仓库外 candidate、私有报告 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M8-0003 | [执行计划](exec-plans/completed/M8-real-data-0001-ai-coach-closure.md) |
| M8-0005 | [completed] | M8-0005 Code、AI、数据/隐私独立验证：验证证据、计划回写 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M8-0004 | [执行计划](exec-plans/completed/M8-real-data-0001-ai-coach-closure.md) |
| M9-0001 | [completed] | M9-0001 保存 M8 本地基线：本地 Git 提交 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M8 | [执行计划](exec-plans/completed/M9-garmin-live-0001-bounded-daily-sync.md) |
| M9-0002 | [completed] | M9-0002 Garmin MCP 有界只读采集器：`source/skills/garmin-sync`、共享 Schema、code tests | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M9-0001 | [执行计划](exec-plans/completed/M9-garmin-live-0001-bounded-daily-sync.md) |
| M9-0003 | [completed] | M9-0003 冻结在线范围与离线预验：fake MCP、预算/Token/幂等验证 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M9-0002 | [执行计划](exec-plans/completed/M9-garmin-live-0001-bounded-daily-sync.md) |
| M9-0004 | [completed] | M9-0004 Candidate 真实采集与离线日报：r04 真实只读采集、r07 公开 canary、唯一 attempt 4、日报/报告/receipt 与幂等重放 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M9-0003 | [执行计划](exec-plans/completed/M9-garmin-live-0001-bounded-daily-sync.md) |
| M9-0005 | [completed] | M9-0005 Code、AI、数据/隐私独立验证：207 项代码门与三类全新只读 Validator 均 PASS；正式 state/Token 不变、外部动作 0 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M9-0004 | [执行计划](exec-plans/completed/M9-garmin-live-0001-bounded-daily-sync.md) |
| M10-0001 | [completed] | M10-0001 冻结治理、窗口与外部预算：Roadmap、exec plan、运行合同 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M9 | [执行计划](exec-plans/completed/M10-live-e2e-0001-rolling-week.md) |
| M10-0002 | [completed] | M10-0002 七日 Candidate 补数和完整报告闭环：Garmin sync、教练/报告运行器、Schemas、Candidate | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M10-0001 | [执行计划](exec-plans/completed/M10-live-e2e-0001-rolling-week.md) |
| M10-0003 | [completed] | M10-0003 Gmail/Garmin 外部动作执行器与离线验证：Gmail/GTS Skills、共享状态、code tests | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M10-0002 | [执行计划](exec-plans/completed/M10-live-e2e-0001-rolling-week.md) |
| M10-0004 | [completed] | M10-0004 精确写入确认、真实发送和 Workout 生命周期：Garmin测试生命周期完成且残留0；r07旧标题8封和r08更正标题8封全部闭合，累计16封 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M10-0003 | [执行计划](exec-plans/completed/M10-live-e2e-0001-rolling-week.md) |
| M10-0005 | [completed] | M10-0005 AI、数据/隐私与清理独立验收：Code、AI、Delivery/Data-Privacy最终Validator均PASS；正式state/Token和重放闭合 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M10-0004 | [执行计划](exec-plans/completed/M10-live-e2e-0001-rolling-week.md) |
| M11-0001 | [completed] | M11-0001 保存 M10 基线并冻结设计与治理：本地基线提交、A-013、设计快照、Roadmap/exec plan | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M10 | [执行计划](exec-plans/completed/M11-email-presentation-0001-readable-cid.md) |
| M11-0002 | [completed] | M11-0002 建立日报/周报 ViewModel 与可读模板：`training-report-publisher`、Schemas、模板、映射测试 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M11-0001 | [执行计划](exec-plans/completed/M11-email-presentation-0001-readable-cid.md) |
| M11-0003 | [completed] | M11-0003 建立 CID MIME v2 与通用 Fake 投递路径：`gmail-sender`、MIME/RAW 验证、Fake REST 测试 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M11-0002 | [执行计划](exec-plans/completed/M11-email-presentation-0001-readable-cid.md) |
| M11-0004 | [completed] | M11-0004 真实 Candidate 私有预览与完整质量门：仓库外 owner-only 预览、视觉/隐私/幂等验证 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M11-0003 | [执行计划](exec-plans/completed/M11-email-presentation-0001-readable-cid.md) |
| M11-0005 | [completed] | M11-0005 三类独立验证并停在 canary 授权前：Code、Visual、Data/Privacy Validator 全部PASS；等待另行授权真实canary | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M11-0004 | [执行计划](exec-plans/completed/M11-email-presentation-0001-readable-cid.md) |
| M11-0006 | [completed] | M11-0006 真实 Gmail 样式 canary 与收口：历史RAW/HTML/text/CID技术闭合；内容失败证据保留并由v2/v3替代 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M11-0005 | [执行计划](exec-plans/completed/M11-email-presentation-0001-readable-cid.md) |
| M11-0007 | [completed] | M11-0007 冻结 Coaching Utility v2 治理和设计合同：A-015、设计章程、Skills/AGENTS、Design Validator | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M11-0006 | [执行计划](exec-plans/completed/M11-email-presentation-0001-readable-cid.md) |
| M11-0008 | [completed] | M11-0008 v2 证据、AI、课程与安全合同：用户授权统一读者自由文本心率处方门 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M11-0007 | [执行计划](exec-plans/completed/M11-email-presentation-0001-readable-cid.md) |
| M11-0009 | [completed] | M11-0009 v2 日报/周报 ViewModel 与渲染：用户授权工程字段显示白名单闭包 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M11-0008 | [执行计划](exec-plans/completed/M11-email-presentation-0001-readable-cid.md) |
| M11-0010 | [completed] | M11-0010 七日报一周报私有离线验收：owner-only Candidate、最多9次Codex、三类Validator、用户审核 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M11-0009 | [执行计划](exec-plans/completed/M11-email-presentation-0001-readable-cid.md) |
| M11-0011 | [completed] | M11-0011 冻结 v3 设计一致性与历史分区展示边界：A-016、交接/解析/验收只读审计 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M11-0010 | [执行计划](exec-plans/completed/M11-email-presentation-0001-readable-cid.md) |
| M11-0012 | [completed] | M11-0012 建立展示证据与共享 OpenDesign 渲染引擎：五项Schema、FIT/睡眠解析、日报/周报View与共享渲染 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M11-0011 | [执行计划](exec-plans/completed/M11-email-presentation-0001-readable-cid.md) |
| M11-0013 | [completed] | M11-0013 生成七日报一周报 v3 离线 Candidate：owner-only Candidate、真实图表、672/375px逐组件验收 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M11-0012 | [执行计划](exec-plans/completed/M11-email-presentation-0001-readable-cid.md) |
| M11-0014 | [completed] | M11-0014 v3 三类独立验证与离线交付：r06 Code、Design-Fidelity、Data/Privacy Validator全部PASS | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M11-0013 | [执行计划](exec-plans/completed/M11-email-presentation-0001-readable-cid.md) |
| M11-0015 | [completed] | M11-0015 v3七日报一周报真实Gmail投递：版本化8项Live Candidate、REST串行投递、RAW/CID与最终独立验收全部PASS | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M11-0014 | [执行计划](exec-plans/completed/M11-email-presentation-0001-readable-cid-r01.md) |
| M11-0016 | [completed] | M11-0016 冻结内容优先治理与日期/安全合同：A-018、AGENTS/Skills、内容与技术矩阵；全新最终Contract Validator PASS | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M11-0015 | [执行计划](exec-plans/active/M11-email-presentation-0001-readable-cid-r02.md) |
| M11-0017 | [completed] | M11-0017 建立全量观察证据、新版AI与固定课表合同：Contract与Closure Code Validator均PASS；869项及全部静态门独立闭合 | 历史范围；不自动恢复。原批准标准原文保留，不重判历史。 | M11-0016 | [执行计划](exec-plans/active/M11-email-presentation-0001-readable-cid-r02.md) |
| M11-0018 | [exec] | M11-0018 生成Markdown、低保真HTML与真实周报预览：用户批准 M12 替代；r19 业务校验失败/私人调用0历史保留，不改写为成功 | 历史范围；不自动恢复。已取消/替代，非当前待办。原批准标准原文保留，不重判历史。 | M11-0017 | [执行计划](exec-plans/active/M11-email-presentation-0001-readable-cid-r02.md) |
| M11-0019 | [plan] | M11-0019 内容/信息架构/数据隐私验证与OpenDesign交接：用户批准 M12 替代，未执行的旧交接不再续跑 | 历史范围；不自动恢复。已取消/替代，非当前待办。原批准标准原文保留，不重判历史。 | M11-0018 | [执行计划](exec-plans/active/M11-email-presentation-0001-readable-cid-r02.md) |

## 未批准事项与债务候选

[技术债记录](exec-plans/tech-debt-tracker.md)保留TD-0001/TD-0002的原人工决定，不借迁移自动提升/解决，不与当前任务状态混用。

## 迁移来源

固定版本与本次许可/历史保真/状态转换说明见[ADHOC-0029](exec-plans/completed/ADHOC-0029-agentsmd-upgrade.md)。PLANS.md已退出当前总计划入口；原件仅在不可执行历史证据中。
