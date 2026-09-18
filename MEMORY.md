# MEMORY.md

## 重要决定

| 事项 | 已确认的决定及理由 | 来源与日期 |
| --- | --- | --- |
| 当前脚手架 | 采用agentsmd固定提交768a3143；AGENTS和角色/执行计划模板直接采用上游。旧开发协议退出，PLAN/exec是任务状态来源，记忆不重复维护进度。 | 用户八项迁移要求及分支批准，2026-09-15；[迁移计划](exec-plans/completed/ADHOC-0029-agentsmd-upgrade.md) |
| CI与Git交付 | 原轮获准退役旧CI、提交/推送并创建PR，不合并main；随后另获明确授权合并PR #20及安全清理分支，已完成。不新增或主动运行远端CI；原合同/收据保留原时点，后置授权不外推到新功能自动合并。 | 用户分时授权，2026-09-15；[原交付记录](exec-plans/completed/ADHOC-0030-retire-ci-and-publish.md)、[后置合并记录](https://github.com/wyizhou/TrainLab/pull/20#issuecomment-5681203528) |
| 本地系统方向 | React前端由FastAPI服务，默认编译到后端web目录，本机8080、暂不做账号认证；Python每三小时查询新活动。首次同步最近七天，新FIT按UTC日期+实际FIT字节SHA命名。AI传输/工具循环与业务Context分离，私有配置在states/ai.json，用户允许真实请求、真实数据不限且暂不设费用/次数上限。运动、日占位、周三模式包含角色/工具与资料索引/历史/当前对话，周模式明确取过去七天运动总结；活动总结中国时区每日凌晨4点自动触发，多轮历史仅内存。 | 用户本轮五项功能要求，2026-09-15；用户D31确认，2026-09-16；[实施目标](exec-plans/completed/ADHOC-0031-local-web-system.md) |
| 资料调用 | AI可按需读取龙豆资料；这明确增加受限资料读取能力，但不增加第二个采样查询或任意路径/URL访问权限。日报仅占位，不因此启动健康采集或新增日报表。 | 用户Context要求，2026-09-15；[实施目标](exec-plans/completed/ADHOC-0031-local-web-system.md) |
| 子任务派发 | 一次给齐材料，不追加消息、审批回执或续聊；结束后交全新实例。用户说明追加消息会影响回收，本轮未把此说明推广为已验证的平台普遍行为。 | 用户补充及当前AGENTS，2026-09-15 |
| 产品方向 | 用户明确不修复/验证即将重构的旧代码；转为直接API。保存的next代码只是未验证快照，不代表可运行产品。 | 2026-09-15；[保存记录](exec-plans/completed/ADHOC-0019-adopt-next-before-api.md) |
| 主动删除 | 用户已删除旧fit保全目录、将data改名states，随后删除source、根README/CHANGELOG/rules/CLAUDE；此次只按请求新增上游README，不恢复旧代码/数据。 | 用户确认，2026-09-15；当前Git与文件事实 |
| 数据入口 | 已有活动入口为states/activities；真实Goal及verification凭据属于私人实例，不公开。Garmin指定文件的运行时使用按本次明确目标，开发测试不用真实认证。此前观察到日期前缀＋64位标识及.weather.json后缀；该标识不等于实际FIT字节SHA，观察结果不能当新下载命名算法。 | 已完成目录调查及本轮同步目标，2026-09-15；[目录记录](exec-plans/completed/ADHOC-0020-states-activities-decisions.md) |
| 四类与输入 | 基本情况、FIT整场摘要、原生分段、设备/采样；默认所有受支持单项运动给AI第1/2/3类。铁三排除，不从标题/GPS猜运动。 | 用户已确认，2026-09-15；[当前决定](exec-plans/active/ADHOC-0023-fit-data-classification-discussion.md) |
| FIT基础表 | activities十二列含segments_json；records为activity_id、record_index、timestamp_utc、metrics_json，前两列联合键、每场按原record顺序从0编号，不插值/降采样/合并同时间点。 | 用户确认，2026-09-15；[存储目标](exec-plans/completed/ADHOC-0024-fit-sqlite-parser.md) |
| 字段/缺失 | 保留schema_version，不恢复has_running、parse_status、session_count、parser_version、data_revision、quality_json；完整解析入库，合法可选缺失保留，真实0不当缺失。 | 用户逐项确认，2026-09-15；当前存储目标 |
| 唯一采样工具 | get_running_records(activity_id)只接受活动ID，返回受授权running活动全部records；子类不设白名单，不分页/裁剪，超容量整体失败。无任意SQL/文件/数据库路径，宿主强制作用域。 | 用户确认，2026-09-15；[查询目标](exec-plans/completed/ADHOC-0025-fit-running-query-tool.md) |
| 报告表 | activties_report保持用户拼写，三列activity_id、运动start_time_utc、全文本summary；weekly_report为自增id、run_time_utc、全文本summary；无活动周总结入库固定全文`本周无任何运动记录`。四张原业务表不变，但本轮允许新增config等系统参数表供Web设置接入，不能借此增加未授权业务事实列。 | 用户最新确认，2026-09-15；D31-03确认，2026-09-16；[活动报告](exec-plans/completed/ADHOC-0027-activity-ai-report.md)、[七天报告](exec-plans/completed/ADHOC-0028-weekly-ai-report.md) |
| 时间与周期 | 绝对时刻存UTC，读取后按用户时区显示；时长/偏移不转换时区。运动开始时间不是报告生成时间。ADHOC-0031后续自动周报改为中国时区每周日15:00执行，窗口为上周日15:00到本周日15:00；周报前先运行一次运动总结补跑。 | 用户确认，2026-09-15；ADHOC-0031补充确认，2026-09-18 |
| 数据保护 | FIT/GPS/raw/数据库/报告/私人Goal/凭据不进Git；states只放行三个.gitkeep和虚构Goal-example.md。代码测试用合成数据，真实Provider动作另授权。 | 已批准项目边界；2026-09-15目录与忽略验证 |
| 位置与外部动作 | 有来源运动位置/路线/名称可给选定AI，不等于公开。Gmail仅官方REST及原精确授权，本轮不新增邮件。Garmin本轮明确要求通过指定私有认证检查/下载自有新活动及必要刷新；实际范围与费用仍须明确，不能猜凭据或绕过登录/MFA，不继承旧活动/健康/训练写入许可。 | 已确认A-022及用户本轮同步要求，2026-09-15；当前PLAN承接 |
| 本地技能与架构 | 项目技能留在skills，不自动复制到全局；references只按主动专题请求维护，不自动沉淀。正常产品运行不读取测试目录，不恢复orchestrate-parallel-work/旧控制面，不要求仓库.venv。原source-only架构尚未批准改变，根tools落点仍需在产品实施前明确。 | 既有项目决定；本次不改变产品架构 |
| 回答方式 | 默认通俗中文；区分直接记录、换算、派生、缺失和未证实推断，优先清晰表格。 | 用户稳定偏好；2026-09-15 |

