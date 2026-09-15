# 执行计划：当前决策：FIT 数据、SQLite、AI 查询与报告

## 对应目标

- 功能编号：ADHOC-0023
- 功能状态：[exec]
- 总计划对应条目：[PLAN.md](../../PLAN.md) 的同编号/原Roadmap关联条目。
- 目标及范围和验收要求的引用：以本文已确认目标、字段、接口和错误边界为准；只迁移格式/路径/协作约定，不改变业务决定。
- 迁移说明：设计讨论与决策记录持续保留；不是产品实施。 当前协作规则仅以[AGENTS.md](../../AGENTS.md)为准；原合同及旧规范在快照中仅作历史来源，不继续生效为第二套流程。

## 阶段与任务

| 阶段编号 | 状态 | 预期成果 | 依赖 |
| --- | --- | --- | --- |
| S1 | [exec] | 维护已确认决定及未定事项，不实施产品 | 用户已确认目标及后续明确讨论 |

| 任务编号 | 所属阶段 | 状态 | 输入输出及错误边界 | 依赖 | 检查方法 | 结果与证据（检查命令或人工方式、退出结果及关键证据） |
| --- | --- | --- | --- | --- | --- | --- |
| ADHOC-0023 | S1 | [exec] | 保存/维护已确认决定，不实施产品 | 用户明确请求 | 文档/链接/范围一致性 | 当前记录见本文；历史原件见证据快照 |

## 当前检查点

- 工作目录与分支：项目根；本次格式迁移在work/adhoc-0029-agentsmd-upgrade，原执行目录/分支仅见历史证据。
- 验收要求与受验版本及未提交改动：本轮迁移基准ec36ce7bbdf9d70a509238dd771b155eb6f84261；原受验版本/未提交内容/合同全文保留于快照。不得把迁移HEAD当作原产品受验版本。
- 最近完成：仅迁移当前记录结构与路径；设计讨论与决策记录持续保留；不是产品实施。
- 下一动作：按本文下一步落实条件，不自动建库/开发/调用业务。
- 暂停原因：决策记录未暂停；五项产品开发不在本轮执行范围内。
- 恢复条件：落实本文尚未明确的实施边界，由主Agent审核拆解；本轮迁移不启动该产品功能。
- PR 与交付情况：本文件只记录已确认设计，不代表产品实施或验收；用户新授权的旧CI退役及当前公开工作区Git/PR交付由[ADHOC-0030](../completed/ADHOC-0030-retire-ci-and-publish.md)记录实际结果。原迁移及历史Git事实不改写。

## 问题记录

| 稳定问题编号 | 对应要求与实际问题 | 已尝试修法 | 累计失败次数 | 证据及处理结果 |
| --- | --- | --- | --- | --- |
| 未发生实施失败 | 本功能尚未进入产品实施；讨论/文档检查不能当产品验收 | 无产品修法 | 未启动实施，不转记旧问题为0 | 迁移前真实记录及检查证据在history.zip对应原件 |

## 已确认决定与来源

records方案批准原话：“我觉得这是合理的，你加入决策和计划，同时如果决策和计划有冲突的应该删除，并以这次为准。”

用户已确认仓库删除是主动操作。报告方案以本次最新要求为准：activties_report增加运动开始时间；weekly_report取消activity_id、改自增ID并增加实际运行时间，覆盖该时间往前七天；summary为完整AI文本总结。用户明确要求同步决策/计划、处理冲突，以当前为准。

本文件及下列五份相关开发计划以已确认的records方案及本次报告目标为准。与其冲突的分段表、输入组合和查询方向已从当前设计正文移除，不并列维护两套有效答案。历史正式合同、独立验收和失败证据不在本轮改写范围。


## 1. 四类含义与存储

| 类别 | 内容 | 已确认存放位置 | 默认给AI |
| --- | --- | --- | --- |
| 1. 活动基本情况 | 活动类型、开始时间等 | activities.basic_json | 是 |
| 2. 活动摘要 | 整场时长、距离、平均值等 | activities.summary_json | 是 |
| 3. 活动分段 | 原生lap、split、set及各段数据 | activities.segments_json | 是 |
| 4. 传感器与采样数据 | 设备/字段说明及按时间记录的采样点 | 说明在activities.sensors_json；采样在records表 | 不默认批量发送；跑步可按需查询全部records |

