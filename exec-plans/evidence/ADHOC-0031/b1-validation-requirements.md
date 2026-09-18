# B1 首次独立验证：客观要求摘录

本文件仅汇集当前已确认目标与已审核技术拆解，供隔离副本审查。不是新规划、修改验收或历史裁决。未附开发者报告、历史验证结论或主 Agent 检查结果。当前代码/README/示例均属受审内容，不能反向改变目标。

范围：ADHOC-0031 B1 / ADHOC-0024 T1～T4，离线合成 FIT 字节经产品解析、完整校验、SQLite 导入和默认123事实读取。B2～B7尚不属于本次功能验收；真实同步、真实私人FIT、真实AI调用不在本次验证范围。测试应使用合成的有效/损坏 FIT 协议文件，不以任意字符串的替身解码等同于 FIT 解析完成。

适用规则：AGENTS.md、subagent-templates/validator.md。固定文件清单：review-snapshot.json。材料提供完整副本，不修改受审源码、测试或验收条件。

来源优先关系：原用户目标与 AC 不变；主审核文件接受的 T2 条款补齐技术细则。下列 Planner 摘录中的承载结构、身份/时间/重解析约束已在主审核对应条款采用，未核实SDK映射和合法零record例外仍须产品提供协议证据，不能把未知当要求或自行放宽。后续采样配额、活动批次/补跑、周触发/缺报政策不属于本次必须实现的分支。

## 来源与摘录时摘要

- `exec-plans/active/ADHOC-0024-fit-sqlite-parser.md`；SHA-256 `3ead6b813cb92c2e734ba71d68c9059e8c817bc4df519850e913b577d2162433`。
- `exec-plans/active/ADHOC-0031-local-web-system.md`；SHA-256 `8a49fa013ceeba5110ce911ccad4e62a512165e517c48a7971b646d971eeb277`。
- `exec-plans/evidence/ADHOC-0031/planner-v2.md`；SHA-256 `348f8daf02a3d46fd7e4eac83456d0f11b7b69117cccdd8813d41cc2b6592b9f`。
- `exec-plans/evidence/ADHOC-0031/parent-contract-review-v2.md`；SHA-256 `97099746d9da215507edc6d11376846347f05db178be9c996f4aa7b2b6aa2bdb`。

## 用户要求 U31

| 要求编号 | 已明确的正常结果与范围 | 来源 |
| --- | --- | --- |
| U31-01 | React前端、FastAPI后端；清爽简洁的参考风格。后端同时服务前端静态页面，前端默认编译到后端web目录；本地8080，无账号认证。展示最新FIT同步状态，浏览/搜索已解析数据和AI总结，提供/api/下接口。无认证不等于不测试。 | 用户第1项 |
| U31-02 | Python基于pygarminconnect每三小时检查新活动，下载并按确认命名存入states；首次同步最近七天；新FIT命名为`states/activities/YYYYMMDD-实际FIT字节SHA256.fit`（UTC日期，未知日期`unknown-SHA256.fit`）。运行适配器使用states/verification/garmin.json，可用刷新机制失效时更新。不能把开发需求扩成无限历史下载、任意账户操作或强行绕过MFA。 | 用户第2项；D31-01确认 |
| U31-03 | AI模块使用可配置base_url的兼容API，私有配置在`states/ai.json`；负责发送/接收和工具调用循环，正常直到无tool calls，不负责业务上下文封装。用户允许真实请求、真实数据不限且暂不设请求/费用上限；密钥仍不进Git。错误/截断/越权/资源耗尽必须明确失败，不将半份结果保存为完整报告。 | 用户第3项及已有错误/全量边界；D31-02确认 |
| U31-04 | 独立Context封装运动总结、日总结占位、周总结；周模式由程序取得过去七天运动总结。公共组成包括角色、tools README摘要、references README清单、多轮历史及当前对话；AI可按需读取longdou资料。活动总结按中国时区每日凌晨4点自动触发；多轮历史仅内存保存，数据库只记录结果。日报不接健康数据、不生成日报或新增业务表。 | 用户第4项；D31-03确认 |
| U31-05 | 同批实现既有FIT解析、records查询、实际工具索引、活动/周报告存储；保留四张业务表12/4/3/3列并新增获准config参数表、原record顺序、完整采样、真实running和宿主授权、全文summary、自增周报ID及统一UTC时间锚。 | 用户第5项、ADHOC-0023～0028已确认设计 |
| U31-06 | 新实现和测试同交付，串行Developer、全新只读Validator、主Agent最终亲验。私人数据不进Git，测试用合成隔离实例；业务实调用与未运行检查分别记录。 | 当前AGENTS及既有项目边界 |