## 已验证的事实与经验

| 主题 | 事实或有效方法 | 适用条件 | 证据位置与复核日期 |
| --- | --- | --- | --- |
| 当前工程 | source与旧依赖/测试/linter配置已由用户删除；旧CI已按用户新授权删除，不是恢复产品或获得测试绿灯。未运行的产品检查不得记为通过。 | 新代码需同批落实Python3.12/pytest/Ruff/mypy/compile/Schema及适用本地安全测试；本轮不恢复旧产品 | 2026-09-15实际文件核对；[PLAN](PLAN.md) |
| FIT参考 | 协议、Profile、单位/来源转换已整理；研究SDK成功解码不能替代产品测试。 | 只作直接相关资料，不复用私人FIT为公开夹具 | [FIT资料](references/garmin-fit-parsing.md)，2026-09-15 |
| 龙豆参考 | 标准与Developer字段不能覆盖合并；字段定义、单位和实测范围已整理，设备存在不能证明逐指标来源。 | 私人例子不进公开文档，缺项不推断设备永不支持 | [龙豆资料](references/longdou.md)，2026-09-15 |
| 历史保护缺口 | 旧清理INCONCLUSIVE、缺失私人基准及此前安装越界不因后续研究/脚手架验证改判；source删除不等于已完成迁移或私人备份。 | 恢复前看原证据，不自动执行历史命令或恢复旧数据 | [旧清理](exec-plans/active/ADHOC-0018-data-fit-year-cleanup.md)，2026-09-15 |
| 历史交付 | 旧M10/M11发送、M12局部门禁及代码保存均只代表当时授权和受验快照；不授权新的邮件、课程或模型调用，也不证明当前旧源码可运行。 | 需要追溯时定向读相应计划及不可变历史快照；不重判历史失败 | [历史功能登记](PLAN.md#历史功能与未结束事项非当前执行队列)，2026-09-15 |
| 保全观测限制 | M8 r31曾触碰正式SHM元数据；原归档曾核对9612份备份/恢复和afdb8c0推送，但现旧source及相关证据位置可能失效，不证明当前备份完整或从未触碰sidecar。 | 临时历史证据不保证仍在；前后摘要/stat不是持续OS审计 | 原MEMORY与相关历史执行计划原件在history.zip，复核2026-09-15 |
| 环境与平台经验 | 原本地子进程曾实测可用；只证明当时调度，不替产品验证。旧macOS专用Candidate的Linux CI失败保留，不把单平台通过推广到另一平台。 | 每次实际派发/检查仍核对当前环境；没有恢复证据不自动重试或切换模式 | 原记录及新AGENTS检查规则，2026-09-15 |
| 方案替换 | 已批准的新方案必须同批对齐受影响约束、实现、Schema/Prompt、配置/入口、适用本地测试和文档；旧CI按后续明确授权退役，不自动恢复或新增远端CI；必要安全场景迁移，不保留两套有效答案或永久固定旧测试数量。 | 只对受影响范围，不扩大授权、不弱化正确预期 | 用户A-023确认及当前PLAN，2026-09-15 |
| 本地检查 | 规划/治理可查Markdown、JSON、链接、来源摘要、状态/路径映射、Git差异和忽略；静态检查不替代真实产品集成/语义验收。 | 当前迁移不运行已被删除的产品测试；后续功能按实际范围验收 | [迁移计划](exec-plans/completed/ADHOC-0029-agentsmd-upgrade.md)，2026-09-15 |
| ADHOC-0031本地验收 | 本地/合成范围已验证通过：FIT/SQLite、records、报告存储、Garmin假同步、AI工具循环/Context、Web/API、React静态构建和重启持久化均通过；用户随后授权提交/推送/PR，已创建PR #21；后续真实检查中8080 HTTP/API/静态入口通过，但真实AI因`states/ai.json`缺少`model`未发起请求，真实Garmin因缺少真实客户端依赖/入口且直接activitylist探针401未通过；无图形浏览器工具，不能冒充完成人工浏览器验收。 | 后续若做真实联调、实现自动补跑/周报策略或合并，需要单独确认范围并新增证据；当前结论只适用同一B7快照及本地/合成边界。已确认：每日进程按上次状态补齐所有空缺活动总结；首版records无配额、不做分段，AI需要时给running活动全量records。 | [B7验证报告](exec-plans/evidence/ADHOC-0031/validator-b7.md)、[PR #21](https://github.com/wyizhou/TrainLab/pull/21)、[策略确认](exec-plans/evidence/ADHOC-0031/user-answers-2026-09-18-scheduling.md)、[真实检查](exec-plans/evidence/ADHOC-0031/real-check-2026-09-18.md)，2026-09-18 |
