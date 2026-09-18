# 执行计划：ADHOC-0031 本地 Web、同步与 AI 系统

## 对应目标

- 功能编号：ADHOC-0031。
- 功能状态：[completed]；B0～B7本地/合成范围全部完成。历史失败、修复尝试、环境阻塞及恢复计数均保留；最终B7独立验证同一79文件快照通过，主Agent核快照、复跑Python/前端门禁及`git diff --check`通过。真实AI、真实Garmin、网络/登录/MFA、私人数据和真实浏览器8080人工验收未执行，按边界列为未验证。
- 总计划对应条目：[功能总览](../../PLAN.md#功能总览)。
- 目标及范围来源：用户2026-09-15明确要求规划并在没有需补充事项时继续实施五项功能。已有ADHOC-0024～0028纳入本次交付，不恢复旧M12产品或历史外部动作。
- 当前合同状态：首次范围/命名、AI许可、活动4点时刻、config、空周及内存历史已确认；活动选数/补跑、周触发/缺报、旧采样周配额仍有未明确分支。精确实施细则及首轮修复范围见[规划调整主审核](../evidence/ADHOC-0031/parent-contract-review-v2.md)，与本计划及关联旧功能计划共同生效；未采纳建议不作为要求。

| 要求编号 | 已明确的正常结果与范围 | 来源 |
| --- | --- | --- |
| U31-01 | React前端、FastAPI后端；清爽简洁的参考风格。后端同时服务前端静态页面，前端默认编译到后端web目录；本地8080，无账号认证。展示最新FIT同步状态，浏览/搜索已解析数据和AI总结，提供/api/下接口。无认证不等于不测试。 | 用户第1项 |
| U31-02 | Python基于pygarminconnect每三小时检查新活动，下载并按确认命名存入states；首次同步最近七天；新FIT命名为`states/activities/YYYYMMDD-实际FIT字节SHA256.fit`（UTC日期，未知日期`unknown-SHA256.fit`）。运行适配器使用states/verification/garmin.json，可用刷新机制失效时更新。不能把开发需求扩成无限历史下载、任意账户操作或强行绕过MFA。 | 用户第2项；D31-01确认 |
| U31-03 | AI模块使用可配置base_url的兼容API，私有配置在`states/ai.json`；负责发送/接收和工具调用循环，正常直到无tool calls，不负责业务上下文封装。用户允许真实请求、真实数据不限且暂不设请求/费用上限；密钥仍不进Git。错误/截断/越权/资源耗尽必须明确失败，不将半份结果保存为完整报告。 | 用户第3项及已有错误/全量边界；D31-02确认 |
| U31-04 | 独立Context封装运动总结、日总结占位、周总结；周模式由程序取得过去七天运动总结。公共组成包括角色、tools README摘要、references README清单、多轮历史及当前对话；AI可按需读取longdou资料。活动总结按中国时区每日凌晨4点自动触发；多轮历史仅内存保存，数据库只记录结果。日报不接健康数据、不生成日报或新增业务表。 | 用户第4项；D31-03确认 |
| U31-05 | 同批实现既有FIT解析、records查询、实际工具索引、活动/周报告存储；保留四张业务表12/4/3/3列并新增获准config参数表、原record顺序、完整采样、真实running和宿主授权、全文summary、自增周报ID及统一UTC时间锚。 | 用户第5项、ADHOC-0023～0028已确认设计 |
| U31-06 | 新实现和测试同交付，串行Developer、全新只读Validator、主Agent最终亲验。私人数据不进Git，测试用合成隔离实例；业务实调用与未运行检查分别记录。 | 当前AGENTS及既有项目边界 |

## 主审核结果与待确认项

审核接受Planner的模块职责、串行依赖、旧任务编号和检查矩阵；不把其建议自动变成新需求。完整原报告与主审核收据在本任务仓库外证据根保存，定位见检查点。

- 采用报告目录A：产品在source/，运行脚本在source/skills/<skill>/scripts/，共享基础设施在source/skills/_shared/scripts/；前端source/frontend，默认输出source/skills/local-web/web；产品能力索引source/tools/README.md。不申请根tools或source/backend例外，不恢复source/src、source/index.py或旧发布层。
- 资料读取是用户第4项已经明确的新能力，无需重复询问“是否允许读取龙豆资料”。实施可用仅映射公开索引条目的read_reference(reference_id)，不接任意路径/URL；get_running_records(activity_id)仍是唯一采样查询，旧全工具数量限制仅在此明确新要求覆盖的范围退出。
- 周Context使用七天运动总结是本次明确新要求，接入ADHOC-0027；不再沿用旧轮次“不预设依赖活动AI报告”的现行限制。既有默认第1/2/3类事实输入与报告时间/表结构不因此取消。
- Garmin运行时读取/刷新指定认证、首次最近七天下载以及AI真实请求/数据不限均已获明确授权，不重问许可。合成检查不用真实认证；不能扩大到无限历史下载、其他账户动作或公开秘密。
- 不采纳“为了更保守就将周累计20次改为滚动七天20次”的规则重解释。周预算口径、事务视图、容量和循环异常界限在0031-T2依据当前要求落实；推荐8轮/16次/180秒等不是用户已确认指标。
- 不新增通用聊天或永久历史留存；用户已批准真实请求及活动每日4点自动生成，不再视为未获收费许可。2026-09-18用户确认补跑/周触发/records配额策略：每日进程按上次状态补齐到当前的所有空缺活动总结；周报中国时区每周日15:00执行，窗口为上周日15:00到本周日15:00，执行时先运行一次运动总结补跑；首版不做分段查询和records配额，AI需要则给对应running活动全量records。合成与真实检查分别记录。

| 稳定问题编号 | 决策内容 | 影响范围 | 当前情况 |
| --- | --- | --- | --- |
| D31-01 | 新下载命名及首次时间范围：`states/activities/YYYYMMDD-实际FIT字节SHA256.fit`，日期用UTC；未知日期`unknown-SHA256.fit`；首次最近七天。现存文件名64位标识不等于实际字节SHA，不能混用旧年份/运动名规则。 | 正式同步命名、首次下载及相应合同 | 2026-09-16用户确认采用建议；证据见[用户确认事项](../evidence/ADHOC-0031/user-answers-2026-09-16.md) |
| D31-02 | AI配置与真实联调边界：私有配置在`states/ai.json`；允许发送真实请求，真实数据无限制，暂时不考虑请求/费用上限。密钥不进入聊天或Git。 | 实际Provider请求、收费和私人数据联调 | 2026-09-16用户确认；开发测试仍可用本地模拟，真实联调在最终检查单列记录 |
| D31-03 | 报告触发/历史留存：活动总结按中国时区每日凌晨4点自动触发；允许新增`config`等系统参数表供后续Web设置使用；周总结若七天无活动则入库全文`本周无任何运动记录`；多轮历史只保存在内存，数据库记录结果。 | 自动生成策略、持久留存及相应入口 | 2026-09-16用户确认 |
| D31-04 | 原Planner提出的目录/资料工具问题 | 不再作为重复询问项 | 主审核已采用兼容目录A；受限资料读取来自用户明确目标，不是额外采样工具授权 |
| D31-03A | 每日4点的活动选数范围，以及错过/迟到/失败如何补做 | 后续自动批次选取和补跑策略；不影响已完成合成底座/存储 | 已确认：每次运行读取上一次状态，补齐从上次状态到当前时间的所有空缺数据；检查当前到昨天这个时候是否有运动，有则每个运动依次总结入库，没有则跳过等待下次。证据见[2026-09-18策略确认](../evidence/ADHOC-0031/user-answers-2026-09-18-scheduling.md) |
| D31-03B | 周报显式还是自动时点；有活动但缺活动总结时等待或先补齐 | 后续周自动触发/缺报策略；不影响空周存储及齐全输入服务 | 已确认：周报中国时区每周日15:00执行，窗口为上周日15:00到本周日15:00；周末运行时先运行一次运动总结补跑，相当于提前执行D31-03A且不与定时进程冲突。证据同上 |
| D31-02A | 不限请求是否也取消旧records周累计20次；若保留其统计周口径 | 后续真实接线策略；不影响全量查询核心/合成解析 | 已确认：首版不做分段查询，不设records配额；AI需要时把对应running活动records全量给AI。证据同上 |

## 阶段与任务

沿用Planner的B0～B7批次。ADHOC-0024～0028各自T1～T4保持原编号和功能级验收，不用总集成替代；以下只是协调对应关系，不另造一套完成状态。B0～B7历史失败、恢复及验证证据保留；当前ADHOC-0024～0028及ADHOC-0031本地/合成范围均已完成，真实外部检查仍按边界单列未验证。

| 阶段编号 | 状态 | 预期成果 | 依赖 |
| --- | --- | --- | --- |
| B0 | [completed] | 0031-T1工程底座、T2公共接口与精确实施合同；目录/JSON继承缺口已随B1修复复验闭合 | 已审分条合同；全新Validator与主Agent复核通过 |
| B1 | [completed] | ADHOC-0024 T1～T4：合成FIT、解析及四业务表/config共存安全入库 | B0直接相关前置；第二轮修复恢复环境后复验通过 |
| B2 | [completed] | ADHOC-0025/0026 T1～T4：唯一采样查询与准确索引 | B1已完成；资料工具随B5接线同步 |
| B3 | [completed] | ADHOC-0027/0028 T1～T4：两报告全文存储与时间身份 | B1/B2已完成；独立验证与主复核通过 |
| B4 | [completed] | 0031-T3：同步/认证适配、三小时调度、下载恢复 | B1～B3、D31-01；修复复验通过，真实联调另受D31-02约束 |
| B5 | [completed] | 0031-T4/T5：兼容API、工具循环、Context及报告接线 | B2/B3、D31-03；修复复验通过，真实AI另受D31-02约束 |
| B6 | [completed] | 0031-T6：Web/API、前端默认构建到后端web | B3～B5已完成；修复复验通过 |
| B7 | [completed] | 0031-T7：完整本地独立验证、主验收与适用交付 | B6已完成；本地/合成验证通过；真实外部检查只在明确范围内执行 |

| 任务编号 | 所属阶段 | 状态 | 输入输出及错误边界 | 依赖 | 检查方法 | 结果与证据（检查命令或人工方式、退出结果及关键证据） |
| --- | --- | --- | --- | --- | --- | --- |
| 0031-T1 | B0 | [completed] | 新目标/兼容目录→Python及前端依赖、隔离实例和本地检查配置；不安装到全局、不创建仓库.venv，不恢复旧工程 | 主审核后的完整首发材料；采用已确认内容，不猜D31剩余分支 | Python3.12 lint/type/test/compile与Schema；前端lint/type/test/build；路径边界 | B0首轮复验已通过；B1暴露的目录/架构继承缺口在第二轮修复后由全新Validator复验通过。固定56文件聚合SHA `5cb22a1f1950c1e73c0624c2ac2981f090c246738dc53f62eb13f9a5996149d8`；Validator核快照、依赖安装、pytest 157通过、ruff/mypy/compile/架构门、前端抽查和FIT/SQLite探针均通过；主Agent复核快照、`git diff --check`、pytest 157通过及架构门退出0。证据：[恢复复验报告](../evidence/ADHOC-0031/validator-b1-fix-r2-resume.md)。 |
| 0031-T2 | B0 | [completed] | 已确认设计/决策→统一DTO、JSON、错误、时间/重复、授权/预算/容量合同；可新增配置表记录系统参数；不能新加未授权业务列、静默截断或改验收 | 0031-T1；在各旧T1实施前冻结 | 准则逐项对齐、正常/错误/边界预期与接口一致性核对 | 身份/时间一致性及公共合同缺口在第二轮修复后复验通过；关联V31-B0-006的历史停止及累计保留。D31-03A/B、D31-02A已在PR创建后确认策略，但本地/合成B0受验快照不因此改判为已实现后续自动策略。Validator独立探针覆盖时间证据、消息身份、默认123、报告保护、路径边界；主Agent复核通过。 |
| 0031-T3 | B4 | [completed] | 认证/活动列表/下载→持久同步状态和安全原件→解析入口；分页不漏、中断恢复、刷新/MFA和冲突显式失败 | B1～B3、D31-01 | 假时钟、模拟分页/ZIP/认证、并发/重启；获准后才真实检查 | B4修复复验通过；未做真实Garmin联调 |
| 0031-T4 | B5 | [completed] | messages+受信dispatcher→兼容HTTP多轮→最终全文或明确错误；不拼业务上下文，不执行任意工具，不保存半份报告 | B2/B3及0031-T2 | 本地协议服务验证无工具/多轮/多call_id/越权/超限/超时；实服务单列 | B5修复复验通过；未做真实AI请求 |
| 0031-T5 | B5 | [completed] | 角色/两索引/事实/运动总结/历史/当前对话→三模式上下文和可信权限→报告服务；日报无业务副作用 | B2/B3、0031-T4、D31-03 | 上下文快照、资料白名单、会话隔离、统一T与缺报、预算/缓存一致性 | B5修复复验通过；D31-03A/B自动策略已在PR创建后确认，需后续实施验证 |
| 0031-T6 | B6 | [completed] | 状态/仓储/报告服务→/api接口及React展示搜索、后端静态目录；仅本机，无秘密/状态文件静态暴露 | B3～B5已完成 | 真实浏览器、生产构建、8080、SPA/API404、文本/XSS/同源、空错态 | B6修复复验通过；未做真实外部调用 |
| 0031-T7 | B7 | [completed] | 固定完整版本→全链路证据/运行说明→主验收及适用PR；不把离线检查冒充实调用，不自动合并main | B6及旧五功能适用T4 | 下载→解析→工具/报告→Web→重启，全部静态/单元/集成回归与全新独立验证，主Agent亲验 | B7本地/合成全链路Validator通过，主Agent亲验Python/前端门禁及快照通过；没有新提交/推送/PR |

检查覆盖沿用Planner V31-01～13：FIT完整性/来源/单位，四表事务，records权限/全量，分页，下载/ZIP，调度/认证，AI协议，Context/资料，周报告时间，预算/一致视图，Web/路由，Web安全，完整集成。方法可在实施中细化；不得用测试器自身假设新增业务要求。

## 当前检查点

- 工作目录与分支：项目根`.`；work/adhoc-0031-local-web-system。基准HEAD为9db8bb1dda5922e85fe42581e27d2428dbc9f195，已包含PR #20。其他分支/worktree不动。
- 验收要求与受验版本及未提交改动：HEAD仍为`9db8bb1dda5922e85fe42581e27d2428dbc9f195`、原分支未变且产品未提交。当前[第二轮修复快照](../evidence/ADHOC-0031/b1-fix-r2-review-snapshot.json)为56文件，聚合SHA `5cb22a1f1950c1e73c0624c2ac2981f090c246738dc53f62eb13f9a5996149d8`；相对[首轮53文件](../evidence/ADHOC-0031/b1-fix-r1-review-snapshot.json)修改10、新增3、删除0。主Agent逐文件核SHA/大小/权限、产品集合及161保护文件未变；协调记录与忽略生成物/私人数据不计入。
- 既有检查记录：B0首轮修复workflow `f8ab6615-ff6e-455d-b0a2-c1db662ee38d`、Developer `adfe5740-aa87-4d72-a20b-6d23b747ab03`完成；全新Validator workflow `1c349135-bf22-42b9-96be-ed1c6ad64d41`、child `d0cfdba6-bdcb-43df-a0fa-8deca953ad90`复验通过。主Agent保存报告后核对清单无误，运行`git diff --check`、`cd source && /tmp/trainlab-b0-fix-venv/bin/python -m pytest tests -q -p no:cacheprovider`（17通过2警告）、ruff、mypy、compileall、`tools/check_b0_static.py`和前端lint/type/test/build均退出0。无真实业务调用。
- 前次独立验证：B1首次Validator workflow `a2a7ab9e-146b-4851-907e-38d98c67539e`及child `80004f90-02f1-4daa-9ce0-93102428e8fd`已结束，结论失败。[独立报告](../evidence/ADHOC-0031/validator-b1-v1.md)含39项21通过/18失败；主Agent另合成副本复跑相同结果，退出1，原38文件SHA不变。[主复现](../evidence/ADHOC-0031/parent-b1-v1-repro.json)、[持久证据](../evidence/ADHOC-0031/validator-b1-v1-evidence.zip)、[逐项主处置](../evidence/ADHOC-0031/parent-b1-v1-triage.md)已保存。现有24项回归和静态门仍通过，不等于完整验收。
- 修复交接记录：修复workflow `9a3478ae-aecf-4274-834a-d904c45e1356`、Developer `323a2aba-d362-4b7b-9858-37f7ab16bc7d`均结束；[修复报告](../evidence/ADHOC-0031/developer-b1-fix-r1.md)及[证据归档](../evidence/ADHOC-0031/developer-b1-fix-r1-evidence.zip)已保存。主Agent核对53文件SHA及26份安装文件一致，复跑pytest 92通过2警告、Ruff/mypy（32文件）/compile/架构Schema检查均0，见[主交接收据](../evidence/ADHOC-0031/parent-b1-fix-r1-intake.md)。仅为实现交接与现有回归，不是复验通过。
- 前次修复复验：复验workflow `58f76709-8133-4fc9-aaec-b8448b021c19`、Validator `c0f5e187-5bc8-4877-a8f6-4162342d17de`已结束，结论失败。[复验报告](../evidence/ADHOC-0031/validator-b1-fix-r1.md)为91项79通过/12失败；主Agent在另一固定合成副本复跑同样结果，退出1，53文件SHA不变。[主复现](../evidence/ADHOC-0031/parent-b1-fix-r1-repro.json)、[持久证据](../evidence/ADHOC-0031/validator-b1-fix-r1-evidence.zip)及[主处置/暂停依据](../evidence/ADHOC-0031/parent-b1-fix-r1-triage.md)已保存。
- 第二轮修复交接：workflow `1ed6a9eb-a527-4b39-9d28-e0a1d3b79a2b`与Developer `edcef8f2-9ff1-4585-8333-bf4950101e7a`均结束；[报告](../evidence/ADHOC-0031/developer-b1-fix-r2.md)、[证据归档](../evidence/ADHOC-0031/developer-b1-fix-r2-evidence.zip)及[主交接](../evidence/ADHOC-0031/parent-b1-fix-r2-intake.md)已保存。主Agent核28份安装文件一致，复跑pytest157通过/2警告、Ruff/mypy（35文件）/compile通过。架构门初因一枚旧脚本编译缓存失败；相同56文件干净副本通过后，仅移出该缓存留存，原工作区复跑通过，产品未改。原失败日志保留。
- 最近完成：B7 Validator workflow `d4569a28-cbae-410b-9bb6-41da64274557`、child `173cdee8-be78-4a0e-8cf2-b3bbc1e6429b`完成，结论[通过（本地/合成范围）](../evidence/ADHOC-0031/validator-b7.md)。其核79文件[B7快照](../evidence/ADHOC-0031/b7-local-validation-snapshot.json)，聚合SHA `aaddd5a762aa7a79b287b92f61c6b3990bb0cc9cca1a696e71d83f7291f27751`，pytest 196通过/2警告、ruff、compileall、架构门、wheel后mypy、前端lint/type/test/build、完整合成E2E、Garmin合成同步、AI/Context安全、Web/API/静态隐私和重启持久化均通过。主Agent核快照聚合SHA一致，复跑pytest 196通过/2警告、ruff、mypy、compileall、架构门、前端lint/type/test/build、`git diff --check`和暂存检查均通过；清理本地生成物。
- 下一动作：本地/合成范围已完成；用户已授权提交/推送/PR，主Agent已创建[PR #21](https://github.com/wyizhou/TrainLab/pull/21)。用户随后授权真实AI/Garmin/浏览器人工8080检查；[真实检查](../evidence/ADHOC-0031/real-check-2026-09-18.md)未全部通过，因此不询问合并。下一步需先补齐AI模型配置、真实Garmin客户端/适配入口，并按需提供真实浏览器人工检查方式。
- 暂停原因：真实检查未全部通过；D31-LIVE-001/002为当前阻塞。D31-03A/B、02A已确认策略，但后续自动批次/周触发/真实records接线仍未完整实现和验证，本次未阻塞本地/合成验收。
- 恢复条件：已满足。B1修复尝试2、公共合同累计尝试3、环境阻塞1/安装恢复1均保留；本轮不增加产品失败轮次，不授权额外代码修复或Git交付。
- PR与交付情况：用户用“2”授权提交、推送并创建PR。主Agent在仓库外环境复跑Python门禁、前端门禁及`git diff --check`后，提交`4eb2734790cda135daaf642664fcb33943b63ae2`（`feat: add local web training system`），推送`work/adhoc-0031-local-web-system`并创建[PR #21](https://github.com/wyizhou/TrainLab/pull/21)。旧PR #20合并是已完成的前一轮操作，不因此授权本功能自动合并。
- 证据定位：仓库外证据根`trainlab-web-system-w09jm7lc`，含baseline.json、planner-request.md、planner-original.md、parent-planning-review.json、planning-checkpoint.json及公开包元数据；原始受管输出由workflow `20f5c34f-ec40-496e-9486-94251a48fe7d`绑定`adhoc0031/planner.md`，child `9f7371cf-6030-4c49-8807-2cc5bdaa2a1a`，均completed。公开保留[首次规划原报告](../evidence/ADHOC-0031/planner-v1.md)；它是待审核建议/当时事实，不是新的权威合同。
- 当前记录检查：第二轮修复、无法判断复验及恢复复验报告均保存，主Agent再次核56文件及聚合SHA完全一致，HEAD/分支未变、`git diff --check`退出0；安装原始超时调用、环境为空、恢复安装与前后清单均归档，没有把未运行记为通过。B0原报告、清单及额外包装探针事实保留原时点；B1已由当前恢复复验证据闭合。首次规划5份记录的证据不是当前工作区文件总数。

## 问题记录

| 稳定问题编号 | 对应要求与实际问题 | 已尝试修法 | 累计失败次数 | 证据及处理结果 |
| --- | --- | --- | --- | --- |
| D31-01 | 首次同步命名/范围曾未确定 | 只提出候选，未执行下载 | 0 | 2026-09-16用户确认采用建议：首次最近七天，UTC日期+FIT字节SHA命名 |
| D31-02 | AI配置/真实检查数据及成本边界曾待补 | 未读取密钥/认证、未请求Provider | 0 | 2026-09-16用户确认：`states/ai.json`，允许真实请求和真实数据，暂不设上限 |
| D31-03 | 报告触发/多轮历史留存曾待确定 | 只提出候选，未写会话/启动生成 | 0 | 2026-09-16用户确认：北京时间每日4点活动总结；允许配置表；无活动周入库固定文本；历史仅内存 |
| D31-04 | Planner将已有资料读取目标列为新增授权疑问 | 主审核按原请求消解，兼容目录A不需要例外 | 0 | 保留原报告；不是修改用户需求或失败重试 |
| V31-B4-001 | 0031-T3/B4失败恢复：已有上次成功状态时，本轮部分同步导入失败不得把`last_success_at_utc`重置为空 | 首轮实现中部分成功后保存中间状态时写入`last_success_at_utc=None`；修复改为保留`attempted_state.last_success_at_utc`并补回归 | 首次验证失败1；修复尝试1；修复复验失败0 | [B4 Validator](../evidence/ADHOC-0031/validator-b4.md)独立探针复现；[修复复验](../evidence/ADHOC-0031/validator-b4-fix-v31-b4-001.md)通过 |
| V31-B5-001 | U31-03/B5资源耗尽边界：ReportService保存活动/周报告前必须执行已配置storage容量限制，超限明确失败且不写报告 | 首轮实现调用`save_activity_report`/`save_weekly_report`时未传递`dispatcher.capacity`；修复传入容量并补活动/周/空周容量回归 | 首次验证失败1；修复尝试1；修复复验失败0 | [B5 Validator](../evidence/ADHOC-0031/validator-b5.md)独立探针复现；[修复复验](../evidence/ADHOC-0031/validator-b5-fix-v31-b5-001.md)通过 |
| V31-B6-001 | B6 API错误统一合同：所有`/api`错误包括FastAPI参数解析422都必须返回统一`ok/data/error` envelope并使用项目错误码/状态映射 | 首轮实现缺少`RequestValidationError`处理器，`limit=abc`或`/api/reports/weekly/not-int`返回FastAPI默认`detail`；修复新增统一处理器和回归 | 首次验证失败1；修复尝试1；修复复验失败0 | [B6 Validator](../evidence/ADHOC-0031/validator-b6.md)独立探针复现；[修复复验](../evidence/ADHOC-0031/validator-b6-fix-v31-b6-001.md)通过 |
| D31-LIVE-001 | 真实AI检查：产品`load_ai_config()`要求`model`，当前私人`states/ai.json`只有`base_url`与`api_key`，配置不完整 | 未擅自猜模型或修改私人配置；未发起Provider请求 | 真实检查失败1；修复0 | [真实检查](../evidence/ADHOC-0031/real-check-2026-09-18.md)记录`AI_CONFIG_ERROR DATA_INVALID AI config is incomplete`；需补齐模型配置或产品安全默认后复验 |
| D31-LIVE-002 | 真实Garmin检查：产品可读`states/verification/garmin.json`，但PR #21未提供真实Garmin client依赖/构造入口；当前环境无`garminconnect`/`pygarminconnect`，直接activitylist Bearer探针401 | 未安装临时包替代产品依赖，未绕过MFA，未下载FIT | 真实检查失败1；修复0 | [真实检查](../evidence/ADHOC-0031/real-check-2026-09-18.md)记录配置键、依赖缺失和401；需补齐真实客户端适配并复验 |
| D31-LIVE-003 | 真实浏览器人工8080：HTTP/API/静态入口通过，但当前工具环境无图形浏览器或browser MCP，不能声称人工浏览器验收 | 已做本机8080 HTTP检查；未做人眼/浏览器自动化 | 无法判断1；修复0 | [真实检查](../evidence/ADHOC-0031/real-check-2026-09-18.md)记录`/api/health`、`/api/status`、`/`通过；需人工浏览器或可用browser工具 |
| E31-B1-001 | 第二轮Validator依赖安装被自身外层200秒超时中断，FIT/SQLite复验未执行 | 用户`resume`后按原锁文件隔离安装并派全新Validator复验 | 环境阻塞1；安装恢复1；不计产品测试失败 | [原始报告](../evidence/ADHOC-0031/validator-b1-fix-r2.md)、[恢复复验](../evidence/ADHOC-0031/validator-b1-fix-r2-resume.md)；已恢复并通过 |
| V31-B0-001 | U31-01/T1：前端没有React依赖及lint/type检查入口 | 首轮修复：改为React/Vite/TypeScript最小工程，补lint/type/test/build | 首次验收失败1；修复尝试1；修复验证失败0 | [首次独立报告](../evidence/ADHOC-0031/validator-b0-v1.md)失败；[首轮复验](../evidence/ADHOC-0031/validator-b0-fix-r1.md)通过；主Agent前端lint/type/test/build退出0 |
| V31-B0-002 | U31-06/T1：仅安装声明依赖无法运行pytest | 首轮修复：补pyproject dev依赖并保持声明依赖检查入口 | 首次验收失败1；修复尝试1；修复验证失败0 | 复验声明依赖安装、pytest/Ruff/mypy/compile/static-check全0；主Agentpytest 17通过、ruff/mypy/static-check通过 |
| V31-B0-003 | U31-05/T2：activities、activties_report、config主键可存NULL，与合同不符 | 首轮修复：DDL显式NOT NULL并补NULL/重复/外键保护回归 | 首次验收失败1；修复尝试1；修复验证失败0 | 复验独立SQLite正常、NULL、重复键、孤儿行、删除保护、全文测试通过 |
| V31-B0-004 | U31-01/U31-06：静态根词法路径校验放行越界和根软链接 | 首轮修复：正规化实际根并拒绝静态根软链接至合成states，实际factory检查 | 首次验收失败1；修复尝试1；修复验证失败0 | 复验TestClient正常静态/health/404/遍历/软链接拒绝通过；仅合成数据，无真实秘密读取 |
| V31-B0-005 | U31-04/T2：历史接受无时区输入并按本机时区解释 | 首轮修复：统一ensure_utc，naive拒绝，带偏移稳定转UTC | 首次验收失败1；修复尝试1；修复验证失败0 | 复验UTC与Asia/Shanghai等不同TZ一致，内存历史只内存 |
| V31-B0-006 | 公共合同未闭合；曾有身份/时间跨层矛盾可入库 | 方法A：浅层DTO/Schema；方法B：递归Schema＋交叉引用；第二轮有界修复补闭合 | 原首次失败1、既往修复1/原时点复验失败0；继承缺口再现1；累计修复3；恢复复验失败0 | 历史停止条件保留；恢复复验及主复核通过，不改写旧失败日志 |
| V31-B1-001 | AC-02/04：已能实际解码，但非法字段号/空必需消息、HR数组累计、时间下界有6个反例 | 首轮固定Profile＋逐消息协议适配；第二轮补边界 | 首次失败1；修复尝试2；第二轮恢复复验失败0 | Validator覆盖非法字段、空消息、HR累计数组、时间下界并通过；主复核通过 |
| V31-B1-002 | 目录迁移/安装已正常，架构门漏sys.path赋值、tools shell、根运行文件3种违规 | 首轮正常打包迁移＋AST/路径检查；第二轮补架构门 | 首次失败1；修复尝试2；第二轮恢复复验失败0 | Validator架构门、compile、ruff/mypy、路径越界探针通过；主复核架构门通过 |
| V31-B1-003 | AC-04/T2：时间字段与证据、消息名与编号等3类内部矛盾可提交 | 完整公开Schema＋局部交叉校验；第二轮补身份/时间一致性 | B1首次失败1、修复2；首轮复验失败1；关联B0-006累计修复3，不清零 | Validator全量pytest和独立探针通过，历史累计保留 |
| V31-B1-004 | AC-03/T2：默认123及最少解释字典/来源闭包 | 本轮实际固定DTO及引用闭包，不整体返回第四类 | 首次失败1；B1修复1；本项修复后失败0，关联历史保留 | 本轮独立和主复现对应项通过；不替整个T2/B1验收 |
| V31-B1-005 | T2/04：同字节普通导入不改原路径/parsed_at/records/报告 | 普通无变更幂等，与维护分离 | 首次失败1；修复1；本项修复后失败0 | 本轮独立和主复现通过，原件及库字节保持 |
| V31-B1-006 | T2/04：已有报告依赖事实变化先冲突，无报告可受控维护 | SHA核验、REPARSE_CONFLICT与原子维护 | 首次失败1；修复1；本项修复后失败0 | 本轮独立和主复现通过，解析/子行失败保旧 |

上表V31项保存首轮修复结束时的问题及计数，E31项另记本次环境阻塞及恢复；2026-09-17用户已用`resume`授权仅恢复验证环境，第二轮恢复复验通过。第二轮修复计为B1修复尝试2、关联公共合同累计尝试3；安装中断不计产品失败轮次，既往失败不清零。主Agent重复复现不是新轮次。B0首轮修复的原时点通过证据保留，本次B1暴露继承缺口后相关任务重开并已闭合。首轮修复复验触发过停止条件，12个失败断言不当作12轮，主复现不增加轮次。后续若新阶段失败，仍按AGENTS稳定编号和累计规则处理。

## 迭代记录

2026-09-15：新功能授权后完成Git/公开资料/环境检查、创建独立功能分支；一次性全新Planner完整派发并结束，主Agent核基线后审核与登记。只保留必要用户问题，未读取私人内容、安装依赖、实施产品或运行真实Provider；产品测试和独立产品验证均未运行。

2026-09-16：用户确认D31-01～03：首次最近七天和SHA命名、AI配置`states/ai.json`且真实请求/数据不限、北京时间每日4点活动总结、允许配置表、无活动周固定文本入库、多轮历史仅内存。主Agent记录确认事项，准备同步计划并派发B0 Developer。

2026-09-16：B0 workflow `a945608a-2f8e-4e81-b4b2-656c940129da`与Developer `768408ae-d6d2-4639-9922-b3e2a7dbc765`均已结束；主Agent读取报告及实现，核实25个source文件、未提交状态与基准未变，`git diff --check`退出0。已创建仓库外隔离审核副本`trainlab-0031-b0-review-djgcz9jg`（清单见本计划链接），待全新独立验证。开发者报告的9项Python/3项Node及静态门通过仅为自述，尚未主验收；React正式构建及FastAPI实际启动尚无验证证据，不因此标记B0完成。用户随后调整模型/推理设置并要求继续，新派发使用当前设置及fresh上下文。

2026-09-16：首次Validator已返回“失败”；主Agent读取报告、逐命令退出码、观测和独立测试，在另一份纯合成副本亲自重跑得到退出1、8失败/11通过/2警告，原25个source文件SHA不变。接受V31-B0-001～006，首次验收失败1轮、修复0轮。证据：[独立报告](../evidence/ADHOC-0031/validator-b0-v1.md)、[合成检查及主复现归档](../evidence/ADHOC-0031/validator-b0-v1-evidence.zip)、[主处置收据](../evidence/ADHOC-0031/parent-b0-v1-triage.json)。归档仅将绝对路径前缀转为相对证据定位，不改变测试结果，原始外部证据保留；当时等待Planner，不启动B1。

2026-09-16：Planner-v2及workflow已结束，主Agent采纳模块所有权、目录A、统一Schema、时间/身份/报告/权限/一致视图协议并记录[分条主审及首轮修复范围](../evidence/ADHOC-0031/parent-contract-review-v2.md)。更正先前“全部决策闭合”的宽泛表述：当时已确认事项不撤销，只保留D31-03A/B、02A剩余分支；允许B1在其实际前置受验后推进，不能虚标整个B0/T2完成。准备派发新Developer，未开始修复时计数仍为首次1、修复失败0。

2026-09-16：B0首轮修复Developer `adfe5740-aa87-4d72-a20b-6d23b747ab03`完成并保存[修复报告](../evidence/ADHOC-0031/developer-b0-fix-r1.md)；主Agent固定33个受审产品文件清单[复验清单](../evidence/ADHOC-0031/b0-fix-r1-review-snapshot.json)，聚合SHA `c80313240e8eb91ea20e152f8bf63a57f26788c92a37fcd9f11b1576d015d37d`。全新Validator `d0cfdba6-bdcb-43df-a0fa-8deca953ad90`复验V31-B0-001～006通过并保存[复验报告](../evidence/ADHOC-0031/validator-b0-fix-r1.md)。主Agent亲验：固定清单无误，`git diff --check`退出0，`cd source && /tmp/trainlab-b0-fix-venv/bin/python -m pytest tests -q -p no:cacheprovider`为17通过2警告，ruff/mypy/compileall/`tools/check_b0_static.py`退出0，前端lint/type/test/build退出0。B0/0031-T1/0031-T2按本阶段范围完成；未读取私人数据、未真实同步或真实AI、未提交推送。

2026-09-17：用户用`resume`授权仅恢复B1验证环境。主Agent记录授权、更新暂停状态并派发全新只读Validator `528d8a7b-8f40-4999-a973-3ebb5717f65e`；复验同一56文件快照通过，保存[恢复复验报告](../evidence/ADHOC-0031/validator-b1-fix-r2-resume.md)。Validator证据：隔离`uv sync`和`npm ci`均退出0，pytest 157通过/2警告，ruff/mypy/compile/架构门、前端抽查、8个FIT/SQLite探针均通过。主Agent核快照聚合SHA、`git diff --check`，并复跑pytest 157通过/2警告及架构门退出0。E31-B1-001恢复，B0/B1及ADHOC-0024当前验收完成；未读取私人数据、未真实同步或真实AI、未提交推送。

2026-09-18：用户解释并确认此前待决策略：每日活动总结进程每次按上次状态补齐到当前时间所有空缺；周报中国时区每周日15:00执行，窗口为上周日15:00到本周日15:00，周报前先运行一次运动总结补跑且不与定时进程冲突；首版不做分段查询和records配额，AI需要时给running活动全量records。主Agent保存[策略确认](../evidence/ADHOC-0031/user-answers-2026-09-18-scheduling.md)并同步PLAN/MEMORY/本执行计划。该记录不代表PR #21已实现真实自动策略或真实AI/Garmin联调。

2026-09-18：用户授权“开始真实 Garmin、真实 AI 和 8080 检查；全部通过后再问是否合并”。主Agent执行真实检查并保存[真实检查记录](../evidence/ADHOC-0031/real-check-2026-09-18.md)：8080 HTTP/API/静态入口通过；真实AI因`states/ai.json`缺少`model`配置失败，未发起Provider请求；真实Garmin配置可读但产品缺少真实客户端依赖/构造入口，当前环境无`garminconnect`/`pygarminconnect`且直接activitylist探针401，未完成同步/下载；当前工具环境无图形浏览器/browser MCP，不能声称人工浏览器验收。因未全部通过，不询问合并PR #21。
