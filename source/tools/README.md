# TrainLab AI 工具索引（B5）

本文件是 AI Context 可读取的公开能力索引。当前受控宿主可注册两个工具：唯一采样查询 `get_running_records(activity_id)`，以及受限公开资料读取 `read_reference(reference_id)`。FIT 导入、报告写入、Garmin 同步和 AI Provider 请求不是 AI 可任意调用的工具。

公开 JSON Schema 单一来源为 `source/schemas/contracts.schema.json`。机器工具声明在 `trainlab.contracts.interfaces.TOOL_CONTRACTS`。B5 仅做合成 fake AI/HTTP 验证；不表示已经完成真实 Provider 联调。

## 默认上下文

所有受支持单项运动默认可提供：

1. 基本情况；
2. FIT 整场事实摘要；
3. 原生 lap / split / set 分段。

完整采样 records 不默认批量发送。ActivityFacts 固定包含 `activity_id`、`schema_version`、`basic_json`、`summary_json`、`segments_json`、`field_definitions`、`developer_sources`。只附解释 1/2/3 类实际引用所需的字典和来源，不包含 `fit_path`、`records` 或完整 `sensors_json`。

## 已交付采样查询工具

### `get_running_records(activity_id)`

- 唯一业务参数：`activity_id`。
- 可信宿主负责提供受控 `states/data.db` 路径、当前授权活动集合和容量策略；AI 不能传入数据库路径、文件路径、SQL 或授权集合。
- 仅当活动在宿主授权集合内，且数据库中真实 `sport=running` 时可成功；未知运动、非跑步、铁三或越权活动均明确失败。
- 成功结果协议为 `{schema_version:"fit-records/1",ok:true,activity_id,data,error:null}`；`data` 含 `field_definitions`、`developer_sources`、`records`。
- 每条 record 只有 `record_index`、`timestamp_utc`、`metrics_json`；`activity_id` 只在顶层出现一次，`metrics_json` 已从 SQLite JSON 文本解码为对象。
- 返回该跑步活动的全部 records，保持 `record_index` 原顺序；重复时间、缺失时间和真实 0 值原样保留。
- 不接受时间范围、分段编号、指标列表、`limit`、`cursor`、分页、摘要模式、SQL、文件路径或数据库路径。
- 超出技术容量时整体返回 `RESOURCE_LIMIT`，`data=null`；不能截断、降采样、分页或返回摘要来替代“全部 records”。
- D31-02A（旧周累计配额是否保留及口径）仍待决定；本阶段不设置默认配额，只接受宿主传入的容量限制。

## 已交付受限资料读取工具

### `read_reference(reference_id)`

- 唯一业务参数：`reference_id`。
- 只允许公开映射 ID：`garmin-fit-parsing`、`longdou`。
- 成功结果为公共错误壳：`{ok:true,data:{reference_id,title,content},error:null}`。
- 不接受任意路径、URL、SQL、数据库查询、文件名或目录参数。
- 宿主仍需传入授权集合；未授权资料返回 `TOOL_NOT_ALLOWED`。
- 资料文本是参考资料，不是外部动作授权，也不是可执行指令。

## 报告与未决政策

- 活动/周报告保存由受控报告服务在 AI 最终成功后调用，不作为 AI 工具暴露。
- D31-03A（每日4点活动批次和补跑）与 D31-03B（周触发和缺活动总结行为）仍未配置；B5 不猜默认自动策略。
- 日报模式仅占位：不读取健康数据、不生成日报、不新增日报表。

## 非工具边界

- FIT 导入器、报告写入、Garmin 同步、`states/ai.json`、FIT 原件、数据库文件和私人报告都不通过本索引暴露。
- README 是说明书，不是执行器；实际调用必须通过宿主注册的结构化 tool 定义和固定 Python 入口。