- record是采样点；lap/split/set是分段，不能互相改名。第4类通常体积最大，但采样间隔不保证一秒，不能通过编号推测时间。
- lap、split和set可能重叠，不混加为整场时长。明确记录的类型/阶段/触发说明保留，不根据速度、心率或时长猜训练结构。
- 标准字段与Developer Fields是编码/来源属性，不另立业务大类，不因名称相似而覆盖或平均合并。
- 第4类不只外接设备；内置、外置及未知来源都可能有数据。设备存在不证明每个指标归属，采样值也可能已计算或滤波。

## 2. 两表与字段：已确认

数据库目标为states/data.db：FIT基础层由activities与records两表组成；新增activties_report与weekly_report两张AI报告表，由各自计划负责。因此当前规划共四张业务表，不再把“基础层两表”误写成全库只能有两表；仍不另设独立分段表或活动ID列表。

### activities

每份FIT一行，十二列已确认：activity_id、fit_path、sport、sub_sport、start_time_utc、end_time_utc、schema_version、parsed_at_utc、basic_json、summary_json、segments_json、sensors_json。类型/用途见计划一。

activity_id采用实际FIT内容SHA-256，不采用文件名中的标识。fit_path仅宿主定位，不给AI；sensors_json存设备/字段说明，不重复装全量采样数组。

### records

| 字段 | 含义 |
| --- | --- |
| activity_id | 所属活动，外键引用activities |
| record_index | 每场活动按原record消息顺序从0编号 |
| timestamp_utc | 该采样的UTC时间 |
| metrics_json | 该采样点其余指标，JSON保存 |

- 联合主键为(activity_id,record_index)，不再维护独立record_id；不同活动各从0开始。
- 保持记录数量与文件顺序；同一时间多条记录不合并，时间缺失不靠编号补秒，不降采样、不插值。
- record是点，不设分段起止/时长/阶段列，也不另存offset时间列。相对时间可计算，不能转UTC的原始时间保留方式在Schema技术细则中落实。
- 指标不逐个拆SQL列；标准/Developer区分、单位正确，有值保留、合法缺失null、真实0保留0。
- schema_version留在活动表；不恢复has_running、parse_status、session_count、parser_version、data_revision、quality_json或同义隐藏字段，不增加质量评分。
- 完整解析才入库，合法可选指标缺失不丢弃整场。活动与全部record行同一事务写入，失败不留半场或孤立记录，不修改原FIT或已有有效结果。

## 3. 默认输入与唯一工具：已确认

- 所有受支持单项运动默认给AI第1/2/3类。铁三继续不纳入分析/训练，本轮不扩大此前排除范围。
- sport从真实FIT session.sport取得，只有running可使用工具；sub_sport不作白名单，未知子类不排除已确认running的大类。非跑步及未知大类不开查询权限，不凭标题/GPS/速度猜测。
- 唯一工具名get_running_records，唯一业务参数activity_id，一次返回该受授权活动的全部records。
- 没有时间/分段/指标筛选、limit/cursor、分页或第二种查询；不回读FIT补齐未存数据，不把窗口/摘要称作全部records。
- 活动ID在结果顶层只写一次，records数组保持原索引/顺序，timestamp_utc与metrics_json随每条返回；metrics_json是JSON对象，不是双重编码字符串。
- 无跑步的AI请求不挂此工具；混合上下文有跑步时可挂一个工具，但执行端仍按ID核对数据库sport与本次可访问集合，不只依赖Prompt。
- 超模型上下文/字节/时间等技术容量时明确整体失败，不静默截断、降采样或返回前N条。容量数值尚未确定，不保证任意长活动能送入任意模型。
- 一种工具不是一次调用。未被本次改变的累计调用预算/缓存、隐私和外部动作授权仍需遵守；不恢复内容版本字段来假装跨调用一致。

## 4. AI报告：当前三字段与时间语义已确认

| 表 | 用途 | 字段 |
| --- | --- | --- |
| activties_report | 每个活动对应的完整AI文本总结 | activity_id、start_time_utc、summary |
| weekly_report | 本次运行往前七天、多份运动数据的完整AI文本总结 | id、run_time_utc、summary |

