# ADHOC-0031 规划调整：0031-T2 与阶段衔接

本稿供主 Agent 审核，**不是已经批准的实施合同或 B0 验证结论**。仅写本次绑定的规划产物，未修改仓库、读取私人 states、安装依赖或发出业务请求。

## 1. 理解、依据和首次规划未闭合之处

当前目标仍为 U31-01～06：本机 8080 React/FastAPI、三小时 Garmin 增量、独立 AI 传输/工具循环和三模式 Context、既有完整 FIT/records/全文报告；不恢复邮件、旧产品或健康日报。沿用 B0～B7、0031-T1～T7，以及 ADHOC-0024～0028 各自 T1～T4。

依据及优先关系：

- `exec-plans/evidence/ADHOC-0031/user-answers-2026-09-16.md` 第5～7行、本次任务中的最新用户原意：首次最近七天、UTC 日期＋实际字节 SHA、旧原件不改名；真实 AI 请求/数据不限、暂不设请求/费用上限；中国时区每日 04:00 活动总结；允许 config 参数表；无活动周入库固定全文；历史仅内存。
- `exec-plans/active/ADHOC-0031-local-web-system.md:13-36`：U31 要求、目录 A、受限资料读取、D31-01～04 已确认部分。D31 编号及原累计失败次数 0 保留；本次没有实施修复失败，不新增“失败一轮”。
- ADHOC-0024～0028 的“当前设计/验收要求”：四张业务表仍为 12/4/3/3 列，SQLite 自增系统表另计，新增 config 是系统参数表，不是放宽业务列。
- `exec-plans/evidence/ADHOC-0031/planner-v1.md` 是原建议，不是完整批准记录。参考资料是来源解释，不独立授权行为。
- `AGENTS.md`、`subagent-templates/planner.md`：Planner 只返回拆解和事实；目标变化交用户，工程细则交主 Agent 审核。

已核对分支 `work/adhoc-0031-local-web-system`、HEAD `9db8bb1dda5922e85fe42581e27d2428dbc9f195`。`source/` 为未提交候选；已有协调记录改动，索引为空。当前代码中有列定义、错误外壳、时间函数、内存历史及 Web 入口骨架，例如 `source/trainlab/contracts/{schema,errors,time,session,config,web}.py`。**这些位置只用于衔接定位，不因代码存在就批准其目录、私有配置形状或业务选择。** B0 的质量由另一个 Validator 审核，本稿不重复缺陷审计或引用其结论。

| 原编号 | 首次遗漏/矛盾及证据 | 本次调整及影响 |
| --- | --- | --- |
| 0031-T2；D31-01 | v1 §4.1 只给原则，JSON 字段身份、时间证据、重复/重解析仍分散在旧 T1 | 统一下列 T2/01～07；固定字节 SHA 身份与原件保护；B1/B2/B3 共用，不各造格式 |
| 0031-T2；D31-02 | v1:116-118 的 8轮/16次/180秒、付费上限、滚动七天20次均为建议 | 不设业务请求/费用限额；技术容量与死循环防护单独建合同；旧采样周配额的适用性仍需澄清，不能替用户取消或重定义 |
| 0031-T2/T5；D31-03 | v1:42 的磁盘会话、v1:108 的空周错误已被答案替代；原先手动生成建议未闭合 | 历史仅内存，空周固定结果正常入库；已确认活动 04:00 时点，但批次范围、错过/缺报策略仍无答案 |
| 0031-T2/T3/T5 | v1 没有统一冻结配置所有权、报告提交不确定、运行一致视图 | 加入非秘密参数所有权、一次运行时间锚、保存重试和读写门协议，避免“摘要是旧的，records 已更新” |
| 0031-T1/T2；D31-04 | v1 把已有资料读取能力再列为授权问题；候选运行包位置并非目录批准 | 不重问资料授权；继续采用 Skill/scripts，source/tools 仅索引；Python 包名与落盘位置解耦 |
| 0031-T2 及旧 T1 | “各旧 T1 前冻结”没有列出冻结产物和可局部放行条件 | 下列合同按消费者分开冻结；B1 不等待周自动时点、缺报收费或采样周配额决定，但 B0/T2 不因此整体虚标完成 |

## 2. 精确合同建议（主 Agent 可批准的工程细则）

以下 `0031-T2/01～13` 是 T2 内的合同条款，不是新功能、阶段或另一套完成状态。标为“待决定”的分支不填默认行为。

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