## ADHOC-0024 验收与字段要求



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


## 已审核目录与所有权

3. 原四张业务表列数12/4/3/3不变；按新授权增加一张config参数表。采用`key TEXT PRIMARY KEY NOT NULL`、`value_json TEXT NOT NULL`、`updated_at_utc TEXT NOT NULL`。活动和活动报告的TEXT身份主键也必须显式非空；SQLite自增ID继续由数据库生成。
4. 目录A保持：运行/共享实现物理位置在`source/skills/<skill>/scripts/`和`source/skills/_shared/scripts/`，Python导入名可为trainlab，不等于批准`source/trainlab/`作为另一实现根。包映射由Developer决定；不临时改sys.path。`source/tools/`仅放能力说明，现有检查脚本移到适用的共享检查或测试位置并保留检查覆盖。前端仍为React，不能用字符串构建壳替代；不要求本轮完成业务页面。

## 已审核条款的边界

| 条款 | 审核及本轮界限 | 消费者 |
| --- | --- | --- |
| /01 所有权 | 采用模块职责与单一修改者；本轮落实目录/导入检查，不提前实现所有服务 | 全部阶段 |
| /02 JSON | 采用四类容器、活动内共用字段字典、来源分离、记录时间证据、默认123和全量records返回形状；公开Schema单一来源，内部字段ID和字典引用有交叉检查。大整数/原字段bytes表示只用于可解释字段，不开放整个FIT或被排除的私人身份。新增JSON结构是实现载体，不恢复被否决的业务元数据 | B1/B2 |
| /03 时间/完整性 | 采用有时区输入、UTC固定六位小数及Z、原顺序、全链式校验、缺失不造值。零record是否合法留B1-T1依据固定SDK/协议证据判定，不预先宣布所有零record失败或成功。初次B0仅做时间与DTO校验，不能冒充FIT解析 | B1 |
| /04 身份/重复 | 采用实际字节SHA、同字节幂等、旧原件不改名、已知远端来源冲突不自动覆盖、事务重解析失败保旧。已有活动报告与改变事实冲突时停止维护，不新增重解析UI/自动补报；本轮写可执行输入结构和协议，真实仓储留B1/B3 | B1/B3/B4 |
| /12 容量/一致视图 | 采用存储容量与模型发送容量分开、边界等于可接受/超限整体失败、运行内只读事务视图、单进程协调写入、普通rollback journal、无活库immutable。B0落实内部类型、输入约束和协议；数值由后续适用环境检查确认，不能把缺模型参数变成B1不能入库。采样周配额待用户决定 | B1/B2/B5 |

## 被采用的 B1 技术拆解

### 0031-T2/01：接口与唯一修改者

| 模块/落点 | 输入 → 输出；所有权 | 禁止跨界 |
| --- | --- | --- |
| `source/skills/fit-store/scripts/`；共享仓储在 `_shared/scripts/` | 受控原件引用 → ParsedActivity → 整场导入结果；唯一修改 activities/records | AI、Web、同步器不各写入库 SQL；不生成 AI 报告 |
| `source/skills/reports/scripts/` | 一次运行输入、完整文本 → 活动/周报告；报告仓储唯一修改两张报告表 | 传输层、工具和 Context 不保存报告 |
| `source/skills/context/scripts/` | 运行视图＋模式＋内存历史＋当前对话 → messages＋tools 声明＋可信执行环境 | 不由模型指定活动集合、时间锚、库路径或角色 |
| `source/skills/ai-client/scripts/` | messages＋固定 dispatcher＋技术容量 → 最终全文或明确错误 | 不取七天数据、不读 FIT/DB/秘密文件、不拼业务角色 |
| `source/skills/garmin-sync/scripts/` | 认证适配、窗口、检查点 → 原件和同步状态，再调用导入服务 | 唯一刷新认证/安装新原件；不启动报告收费 |
| 共享 ConfigRepository | 已校验非秘密参数 → config 表；运行开始时读取不可变参数快照 | 其他模块不自行改 config；模型无配置工具 |
| `source/skills/local-web/scripts/` | 仓储/状态/报告宿主服务 → `/api/` DTO 与静态页面 | 不直连 Provider；静态根只能是 `source/skills/local-web/web` |

