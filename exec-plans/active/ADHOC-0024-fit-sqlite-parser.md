# 执行计划：开发计划一：FIT 解析与活动／采样记录 SQLite 存储

## 对应目标

- 功能编号：ADHOC-0024
- 功能状态：[plan]
- 总计划对应条目：[PLAN.md](../../PLAN.md) 的同编号/原Roadmap关联条目。
- 目标及范围和验收要求的引用：以本文已确认目标、字段、接口和错误边界为准；只迁移格式/路径/协作约定，不改变业务决定。
- 迁移说明：设计已确认；产品实现尚未开始。 当前协作规则仅以[AGENTS.md](../../AGENTS.md)为准；原合同及旧规范在快照中仅作历史来源，不继续生效为第二套流程。

## 阶段与任务

| 阶段编号 | 状态 | 预期成果 | 依赖 |
| --- | --- | --- | --- |
| S1 | [plan] | 按本文目标准备/实施，业务边界不变 | 原用户目标及对应前置条件 |

| 任务编号 | 所属阶段 | 状态 | 输入输出及错误边界 | 依赖 | 检查方法 | 结果与证据（检查命令或人工方式、退出结果及关键证据） |
| --- | --- | --- | --- | --- | --- | --- |
| T1 | S1 | [plan] | 落实目录、规则/本地检查对齐、JSON细则、容量与重解析边界；不超出本文目标/错误边界 | 前置依赖 | 保持已确认设计，按新版AGENTS审核实施拆解 | 未实施、未验证 |
| T2 | S1 | [plan] | 合成测试先行；不超出本文目标/错误边界 | T1 | 正常/缺失/重复时间/长活动/原生分段与采样分别验证 | 未实施、未验证 |
| T3 | S1 | [plan] | 实现建库、解析与两表整场写入，退出受影响旧路径；不超出本文目标/错误边界 | T2 | 代码/Schema/入口/规则/本地测试/文档同批 | 未实施、未验证 |
| T4 | S1 | [plan] | 完整门禁及全新独立验收；不超出本文目标/错误边界 | T3 | 绑定当前快照，未接API不能宣称业务上线 | 未实施、未验证 |

## 当前检查点

- 工作目录与分支：项目根；本次格式迁移在work/adhoc-0029-agentsmd-upgrade，原执行目录/分支仅见历史证据。
- 验收要求与受验版本及未提交改动：本轮迁移基准ec36ce7bbdf9d70a509238dd771b155eb6f84261；原受验版本/未提交内容/合同全文保留于快照。不得把迁移HEAD当作原产品受验版本。
- 最近完成：仅迁移当前记录结构与路径；设计已确认；产品实现尚未开始。
- 下一动作：按本文下一步落实条件，不自动建库/开发/调用业务。
- 暂停原因：实施前目录、适用检查入口和剩余接口细则尚需落实；本轮不启动产品。
- 恢复条件：落实本文尚未明确的实施边界，由主Agent审核拆解；本轮迁移不启动该产品功能。
- PR 与交付情况：本文件只记录已确认设计，不代表产品实施或验收；用户新授权的旧CI退役及当前公开工作区Git/PR交付由[ADHOC-0030](../completed/ADHOC-0030-retire-ci-and-publish.md)记录实际结果。原迁移及历史Git事实不改写。

## 问题记录

| 稳定问题编号 | 对应要求与实际问题 | 已尝试修法 | 累计失败次数 | 证据及处理结果 |
| --- | --- | --- | --- | --- |
| 未发生实施失败 | 本功能尚未进入产品实施；讨论/文档检查不能当产品验收 | 无产品修法 | 未启动实施，不转记旧问题为0 | 迁移前真实记录及检查证据在history.zip对应原件 |

## 当前唯一有效设计

- 本任务负责states/data.db的FIT基础层：activities十二列、records四列，解析及入库；分段在activities.segments_json，不另建分段表。全库还规划activties_report、weekly_report两张报告表，分别由[ADHOC-0027](ADHOC-0027-activity-ai-report.md)与[ADHOC-0028](ADHOC-0028-weekly-ai-report.md)负责，不再限制全库只能两表。
- 四类含义不变：1基本情况、2整场摘要、3原生分段、4设备及时间采样。record是采样点，不是lap/split/set，不把原生分段改名成records。
- 所有受支持的单项运动默认向AI提供第1/2/3类；第4类采样不默认批量发送。跑步才开放按活动ID读取全量records的工具，非跑步不开放。此前铁三不纳入分析/训练的边界不因“所有运动”措辞自动恢复。
- 保存FIT实际record消息的完整记录集合；不插值补成每秒一行、不合并重复时间点、不降采样，不以统计窗口代替records。
- 继续保留schema_version；不恢复has_running、parse_status、session_count、parser_version、data_revision、quality_json。完整解析才入库，合法可选字段缺失不丢弃活动或采样记录。
- 新目标替代旧A-021中不批量秒级落库/窗口细读等冲突条款；旧编号只记录批准来源。当前未实现产品代码/入口/Schema，不能声称新路线已交付。