### 0031-T2/05：工具、正常/错误外壳

`get_running_records` 的机器参数固定：object，required=`[activity_id]`，activity_id 为64位小写十六进制字符串，additionalProperties=false。唯一参数不变。

成功/空结果：

```json
{
  "schema_version": "fit-records/1",
  "ok": true,
  "activity_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "data": {"field_definitions": {}, "developer_sources": {}, "records": []},
  "error": null
}
```

每条 records 仅 `{record_index, timestamp_utc, metrics_json}`；活动 ID 不在各 record 或字典重复。结果按 record_index 原序、全部或明确失败，不分页、不回读 FIT 补点。schema_version、数量、连续索引和字典引用必须共同校验。

错误同样保留上述顶层键，`ok=false,data=null,error={code,message,details}`；无法确认的 activity_id=null。先验证参数与本次授权，再在同一视图查询 sport/schema/records；无跑步上下文不注册工具，混合上下文也逐 ID 查真实 running，不设 sub_sport 白名单。未授权 ID 返回 `TOOL_NOT_ALLOWED`，不借错误披露另一活动存在性。

API/任务共用 `{ok,data,error}`；records 额外两个顶层身份字段不丢。所有 errors 的 details 只含受控类型和脱敏值，不返回任意异常对象、路径、秘密或原始请求。建议冻结如下分类，详细原因用固定 reason 值，不无限扩枚举：

| 错误类别 | 代码例子 / HTTP 映射 | 副作用边界 |
| --- | --- | --- |
| 输入/协议 | INVALID_ARGUMENT 422；SCHEMA_UNSUPPORTED、DATA_INVALID 409；AI_PROTOCOL_ERROR 502 | 无部分结果 |
| 存在/权限 | ACTIVITY_NOT_FOUND、REPORT_NOT_FOUND 404；TOOL_NOT_ALLOWED、SPORT_NOT_ALLOWED、SPORT_UNKNOWN 403 | 不执行越权工具 |
| 来源/时间/报告冲突 | SOURCE_CONFLICT、REPARSE_CONFLICT、MISSING_ACTIVITY_REPORTS、WINDOW_INDETERMINATE、NO_ANALYSABLE_ACTIVITIES 409 | 不假冒空周/完整报告 |
| 配置/服务 | CONFIG_UNAVAILABLE、CAPACITY_UNVERIFIED、DATABASE_UNAVAILABLE、AUTH_REFRESH_REQUIRED 503；EXTERNAL_SERVICE_FAILED 502 | 脱敏；认证需人工时不绕过 |
| 技术容量/循环 | RESOURCE_LIMIT 413；TIMEOUT 504；LOOP_NO_PROGRESS 502；RUN_BUSY 409 | 整体失败，不提交半文 |
| 重试/占位 | COMMIT_UNCERTAIN、REQUEST_STATE_LOST 409；NOT_IMPLEMENTED 501 | 不自动重做收费/插入；日报无调用 |

### 0031-T2/06：报告保存、重复与提交不确定

- activties_report 采用 activity_id 主键/外键，每活动一条当前报告；start_time_utc 由同一视图的 activities 复制，包括 NULL。summary 必须是非空白完整字符串，校验可判断空白但**保存不 trim、不统一换行、不重新摘要**。
- 常规重复生成请求有当前报告时返回当前报告，不把自动任务变成每日覆盖全部历史。宿主明确要求重新生成时，只有完整生成并保存成功才替换当前全文；失败保持旧报告。不新增报告历史表、模型/生成时间列。
- weekly_report 每个明确的新运行 INSERT，由 SQLite 分配 ID；同 T 的不同运行可有不同 ID，不要求连续、不按自然周覆盖。
- 宿主使用内存 request_id 注册表，绑定实例、模式、对象和输入。相同 request_id＋相同输入返回运行中/原结果，不重复发 AI 或保存；同 ID 不同输入为冲突。它不是跨重启会话数据库。
- 已知事务未提交且完整文本仍在内存，可只重试保存，绝不能为 SQL busy 再调用 AI。重试需先核对同一运行视图/输入仍成立。
- 提交结果不明：若已知本次 rowid，可读取该 ID 核验；不能仅凭同 T/同全文推断是本次记录。无法确认则 COMMIT_UNCERTAIN，暂停该请求的自动重放，不自动再次付费/INSERT。
- 重启丢失 request_id 状态后，不承诺 exactly-once，不把同 T 设唯一约束；告知 REQUEST_STATE_LOST，先查看已保存结果。新显式运行与保存重试必须区分。
- 周/活动结果响应分别为三列业务字段组成的对象；request_id、conversation_id 可作为响应中的运行关联信息，不写入 summary 或增列。