Python 导入名可以是 `trainlab`，但运行与共享模块的物理实现仍须位于已批准 Skill/scripts。不能把当前 `source/trainlab/contracts/` 自发落点当架构例外；具体打包映射由实施者选择，主 Agent 核对目录 A。

### 0031-T2/02：四类 JSON 与传递格式

建议首版 activities.schema_version 为整数 `1`，records 工具协议为字符串 `fit-records/1`；二者分别表示存储格式和接口格式，不表示内容修订。公开 Schema 放 `source/schemas/`，共享验证器和工具声明引用同一来源。

**共同规则**：UTF-8 严格 JSON；拒绝重复对象键、NaN/Infinity、坏类型；JSON 列落库为 TEXT，离开仓储即解码对象，不双重编码。声明的结构键拒绝额外键；字段字典的动态字段 ID 是明确允许的映射键。不得借 JSON 加回被否决的状态、版本、质量列或把全文 summary 强制包装成元数据对象。

为避免每条采样重复长说明，采用**活动内共用字段字典**：

- `FieldSet = {"standard": {字段ID: 值}, "developer": {字段ID: 值}}`。
- 字段 ID 按文件首次出现分配 `f0、f1…`，仅在该活动内解释。字典描述至少包含：`message_number`、`message_name`（未知为 null）、`field_number`、`name`（未知为 null）、`base_type`、`unit`（未知为 null）、`origin`、`source_ref`、`definition_index`、`chain_index`、`component_of`（不适用为 null）。
- `origin` 取 `direct/expanded/merged`；默认不启用会改写原 record 集合的 HR 合并。原字段和组件展开字段必须分别有身份，不能覆盖。SDK 已换算的值不得再次 scale/offset。
- Developer 来源用活动内别名 `d0…`，由链式片段、developer_data_index 及实际来源定义绑定；字段重定义产生新字典项。相同名称、不同开发者或定义不能合并。别名可解释来源差异，但不暴露设备序列号/私有用户身份。
- 值为有限 JSON 标量、null 或保持顺序的数组；超出前端精确整数范围的整数用 `{"integer":"十进制整数"}`，不能浮点近似。无法解释但可完整解码的字段字节用 `{"bytes_hex":"小写十六进制"}`；这些对象只能有对应单键，不能嵌入任意元数据。字典补充 `value_form=physical/raw` 区分已换算值与未知原值，不凭数字形状猜含义；这不是开放 FIT 原字节下载。
- 未定义字段不造键；文件定义存在但该值为类型规定 invalid 时保留键、值为 null；有效 0 保留 0。未知语义不等于解码损坏；坏长度/类型/解码失败不能伪装为 null。
- 字典保存于 sensors_json；每份对外结果只附解释其实际字段所需的字典与来源别名，**不整体发送 sensors_json**。

| 列/DTO | 固定结构及归属 |
| --- | --- |
| basic_json | `{sport, sub_sport, start_time_utc, end_time_utc, messages}`；前四值与 SQL 列一致，messages 保存 file_id/activity 等允许的基本信息，剔除私有身份字段 |
| summary_json | `{messages:[Message…]}`；保存所有 session 的整场原生摘要，而非挑几个熟悉指标；不是 AI 报告 |
| segments_json | `{items:[Message…]}`；保存实际 lap/split/set/length 等原生分段，保留类型、原始顺序和原生关联字段；不猜热身/恢复，不相加重叠层次 |
| sensors_json | `{field_definitions:{f0:Definition…}, developer_sources:{d0:Source…}, messages:[Message…]}`；Definition 为上列固定字段，Source 为 `{chain_index,developer_data_index,application_name,manufacturer}`，后两项未知为 null；来源别名区分同索引重定义，不携带设备私有身份。保存第四类实际非 record 信息，不复制 records 数组 |
| Message | `{message_index, chain_index, message_number, message_name, fields:FieldSet}`；message_index 按数据消息原始流从0计数，不能用分组后重排冒充原序；关联依据原生索引/时间证据，不靠相邻位置猜 |
| metrics_json | `{standard, developer, time_evidence}`；前两项为 FieldSet 中的两映射，第三项为原采样时间证据；record_index/timestamp_utc 仍在 SQL/结果记录三字段中 |
| time_evidence | `{kind, raw, unit}`；kind 为 `absolute/relative/local/invalid/missing`，raw 为原值或 null，unit 为已知单位或 null；不能把相对设备时间伪造成 UTC |
| 默认123 DTO | `{activity_id, schema_version, basic_json, summary_json, segments_json, field_definitions, developer_sources}`；包含三类全文和最少共用解释，不含 fit_path、完整 sensors 或 records |