## 规则对齐与实施前门

原源码已由用户删除，不恢复旧路径；全量records及隐私目标按本文最新决定执行，协作方式以根AGENTS为准。

用户已明确新目标；产品实施时同批对齐受影响的项目约束、Schema、Prompt、入口、适用本地测试和文档，不恢复rules.md或旧执行协议，不继续20分钟裁切，也不把旧窗口称作全部records。开发协作按当前AGENTS；本计划只保存已确认设计，不自动开始实跑。

周累计最多20次及同请求缓存等未被用户本轮明确取消，继续作为待宿主对齐的既有边界；“一种工具”不等于“只能调用一次”。完整返回仍有模型上下文/字节/运行时间等技术容量限制，超限必须整体明确失败，不能截断、分页或返回摘要冒充完整结果。数值预算和超限策略在实施前冻结。

根tools与现行source-only/Skill脚本位置仍有布局冲突，先确认目录和同批规则/本地检查修改范围。不安装新依赖，不把已有研究SDK安装批准当产品依赖变更授权。

## 已确认验收要求与实施边界

- 已确认事项不再重提审批：FIT基础两表/列名/联合键、UTC时间列、完整采样、默认123、唯一ID查询及活动ID只在返回顶层写一次、metrics_json返回对象。待落实的是目录、受影响规则/本地检查对齐、JSON技术细则、容量数值及重解析边界；这些不能重新引入已否决方案。

| 标准 | 已确认验收目标 | 来源 |
| --- | --- | --- |
| AC-01 | 建states/data.db及activities、records两表；activities采用下列12列，records采用四列及(activity_id,record_index)联合主键，引用所属活动，不另建分段表。 | 用户本轮确认 |
| AC-02 | 保存实际record消息的全部记录，不降采样/插值/合并同时间记录；顺序可复核、单位与标准/Developer来源准确。 | 用户全部records目标及真实数据边界 |
| AC-03 | 默认输出第1/2/3类，原生lap/split/set不丢失、不和采样混淆；不默认输出全量第4类。 | 用户本轮输入策略 |
| AC-04 | 只让完整解析结果入库；合法缺失如实保留；两表整场事务一致，首次失败不造行、重解析失败不破坏已有有效数据。 | 用户既有入库/缺失决定及工程门禁 |
| AC-05 | 保留schema_version、不恢复被否决六列；存储运动范围与running查询权限分离；保护原件/无关数据，基础层初始化/导入不得清空或覆盖报告表。 | 用户既有决定、新增报告目标及AGENTS数据保护边界 |

| 门禁 | 计划检查 | 来源 |
| --- | --- | --- |
| GATE-01 | 先建合成FIT/SQLite正常/缺失/重复时间/非规则采样/错误预期，再实现；完整适用pytest/Ruff/mypy/compile/Schema检查。 | AGENTS、A-009 |
| GATE-02 | 两表键/外键、零/多记录、消息条数与顺序、全量不裁剪、默认123不混入采样、事务回滚及隐私/差异检查。 | 用户目标与工程边界 |
| GATE-03 | 已确认验收要求及当前完整快照经全新只读Validator验收；受影响旧路径与规则同步退出，不复用历史PASS。 | 当前AGENTS及已确认的新方案同步边界 |

## activities：已确认12列

segments_json承载默认给AI的第3类原生分段；sensors_json保留设备/字段定义等非采样说明，不重复存全量record数组。以下是已确认设计，尚未创建实际Schema或迁移数据库。

| # | 列 | 类型 | 用途 |
| --- | --- | --- | --- |
| 1 | activity_id | TEXT PRIMARY KEY | 原FIT实际字节SHA-256，不采用文件名标识。 |
| 2 | fit_path | TEXT | 受控实例根相对路径，仅宿主使用，不传AI。 |
| 3 | sport | TEXT | 来自FIT session.sport的活动大类。 |
| 4 | sub_sport | TEXT | 活动子类；running不设子类白名单。 |
| 5 | start_time_utc | TEXT | 实际活动开始时间，能确认才填。 |
| 6 | end_time_utc | TEXT | 可核验的活动结束，不盲用摘要timestamp。 |
| 7 | schema_version | INTEGER | 用户明确保留的格式版本。 |
| 8 | parsed_at_utc | TEXT | 成功解析处理时间。 |
| 9 | basic_json | TEXT(JSON) | 第1类活动基本情况，默认给AI。 |
| 10 | summary_json | TEXT(JSON) | 第2类整场摘要，默认给AI。 |
| 11 | segments_json | TEXT(JSON) | 第3类原生lap/split/set等，默认给AI。 |
| 12 | sensors_json | TEXT(JSON) | 第4类设备/字段定义等说明，不重复存record正文；默认不整体发送。 |