### 0031-T2/07：周窗口、缺报、空周

1. 报告宿主获得执行权后捕获一次实际 UTC 时间 T，在同一视图用 `T-7×24小时 <= start_time_utc < T` 选活动；T 贯穿取数、Context、run_time_utc。等于下界纳入、等于上界留待后续；跨界活动按开始归属，不裁其 records/分段。不是中国时区七个自然日期。
2. 周输入包含选中活动的**已有完整活动总结＋默认123事实**；正文、活动身份、运动开始时间一一对应。不得改为只取 FIT 摘要、只取最近若干条或让 AI 自行查询活动清单。该依赖对应 ADHOC-0027→0028/0031-T5。
3. 开始时间未知不能猜进七天；Context/响应必须披露未能归属的数量。若这些记录或已知窗口内下载/解析失败使“没有任何活动”无法确定，返回 WINDOW_INDETERMINATE，不入库空周固定文本。正常报告也不得隐藏已知缺失输入。
4. 必须区分：真正空窗口；有活动但尚无活动报告；有活动但不属于获批分析范围。后两者不能写“本周无任何运动记录”。只有真实空窗口分支直接由程序返回并保存全文 **`本周无任何运动记录`**，不依赖 Provider、不加换行/解释文字；仍有自增 ID 与实际 T。
5. 存在获选活动但缺报告时，检测结果固定为 `MISSING_ACTIVITY_REPORTS` 和缺失 activity_id 列表；禁止送半份周输入。随后是“本次阻塞、等待已有任务”还是“先补活动报告再继续”，属于 D31-03 剩余决定；**未决定前只完成检测与安全停止，不把停止永久定为产品要求，也不自动补费**。
6. 周自动触发没有已确认时点；`ADHOC-0028:60` 明确周日15点只是示例。可实现/测试显式宿主调用的周服务，不能顺手注册周定时任务。

### 0031-T2/08：config、调度与同步接口

建议采用一张最小 config 系统表：`key TEXT PRIMARY KEY NOT NULL, value_json TEXT NOT NULL, updated_at_utc TEXT NOT NULL`。三列只是工程建议，用户批准的是新增参数表能力；其他业务表列不动。

- 首批非秘密参数白名单：`sync.interval_seconds=10800`、`sync.initial_lookback_days=7`、`reports.activity.timezone="Asia/Shanghai"`、`reports.activity.local_time="04:00"`，以及 T2/12 的技术容量参数。各参数有严格类型/单位校验；不存在时写入默认，不在每次启动覆盖既有值。
- 未决定的 `activity_batch_policy`、`misfire_policy`、`weekly_trigger`、`missing_report_policy` 不填想当然的默认值；注册自动任务前检查所需政策是否已经批准。技术/运行状态不伪装成活动质量列。
- config 不保存密钥、Token、Garmin 认证、原始 messages、工具正文、FIT/报告副本；AI endpoint/model/credential 以 `states/ai.json` 的适配结果为单一来源，避免在表与私有文件双写秘密配置。允许配置表不等于本轮新增设置页面。
- 本次未读秘密文件，因此不承诺其顶层键名/嵌套形状；当前 `source/trainlab/contracts/config.py:30-42` 里的 required_keys 只当候选。B4/B5 获授权适配时在本地安全核实，映射成内部类型，不要求用户重填可自行查明的字段，不输出原值。
- `SyncStatus` 固定包含 `state,last_attempt_utc,last_success_utc,next_due_utc,counts,last_error`；counts 分开列 `discovered,downloaded,imported,pending,failed`。下载成功不等于解析成功；最新状态对 Web 脱敏。
- Garmin 每3小时检查，单实例锁/单调度器；首次固定 `[S-7天,S)`，S 是第一次实际扫描的上界，重启继续该窗口与待处理项，不偷偷向历史扩展。后续从成功检查点连续推进并重扫获准时间范围，枚举与下载/解析待项分别持久化，失败不推进成成功。
- 当前授权起点之前不补历史；枚举获准范围的完整分页可以重复检查，不能只看第一页。分页不进展或时间无法可靠过滤时明确未完成，不用 max ID 假定时间序。远端无法提供可靠时间/分页语义时报告限制。
- 认证仅由适配器刷新，MFA/无法刷新则 AUTH_REFRESH_REQUIRED。原件临时写入、验证实际 FIT/安全解包、原子安装；不改旧文件，不跟随任意链接。重启可恢复同步待项；不恢复旧外部 CLI。
- 04:00 是 `Asia/Shanghai` 当地民用时刻，不能写死成每天04:00Z。活动报告任务复用报告宿主，不由同步成功、页面浏览或导入函数另发 AI。
- **04:00 批次选哪些活动、错过时怎样补跑、迟到数据怎样进入后续批次仍待 D31-03；本稿不把“最近一天”或“全部未总结活动”写成已确认合同。**