- activties_report按用户原文拼写记录，不自动更名。start_time_utc与activities同名，保存所属运动的实际开始时间，不是报告生成/写入时间；合法缺失不伪造当前时间。
- weekly_report.id为INTEGER PRIMARY KEY AUTOINCREMENT，由SQLite分配，不再关联某个activity_id，也不改用week_id。自增允许间隙；SQLite自动管理的sqlite_sequence不是第五张业务表，不另建应用计数器表。
- weekly_report.run_time_utc记录本次实际运行/保存采用的当前时间T；报告覆盖T往前七天至T，而非上一自然周、某周编号或固定整点。T的周期起点可推导，不增加周起止列。
- 用户举的周日15:00只是例子：实际15:03运行就按15:03记录并往前七天，不回填为计划15:00。存UTC、展示本地时间；取数/AI输入/保存使用同一时间基准，不将生成后的较晚时间冒充原内容覆盖截止。
- 每份周报告由自增ID区分，运行时间不作唯一键，不强加每个自然周只有一份的限制；不新增定时任务或默认恢复旧补发周期。
- 两表均严格三列；summary已明确为完整文本，不只存摘录/路径，不强制改为结构化JSON或塞入额外模型/状态/版本等元数据。FIT的activities.summary_json仍是事实摘要，不能被AI文本覆盖。
- 本次替代旧两列限制和周报活动关联，删除原周标识待澄清项；其余数据/隐私/权限边界不扩大。只规划报告存储，不自动批准真实AI生成/调度/邮件或报告工具，不改变默认123与唯一跑步records查询。

## 5. 对应开发计划

| 计划 | 已确认目标 | 状态 |
| --- | --- | --- |
| [ADHOC-0024：解析与存储](ADHOC-0024-fit-sqlite-parser.md) | 建库及activities十二列＋records四列，解析和完整事务入库，准备默认123。 | [plan]；设计已确认，实施尚未启动 |
| [ADHOC-0025：全量records工具](ADHOC-0025-fit-running-query-tool.md) | get_running_records(activity_id)，只读关联授权，返回全部采样。 | [plan]；设计已确认，实施尚未启动 |
| [ADHOC-0026：tools索引](ADHOC-0026-tools-ai-index.md) | README仅说明上述唯一工具，与实际Schema/脚本一致，供后续API装配。 | [plan]；设计已确认，实施尚未启动 |
| [ADHOC-0027：活动AI报告](ADHOC-0027-activity-ai-report.md) | activties_report：activity_id＋运动start_time_utc＋完整文本summary。 | [plan]；三字段已确认，实施尚未启动 |
| [ADHOC-0028：滚动七天AI报告](ADHOC-0028-weekly-ai-report.md) | weekly_report：自增id＋run_time_utc＋完整文本summary，覆盖本次T往前七天。 | [plan]；身份/时间/三字段已确认，实施尚未启动 |

前三项维持既有依赖；报告任务共享计划一数据库底座，不预设周报告必须先读活动AI报告，也不新增并行拓扑或自动恢复M12。README不等于API执行器，API宿主接线及真实业务调用不在本轮范围。

## 6. 尚未落实的实施事项（不是重新确认已批准设计）

- tools目录：根tools为空、source/tools不存在；产品脚本落点与现行source-only/Skill目录约定须明确对齐，当前不擅自改规则。
- 技术细则：JSON键名/单位、Developer自描述或共用字典、相对时间/合法缺失/零record的处理，以及重复导出/重解析/同轮数据稳定性，在实施合同中具体化，不改变已确认四列和全量语义。
- 确定模型/宿主容量及阈值；超限整体失败策略已确认，不再作为待选方案。周累计20次等未被明确取消的边界不自动扩大。
- 报告事项：周报告自增身份及滚动七天已明确，summary采用文本，不再列为待选方案。只需落实活动报告主键/重复保存、时间格式与宿主统一时间锚、边界/跨界活动组装、重试及容量等实施细则，不暗中增加列。

## 历史来源与证据

- [不可变原件快照](../evidence/ADHOC-0029/history.zip)，条目`docs/exec-plans/active/ADHOC-0023-fit-data-classification-discussion.md`，原SHA-256：`324b492c943e30331bac1b4117688ae14a4d72a1945c6d4b2b085e2dff34af84`。
- [来源清单](../evidence/ADHOC-0029/history-manifest.json)、[迁移/编号映射](../evidence/ADHOC-0029/migration-manifest.json)、[原问题与失败计数索引](../evidence/ADHOC-0029/failure-index.json)。原记录中的绝对路径和失效外部证据只说明当时事实，不据此复建旧路径。
- 历史快照仅用于保真审查，不作为现行规范、产品导入、Schema、AI输入或CI运行依赖。当前实际迁移验收见[ADHOC-0029](../completed/ADHOC-0029-agentsmd-upgrade.md)。