summary_json是FIT整场事实摘要，不是AI报告；AI完整总结另存报告表summary，不能互相覆盖。FIT解析器不负责生成/写入AI总结。

lap、split和set可能重叠，原生类型/触发/阶段说明保留，不混加时长，不从强度或时长猜热身/恢复。保留原生经过/计时时长，不强迫等于起止差；具体分段JSON格式待确认。

## records：已确认四列

| # | 列 | 类型 | 用途 |
| --- | --- | --- | --- |
| 1 | activity_id | TEXT NOT NULL | 所属活动，外键引用activities.activity_id，联合主键之一。 |
| 2 | record_index | INTEGER NOT NULL | 活动内按原FIT record消息出现顺序从0编号，联合主键之二。 |
| 3 | timestamp_utc | TEXT | 该采样的UTC时间；不能确认绝对时间时不伪造，具体缺失/相对时间表示待定。 |
| 4 | metrics_json | TEXT(JSON) | 该record的其余采样指标，不逐项增加SQL列。 |

主键为PRIMARY KEY(activity_id, record_index)，两列显式NOT NULL，并实际启用/验证外键。不同活动各从0开始，不需要额外record_id或records_id；timestamp不作唯一键，因为同一时间可能多条记录或时间缺失。保持文件顺序，不按时间排序后重编号，不删除重复时间点。

采样点不是区间，因此不沿用segment_type、phase、start/end_offset、elapsed/timer这组分段列。不需要record_count常驻列，必要时由集合得到。时间列确定为timestamp_utc；相对活动开始的offset可计算，不另增时间偏移列。无法转UTC的原始时间证据如何保留在JSON中，须在字段规范中明确。

metrics_json区分标准字段与Developer字段，保存文件实际提供的心率、距离、速度、功率、跑步动态、位置等。有值保留，合法缺失用null、真实0仍为0；没有定义的专项字段不虚构。单位转换只做一次，不把组件展开/滤波值冒称未经处理的传感器原信号。

Developer字段身份/单位须能解读，自描述放记录内还是结果共用字典待确认。不恢复质量评分/解析版本字段。全量records指全体采样记录，不是开放FIT原字节、凭据、任意其他消息或无关身份；字段范围与A-004/A-022共同约束。

## 完整性、数据量与写入

- 同一FIT的活动行及全部record行完整校验后，同一事务提交；子行失败整体回滚。无实际可选信息不补造；没有record的文件如何区分合法缺失与结构不完整，在完整解析定义中明确。
- 同字节FIT可幂等；不同字节导出对应同一运动的重复识别仍待确定。不自动合并、删除或默许负荷重复统计。
- 主表字段、JSON与record归属一致，不能将部分采样写入后宣称成功。数值/JSON损坏不伪装成合法null。
- 本轮没有data_revision，schema_version只保证格式，不保证内容没变。是否更新既有行、同一轮AI分析中的数据稳定性与重解析政策仍待确认。
- 全量落库与全量发送是两个边界：SQLite可以存完整记录，不等于任何模型都能一次接收。容量不足不能悄悄改成一分钟/五分钟统计或只返回前N行。

## 功能与检查映射


候选测试：`source/tests/code/unit/test_fit_store_parse.py`、`contract/test_fit_store_schema.py`、`integration/test_fit_store_import.py`、`fixtures/fit_store/`。至少验证活动/record联合键、同时间多条不丢失、不规则间隔不补点、不降采样、分段仍在默认输入、外键和事务回滚；报告表加入后补充跨表保护回归，避免初始化/REPLACE等破坏报告。全合成，不读取正式实例。

技术栈拟沿用Python3.12/pytest/Ruff/mypy；source已被用户删除，原依赖/测试/linter文件不是当前可用入口，旧CI已按用户授权退役。正式新实现须同批落实依赖、适用测试及本地lint/type/compile/Schema检查，不新增或主动运行远端CI；保留必要安全场景，不恢复旧产品或删弱门禁；研究SDK批准不等于产品依赖已选定，不要求仓库.venv。

## 历史来源与证据

- [不可变原件快照](../evidence/ADHOC-0029/history.zip)，条目`docs/exec-plans/active/ADHOC-0024-fit-sqlite-parser.md`，原SHA-256：`a68c06f23d218f089b3f9e102cef87dab15823d61868d47ec98d7c484a3968d5`。
- [来源清单](../evidence/ADHOC-0029/history-manifest.json)、[迁移/编号映射](../evidence/ADHOC-0029/migration-manifest.json)、[原问题与失败计数索引](../evidence/ADHOC-0029/failure-index.json)。原记录中的绝对路径和失效外部证据只说明当时事实，不据此复建旧路径。
- 历史快照仅用于保真审查，不作为现行规范、产品导入、Schema、AI输入或CI运行依赖。当前实际迁移验收见[ADHOC-0029](../completed/ADHOC-0029-agentsmd-upgrade.md)。