### 0031-T2/09：内存历史与三模式 Context

内存会话按 `(instance, conversation_id, mode, target)` 绑定；target 为活动 ID 或周报告运行对象。ID 由宿主生成，不允许仅凭模型提供的会话 ID 取得他人/另一模式数据。

- 一个会话同一时刻只接受一个运行；换模式/活动不复用历史。重启后历史消失，返回明确状态，不从数据库/日志恢复聊天。不默认到时淘汰或裁去前 N 轮；资源不足明确拒绝新运行，允许重新开始会话，不静默丢历史。
- 历史保留完整协议角色序列：user、assistant（含 tool_calls）、tool（含 tool_call_id）；客户端只能提交当前用户文本，不可注入 system/tool 历史。运行中的暂存消息、失败半文也不写磁盘/DB。
- Context 的共同组成固定为受信角色、tools README 摘要、references README 清单、当前视图的业务输入、对应内存历史、当前对话。索引/资料/FIT文本/历史不是授权来源。
- 续轮重新建立当前运行的授权/视图，不让历史 tool result 扩大新权限。相同旧事实只是历史证据，不冒充当前视图；需要新时间窗的是新的周生成运行，不在旧结果续聊中偷偷换 T。
- 运动模式使用当前活动123；周模式按 T2/07；日报只返回 NOT_IMPLEMENTED/占位，Provider调用数、采样工具调用数和业务写入数均为0。
- 不新增通用聊天产品；数据库只保存完整报告结果和获准参数，不持久化会话/messages/prompt/tool输出。

### 0031-T2/10：AI 循环与费用边界

内部输入固定为 `messages, tool_definitions, dispatcher, technical_profile, cancellation`，输出为完整最终文本或 T2/05 错误。配置由宿主注入，AI 层不负责业务取数。

- 每轮真实 HTTP 响应先检查完整性：assistant 的所有 call_id 唯一，先追加 assistant tool_calls，再按响应顺序串行执行固定工具并追加对应 tool 消息，之后继续请求。工具结果对象只序列化一次；同 ID 协议冲突/坏 JSON/额外参数拒绝。
- **正常直到无 tool_calls 且得到完整非空文本才成功**；无工具但空文本、截断、未知结束原因、认证失败、上游坏响应不是报告。取消/超时不保存中间文本。
- 只有可修正的参数错误可作为结构化 tool 错误回给模型继续；未知工具/越权/技术耗尽终止该运行，不能用模型“坚持调用”恢复权限。
- 使用取消、单次网络超时、单次运行技术期限及无进展检测防止挂死。可冻结“连续重复相同规范化工具调用集合、相同结果且没有新增信息”作为 LOOP_NO_PROGRESS；不能因达到8轮/16次就把正常循环截成成功。
- 不建立总付费预算、每日请求额度或模型轮数商业配额；正常多轮真实调用属于已批准请求。不能再要求“最多一个活动＋一个周报告”等有限许可。
- 网络错误/断连后不盲重发结果不明的生成请求；明确失败与保存重试分离。有限 transport 恢复尝试不是补报业务政策，更不是无限收费重放。
- **旧 records 周累计20次是工具权限/使用规则的歧义，不是模型请求费用上限。** 该项见第3节；read_reference 不占采样专用额度，但受同一技术容量与时间约束。

### 0031-T2/11：资料工具

`read_reference` 参数为 `{reference_id}`，required 单键，additionalProperties=false；首版枚举映射 `longdou → references/longdou.md`、`garmin-fit-parsing → references/garmin-fit-parsing.md`，只包含公开索引内条目。

成功为 `{ok:true,data:{reference_id,title,content},error:null}`；content 为全文。读取前核对真实路径在公开映射内、是允许的普通文件；不接受路径/URL/SQL、不跟随正文链接，不读取原 XLSX/私人证据。资料过大整体 RESOURCE_LIMIT，不能只传前半篇却称完整。