该结构定义承载方式，不把参考文档中的几项字段当白名单。B1-T1 必须按固定 SDK/Profile 列出实际消息→四类的映射；未知扩展消息也要保留可解码的结构/来源，不能悄悄忽略后宣称完整。若 SDK 无法提供原顺序或必要定义证据，报告能力阻塞，不能改成“SDK 输出多少就算全部”。不新增第五类业务表。

### 0031-T2/03：时间与完整解析

- SQL 绝对时刻统一规范为 UTC RFC3339、固定六位小数和 `Z`，例如 `2030-01-01T00:00:00.000000Z`；输入允许带偏移但必须先正规化，拒绝无时区的绝对时间。日期命名按正规化后的 UTC 日期；小数时长不取整。
- FIT start 只能来自可确认的 session 开始；end 优先使用同一 session 的 start＋原生 elapsed 等可核验证据，不能用 timer 或任意汇总 timestamp 顶替。无法确认填 SQL NULL，原始时间语义保留在 JSON。
- 多 session 必须完整保存；不能拿第一 session 的 running 给整个多运动文件授权。存储范围与分析范围分开，铁三仍不分析；无法得到唯一真实运动大类时不授予 running 权限，原始 session 类型保留。
- 完整解析包括完整字节读取、所有链式部分的长度/CRC/Definition/消息解码检查、所有 errors 处理、消息与字段计数/来源可复核。不是只看扩展名、is_fit 或第一段 SDK 返回值。
- 合法可选缺失不淘汰活动/record；重复时间、不规则间隔、相对时间、未知语义不补点、不合并。record_index 对所有实际 record 从0连续编号，跨链式片段延续原顺序。
- 零 record 与结构缺失分开：公开参考 `references/garmin-fit-parsing.md` §4 将 record 列为 Activity 必需消息，目前材料没有证明通用零 record Activity 的合法例外。**不把所有零 record 一律当合法成功**；B1-T1 依据固定协议/SDK证据落实必需消息判定及可证明例外。数据库中确属合法且记录集合为空时，查询成功返回 `[]`；活动不存在、SDK 漏解码或结构不全不能用空数组代替。
- 在解析结束并校验全部 DTO 前不提交活动/record 行；任一子行失败整场回滚。parsed_at_utc 是该次成功解析处理时刻，不是活动时间。

### 0031-T2/04：文件身份、重复与重解析

1. activity_id 永远是实际 FIT 字节的完整小写 SHA-256。Garmin 下载解包后计算，不用 ZIP 摘要、远端 ID 或旧文件名的64位部分代替。
2. 新原件用 `states/activities/YYYYMMDD-SHA.fit`，未知日期用 `unknown-SHA.fit`；未知日期后续可知也不自动改旧原件名。同 SHA 的不同文件名/远端 ID 只导入一行，重复导入不更新有效行、parsed_at 或报告。
3. 不同 SHA 不合并身份。同一远端活动已对应另一个 SHA 时标记 `SOURCE_CONFLICT`，保留新旧原件和关联证据，不自动覆盖、二次计入或删除；同步检查点记录此冲突，不添加业务元数据列。
4. 不以标题/时间相近强行合并独立运动；没有可靠来源关联时，不承诺识别所有重新导出的重复活动。已知来源冲突未解决前，相应分析返回明确冲突而非双计。
5. 首版不新增重解析 UI/自动重解析。受控维护入口必须排空运行视图、验证原件 SHA、先完整解析，再事务更新两表，不用 REPLACE/删除父行触发报告丢失。无内容变化为幂等；失败保留全部旧数据。
6. 已有活动报告且重解析改变其依赖事实时，先返回 `REPARSE_CONFLICT`，不悄悄保留失配报告或自动付费重生成；本轮不承诺自动修订历史报告。无报告的合法重解析可原子更新；历史 weekly_report 始终作为当时结果保留。