tools README 的摘要和 references 清单由宿主从公开索引装配；机器注册表才执行权限。引用中的建议/未经证实内容维持原限定，不把龙豆43项字典当成每场都有43项值，也不把标准/Developer指标合并。对应 `references/longdou.md` §1、§5。

### 0031-T2/12：技术容量与同一运行视图

**不设费用上限≠设备内存、模型上下文或等待时间无限。** 容量配置只作工程保护，不能借机少传获批数据。

内部 `TechnicalProfile` 必须明确：`max_serialized_bytes,max_materialized_bytes,max_input_tokens,max_output_tokens,context_window_tokens,http_connect_timeout_s,http_read_timeout_s,run_deadline_s,db_wait_timeout_s` 及计算模型 token 的方法/来源。不得沿用 v1 的8/16/180为默认验收值；硬件/HTTP参数由主 Agent 根据本地检查批准，模型项在安全读取配置和可核实能力后绑定。不能从“密钥文件存在”推断容量无限；缺证据为 CAPACITY_UNVERIFIED，不让用户重复提供文件里已有的信息。

- 入库容量与发送容量分开：能完整落库的长活动不能仅因当前模型装不下而不导入。Parser/SQLite内存限制与真实模型容量分别验。
- 每次模型请求前计算整份 messages＋工具声明＋完整工具结果＋输出预留，要求 `输入token＋输出预留 <= context_window_tokens`，同时满足字节/内存预算。工具先做整体资源预检、结果完整序列化后再传；不能已传一半才当成功。
- 确定值正好等于限制可成功，超过则整个运行 RESOURCE_LIMIT；不裁123、历史、资料、records 或报告，不改成分页/统计窗/更短总结。由用户显式换会话或更大容量配置，不自动改目标。
- 运行期限使用单调时钟；超时取消外部工作并收口状态，不影响已保存报告。期限的具体值是待主审核的技术配置，不是请求收费授权；B1不需要先知道真实模型容量。

首版采用**单进程、单业务写入协调门＋rollback journal 只读事务**，不引入快照库、内容版本列或活库 immutable：

1. 报告宿主取得运行门后捕获 T，读取参数并打开只读事务；该事务内选活动、123、活动报告、sport及后续 records。
2. 同一运行期间业务表写入/重解析/参数变更排队；Web可只读浏览，原件下载可继续安装，导入提交等待。未持有跨网络的 SQL 写事务。
3. 同一门保护读事务结束到报告写入的过渡；完整结果校验后结束读事务，再由报告仓储短事务提交，之后释放门。不能在两者之间让重解析抢写导致新事实配旧报告。
4. 运行门/SQLite等待均有明确超时，返回 RUN_BUSY/TIMEOUT 而非静默漏任务。已下载待导入项持续保留；自动报告错过/重试策略另待决定，不靠无限队列补费。
5. 缓存仅当前运行，键至少绑定实例、run_id/视图、工具名、activity_id；命中仍重新核对当前授权。跨请求/重启不复用 records 缓存。若周配额保留，由宿主在工具实际派发前原子预占，不能每进程重置。
6. records 工具使用受控连接、query_only/固定参数化查询、禁止 ATTACH/扩展/写语句；自身不创建缺失库，不产生业务写入。rollback 策略下核对只读调用前后 DB/sidecar，不能只凭 mode=ro 声称无副作用。

这是够用的一致性方案；其代价是 AI 运行时推迟导入提交，必须在 B5/B7 并发场景实际检查。若要换 WAL/快照方案，仍须保持相同用户行为与只读边界并独立验证，不因代码困难增加版本列。

### 0031-T2/13：Web/API 接口边界

沿用 v1 的最小浏览/搜索服务，但只发布真实已接线能力：`GET /api/health`、`/api/sync/status`、`/api/activities`、`/api/activities/{activity_id}`、`/api/reports/activities/{activity_id}`、`/api/reports/weekly`、`/api/reports/weekly/{id}`。列表使用 `q,sport,from,to,page,page_size` 中适用字段，固定稳定排序；列表分页不改变单报告全文或 records 全量语义。健康接口只返回配置就绪布尔值，不返回秘密配置形状/值。

生成调用统一经过报告宿主；活动定时器与获批的显式调用不能各写一套逻辑。周定时和补报入口须等行为决定，不以路由注册代替授权。不为本轮新增任意聊天/原件下载/SQL/设置产品。

默认只监听 `127.0.0.1:8080`、同源、无账号；无认证不取消 Host/Origin、XSS、API404和静态路径检查。页面按文本安全展示完整报告；仅 web 目录可静态服务。前端生产构建直接输出该目录，不能恢复集中发布层或清空相邻 scripts。

## 3. 仅真正需要用户决定的剩余行为

D31-01～04 **已确认内容不重问**。下表是原主题中的剩余分支，不把旧决定改回未确认，不等待向本 Planner 追加材料。

| 关联编号 | 已从材料核实仍缺的决定 | 主 Agent 交用户的最小问题 | 暂停范围；独立可做 |
| --- | --- | --- | --- |
| D31-03／活动批次 | 只明确每日04:00，没有选数窗口、迟到和停机补跑规则 | 04:00处理“上一中国自然日的活动”还是“截至本次仍未有总结的活动”（若是其他范围请指定）；错过04:00/晚到/失败的活动，启动或下一批是否补做？ | 暂停自动批次选取、补跑和相应真实AI任务；时钟换算、调度单实例、报告存储/单活动生成服务可做 |
| D31-03／周生成 | `ADHOC-0028:60`排除周日15点自动授权；答案说明正常依赖已有报告，未说明缺报后的动作 | 周报按显式调用即可，还是也要自动（若要，请给时点）；有活动但缺活动总结时，本次等待/报缺，还是先补齐再生成？ | 暂停周自动触发与自动补报；周窗口/缺报检测/齐全输入生成/真正空周固定结果和保存都可做 |
| D31-02／采样配额 | 新答案“不限请求/费用”与旧 `0024:55、0025:55` 的采样周累计20次，无法确定是否同一范围 | 不限是否也取消 `get_running_records` 的旧周累计20次？若保留，请明确统计周的起点/时区和哪些实际派发计次；同请求缓存命中不重复执行的机制继续保留 | 暂停真实采样派发的配额启用及其最终验收；不取消 running/本次授权，不把20次改滚动七天；B1、只读查询核心/参数化配额适配测试可做 |

不能用“不注册采样工具然后声称全功能可用”掩盖第三项。可以完成不依赖采样的 AI/资料流程，但需明确其有限覆盖；正常全量工具闭环仍须补验。

## 4. 稳定任务拆解、依赖及检查预期

检查编号沿用 V31-01～13，只调整受新答案影响的预期；以下均为**拟检查，不是已运行结果**。串行顺序不变，依赖细化不是本实例调度。

| 阶段/原任务 | 对应要求/验收 | 输入 → 输出/接口 | 前置与停止边界 | 正常、错误、边界检查预期 |
| --- | --- | --- | --- | --- |
| B0：0031-T1 | U31-01/06 | 目录A、隔离环境 → 实际工程底座/本地检查入口 | 当前B0独立结果＋主验收；不写受审快照 | 实际最小启动/前端生产构建/目录与静态根，不以声明文件代替运行证据 |
| B0：0031-T2 | U31-02～05；五功能各T1 | 本稿＋确认记录 → 单一Schema、DTO、错误、视图/保存合同、待决定分支 | 主Agent逐条批准工程细则；不把秘密配置候选当实际格式 | 合成JSON正常/坏值/缺失/额外键；每个消费者使用同一类型；决策分支无偷偷默认值 |
| B1：ADHOC-0024 T1→T2→T3→T4 | 0024 AC-01～05；V31-01/02 | T2/01～04、12 → 字段/完整性规范、合成FIT、解析及整场写入 | B0底座受验，B1消费合同冻结；真实模型/调度决定不是前置 | T1固定SDK/Profile、消息映射和合法缺失；T2先造真实字节合成样例；T3全量/事务；T4独立核计数/顺序/来源/回滚/报告表与config保护 |
| B2：ADHOC-0025 T1→T2→T3→T4 | 0025 AC-01～05；V31-03/10 | 完整库＋T2/05/12 → 唯一只读查询与宿主边界 | B1；周配额未决只暂停该政策与真实接线，不假装整个T4已完成 | T1固定接口；T2长活动/非跑步/跨ID/坏JSON/空/超限；T3实现；T4实际只读与全量验证，配额未闭合明确无法判断 |
| B2/B5：ADHOC-0026 T1→T2→T3→T4 | 0026 AC-01～04；V31-03/08 | 查询和受限资料定义 → 索引/机器声明/漂移检查 | B2核心能力；B5真实注册后复验受影响部分 | T1声明协议；T2据实际能力写索引；T3重放示例/签名；T4独立核单一采样工具＋资料工具，不再断言总工具数只能1 |
| B3：ADHOC-0027 T1→T2→T3→T4 | 0027 AC-01～04；V31-02/09 | T2/06 → 活动三列存储/读取 | B1并按序在B2后；自动批次不是存储前置 | T1冻结重复/NULL/全文；T2中文多行与SQL文本样例；T3事务保存；T4全文逐字往返、失败保旧、其他表不变 |
| B3：ADHOC-0028 T1→T2→T3→T4 | 0028 AC-01～04；V31-09 | T2/06/07 → 周三列存储、同T/自增、窗口DTO | B1/0027契约；周定时未决不阻塞存储 | T1时间/保存重试；T2上下界/跨年/同T两份/空周固定文本；T3实现；T4统一T、失败回滚；不以存储通过冒充生成闭环 |
| B4：0031-T3 | U31-02；V31-04～06 | T2/04/08 → 安全认证、分页、检查点、原件→导入 | B1～B3；D31-01已确认，不再索要首次七天授权 | 假时钟3小时、分页移动/循环、中断安装、同SHA/冲突SHA、刷新/MFA；真实联调在现授权范围单列 |
| B5：0031-T4 | U31-03；V31-07/10 | T2/10/12 → 真实HTTP兼容循环 | B2/B3；模型容量后续安全核实，不能虚填 | 无工具全文、多call_id、多轮正常终止；截断/空文/坏协议/越权/重复无进展/取消/技术超限均不保存；不加入付费总限额断言 |
| B5：0031-T5 | U31-04/05；V31-08～10 | T2/06～12 → 三模式Context、内存历史、报告与调度宿主 | B2/B3/T4；仅第3节未决分支暂停 | 123＋全文活动报告、龙豆全文按需、模式/活动隔离、重启历史消失；04:00换算，空周正常入库；缺报不伪造，最终自动政策按用户答案验 |
| B6：0031-T6 | U31-01；V31-11/12 | T2/13＋实际服务 → 8080 API/React浏览搜索和全文展示 | B3～B5可用接口；未接线能力不可伪装已启用 | 生产构建/浏览器、空/错态、筛选/详情/全文；路径/Host/Origin/XSS/API404、秘密不进静态产物 |
| B7：0031-T7 | 全部U31及五功能回归；V31-13 | 固定完整版本 → 独立集成、主亲验、运行说明和适用交付 | 全部适用任务验收，未决行为闭合；不自动合并main | 下载→解析→中国04:00获批批次→活动结果→七天周结果→Web；重启、并发导入/报告、空周与失败恢复；离线/真实请求分别记录 |

### B0 补齐和 B1 可安全开始的门

1. **B0补齐**：主 Agent 先消费独立 B0 审核；本稿不代它裁决。其后补齐已批准目录A的接口承载、公开Schema/合法与非法样例、错误/时间/重解析/事务合同；将私有配置从“猜测文件键名”改为“内部适配接口＋后续安全核实”。影响受审内容的修改须新实例独立验证。
2. **B1硬前置**：0031-T1中B1会使用的工程底座已受验；T2/01～04、05中的records形状、06中的报告表保护、12中的存储/视图边界获主审核并可供B1调用。B1自己的T1再落实SDK/Profile能力证据，不跳过测试先行。
3. **无需等的事项**：周自动触发、缺报补费、04:00批次选择和旧采样周配额不影响B1合成FIT解析/整场入库；真实AI文件形状/模型token值也不是B1依赖。
4. **状态诚实**：主 Agent 可审核将 B1 依赖细化为“B0已验底座＋B1消费合同”，再放行独立可做工作；0031-T2及B0仍保留[exec]并记录仅后续分支待决，不能为了形式上B0完成而填猜测或跳过验证。B0整个完成仍须全部适用任务闭合。

## 5. 只对受影响当前记录的对齐清单

由主 Agent 维护协调记录；本稿未改下列文件，历史快照和 v1 原文不改写。

- `PLAN.md:5,32,38`：四张**业务**表＋允许config系统表；首次最近七天已确认，删除“首次范围尚待确定”的当前限制；“当前没有”只能写经核实的未交付事实，不能让新增骨架冒充产品完成。真实请求已获准，不重新登记有限收费许可。
- `exec-plans/active/ADHOC-0031-local-web-system.md:28,44-60`：写入T2合同索引和按消费者冻结门；将“全部待确认项闭合”细分为D31已确认内容与第3节剩余行为；预算措辞分开请求费用、采样配额、技术容量。阶段编号不变。
- `ADHOC-0024-fit-sqlite-parser.md`：“JSON待定/完整性/重解析”指向同一T2合同及本功能T1；四表保护包含config共存；周20次仍只登记未决适用性，不改滚动七天。
- `ADHOC-0025-fit-running-query-tool.md:22,55,82-131`：保留唯一采样能力，替换已失效“不接API/实际API另授权”现行限制；示例内部JSON与共用字典对齐，周配额待用户澄清但不扩权限。
- `ADHOC-0026-tools-ai-index.md` 的 T3/GATE-02/测试映射：“仅一个工具”明确为“仅一个采样查询工具，另有受限资料工具”；不能把README尚未注册当最终可用，也不能继续把已授权接线写成待新授权。
- `ADHOC-0027-activity-ai-report.md`：重复保存/主键/全文/时间细则指向T2/06；当前自动04:00已确认，但批次与补跑待定；“不读私人/不接Provider”限定为合成检查，不写成整个新目标禁令。
- `ADHOC-0028-weekly-ai-report.md:29,60,65,75`：保留“周日15点不是授权”；“调度接线”不得暗示已有周时点；空周固定全文已经是成功分支，缺活动报告不是空周。存储与生成验收分开。
- 五项旧计划中的迁移基准/历史工作分支只保留其原时点事实；新增当前实施检查点使用本功能分支与实际受审版本，不把迁移HEAD当产品验收版本。“本轮不启动/不实跑”如仍适用于旧迁移，标清历史/合成测试限定，不覆盖0031新授权。
- `source/tools/README.md`、Schema、Prompt、机器tool定义由后续Developer按获批合同同批对齐；不能把v1推荐、当前候选包位置或未验示例升级为要求。MEMORY如要更新仅记录已确认决定及理由，不抄本稿进度。

## 6. 实际检查、限制与下一步

实际只读检查：

| 方式/命令 | 实际结果 | 证据/限定 |
| --- | --- | --- |
| read：AGENTS、Planner模板、PLAN当前部分、0031执行计划、用户答案、v1及0024～0028全文 | 均已读取，未缺必读材料 | 本稿第1节来源定位；未将v1全部视作批准 |
| read/find：source公开文件；read：skills/README、references/README及两篇资料 | 核实当前合同/入口落点和公开来源 | 项目skills索引无技能包；未读取私人states、开发者结果报告或Validator结论 |
| `pwd; git rev-parse --show-toplevel; git branch --show-current; git rev-parse HEAD; git status --short; git diff --stat; git diff --cached --stat` | 退出0；目录/分支/HEAD匹配，source未跟踪，已有7个跟踪协调文件改动及0031新材料，索引无差异 | 仅基线检查；工作区并非干净，不把现存改动归为本Planner所改 |
| 定向 grep：0031、0024/25/28、v1、PLAN及source的函数/契约入口 | 找到上述文件行号与原建议/未决边界 | 一次组合glob查询无匹配，随后按具体路径检索；不把无匹配当要求不存在 |
| 产物检查：Python 解析 acceptance-report、核对围栏；最终 `git rev-parse HEAD; git branch --show-current; git diff --cached --exit-code; git status --short` | 退出0；验收JSON有效、围栏配对；HEAD/分支及未暂存状态保持一致 | 仅产物格式与只读Git复核，不是产品测试 |
| 产品静态/单元/集成/浏览器/真实服务检查 | **未运行** | 本任务是只读规划，不能给B0或产品“通过”裁决 |

读取过程中主 Agent 的协调记录有正常进度回写；本稿不依据它推断受审源码被修改，也未自行刷新验收状态。后续验收仍固定实际代码快照。

残余风险：SDK的完整顺序/未知字段/合法零record能力尚需固定版本实证；私有配置形状、认证刷新和模型真实容量未读取/实测；远端分页移动、迟到和无来源关联的重复导出不能凭规划保证全部识别；单进程一致视图会推迟导入提交，需实测技术期限和等待边界；重启后没有持久会话/请求账本，不承诺跨崩溃生成恰好一次；只对受信本机开放，无账号不防同机恶意进程。

**交主 Agent 的下一步**：审核上文工程细则并同步受影响合同；消费独立B0结果决定补齐与复验；只把第3节少量行为问题交用户，暂停对应分支。满足B1门后可推进其独立范围，无需重做无限规划或冻结全部功能。
