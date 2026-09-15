# 执行计划：开发计划二：按活动ID返回跑步全部records

## 对应目标

- 功能编号：ADHOC-0025
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
| T1 | S1 | [plan] | 落实目录、规则/本地检查对齐、JSON细则、容量与宿主边界；不超出本文目标/错误边界 | 前置依赖 | 保持已确认接口，按新版AGENTS审核实施拆解 | 未实施、未验证 |
| T2 | S1 | [plan] | 合成测试固定全量与拒绝预期；不超出本文目标/错误边界 | T1 | 测试先行，不读取正式数据 | 未实施、未验证 |
| T3 | S1 | [plan] | 实现唯一按ID只读工具；不超出本文目标/错误边界 | T2 | 仅一个工具、仅activity_id参数、全量返回 | 未实施、未验证 |
| T4 | S1 | [plan] | 全面检查与全新独立验证；不超出本文目标/错误边界 | T3 | 离线能力交付，实际API另授权 | 未实施、未验证 |

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

## 当前唯一能力

工具名确定为get_running_records，Python脚本query_fit.py放在待批准的TOOLS_DIR中。外部参数**只有activity_id**；返回该受授权跑步活动的全部采样记录。

接口不接收时间范围、分段编号、指标列表、limit或cursor，不提供分页或第二种查询，不以窗口/摘要替代全部records，不回读FIT补齐未入库的点。四列、工具名及核心返回方式已确认；只剩JSON技术细则、错误外壳和实施边界需要落实。

数据中sport=running才允许调用，子类不作白名单。非跑步默认得到第1/2/3类但不开放此工具；无跑步活动的AI请求不注册此工具，混合上下文有跑步时可注册一个工具，但执行端仍逐ID验证运动与本次授权集合。不能仅靠Prompt约束。

先前铁三排除仍保留，不开放其中跑步子阶段。未知运动类型不自动取得跑步权限，不按标题/速度/GPS猜测。

新增的[活动报告](ADHOC-0027-activity-ai-report.md)与[周报告](ADHOC-0028-weekly-ai-report.md)属于独立存储任务；本工具不因它们加入数据库而开放报告读取/写入或第二种能力，返回仍只有受授权活动的全部records。

## 已确认要求与实施边界

- “按活动ID取全部records”已取代此前20分钟时间范围细查及预计算窗口返回。旧A编号仅作批准来源；产品实施时同批对齐受影响的约束、实现、资源、适用本地测试和文档，不恢复rules.md、旧执行协议或冲突路径。
- 周累计20次/同请求缓存等未明确取消的边界仍保留；一种工具是能力种类，不是总调用次数。累计预算由可信宿主管理，不能每次Python进程重启就重置。
- 不新增任意SQL/路径/命令能力，不恢复data_revision/quality_json等已否决字段。schema_version只标识格式，跨调用内容稳定性另需宿主政策。

| 标准 | 已确认验收目标 | 来源 |
| --- | --- | --- |
| AC-01 | tools中只有一个本轮新增查询能力，唯一业务参数activity_id，返回该活动全部records。 | 用户本轮明确目标 |
| AC-02 | 关联activities检查running及本次作用域，所有跑步子类可用，非跑步/未知/铁三不放行。 | 用户分类/权限与既有范围 |
| AC-03 | 保留实际记录顺序/数量及获批字段，不截断、降采样、合并重复时间点或补点；JSON内容/单位/缺失真实。 | 用户全量目标与数据边界 |
| AC-04 | 正常/空结果/错误固定格式，JSON列解码为对象，不提供分段/时间/指标/分页的旧接口。 | 用户唯一能力与固定返回目标 |
| AC-05 | 只读、参数化、受控DB路径；超技术容量整体明确失败，不把部分结果装成全量；无库不造库。 | A-004/A-022及全量语义 |

| 门禁 | 计划检查 | 来源 |
| --- | --- | --- |
| GATE-01 | 合成SQLite与正常/缺失/重复时间/长活动用例先行，再实现；完整适用pytest/Ruff/mypy/compile/Schema。 | AGENTS、A-009 |
| GATE-02 | 唯一ID参数、全量保真、非跑步拒绝/跨活动隔离、坏数据/过大数据明确失败、只读/sidecar/注入/隐私检查。 | 用户要求及工程门禁 |
| GATE-03 | 全新只读Validator依已确认验收要求和当前快照验收，检查受影响旧接口/规则已退出，不复用历史PASS。 | 当前AGENTS及已确认的新方案同步边界 |

## 已确认接口与返回方式

合成请求示例：

```json
{
  "activity_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
}
```

成功外壳示意如下，日期/值均为合成示意，不是用户活动。record_index、timestamp_utc、metrics_json及顶层活动ID方式已确认；metrics_json内部指标定义和错误码等技术细则在实施Schema中固定。

```json
{
  "schema_version": "fit-records/1",
  "ok": true,
  "activity_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "data": {
    "records": [
      {
        "record_index": 0,
        "timestamp_utc": "2030-01-01T00:00:00Z",
        "metrics_json": {
          "standard": {"heart_rate_bpm": 120, "distance_m": 0.0},
          "developer": {}
        }
      },
      {
        "record_index": 1,
        "timestamp_utc": "2030-01-01T00:00:01Z",
        "metrics_json": {
          "standard": {"heart_rate_bpm": 121, "distance_m": 2.5},
          "developer": {}
        }
      }
    ]
  },
  "error": null
}
```

活动ID只在顶层传一次，不在每个record重复同一64位字符串；集合归属不变，记录本身不裁减。metrics_json从SQLite TEXT解码成对象，不让AI处理双重编码字符串。原索引/原顺序保留，不因缺项重排或重编号。

为解释Developer值，单位/字段身份必须可用；是每条自描述还是结果附共用字段字典，待与计划一字段规范共同确认，不悄悄传完整设备私有身份或FIT原字节。不额外增加第二种查询来补解释。

错误保持相同顶层键：ok=false、data=null、error={code,message,details}，无法确认的activity_id为null。候选错误：INVALID_ARGUMENT、ACTIVITY_NOT_FOUND、SPORT_NOT_ALLOWED、SPORT_UNKNOWN、SCHEMA_UNSUPPORTED、DATA_INVALID、RESOURCE_LIMIT、DATABASE_UNAVAILABLE。没有分页/时间边界/游标错误协议。

存在且合法但没有可用record的活动是否返回空数组，需与完整解析/合法缺失定义一致；无记录与活动不存在不能混同。损坏或中途失败不得返回已读前半段作为成功。

## 查询实现建议与完整返回语义

- 可信宿主定位实例DB，AI无db_path/sql/file_path参数。mode=ro、query_only、固定参数化SQL及适用authorizer等共同约束，不加载扩展/ATTACH/写语句；不存在库时明确失败，不自动创建。
- 同一次只读事务中读取活动身份/sport/schema并取该activity_id的全部record，按record_index排序；权限和资源预检可在内部做COUNT/长度估算，不对AI开放另一查询能力。
- 不使用LIMIT裁掉记录，不用分页或摘要补救来改变返回目标。若完整结果超过已冻结的字节/内存/时间/模型上下文预算，返回RESOURCE_LIMIT、data=null，不少给数据却称“全部”。无损紧凑格式可另讨论，不能自行切换协议。
- 取消“单次20分钟”不等于无限资源；也不允许读到其他活动或绕过周累计预算。当前预算数值/模型容量未确定，不承诺任意长活动必能送入任意模型。
- mode=ro不自动保证无SHM/WAL影响。首版journal/并发策略在实现前明确并测试，不对活库滥用immutable绕锁；只读声明限定实际检查范围。
- 记录有时间重复/空洞也完整保留；未知类型或坏JSON不能变成假数据。活动ID不是访问授权，宿主注入当前可访问活动集合，非跑步即使表里有records也拒绝。
- 数据来源/字段字典与原record绑定，避免把标准值和Developer值覆盖或平均；不把FIT文本当运行指令。
- 没有data_revision，不宣称跨调用内容版本一致；原初始摘要与后续records来自同一稳定数据视图的策略、重解析时机需冻结。这里不自动创建快照库或新增持久元数据。
- 实际API宿主接线、业务调用和Provider授权不包含在本轮规划。仅文档或离线脚本完成不等于已安全开放给业务AI。

## 功能与检查映射


候选测试继续放source/tests/code下：unit/test_running_query_parameters.py、contract/test_running_query_protocol.py、integration/test_running_query_sqlite.py、fixtures/running_query/。覆盖仅activity_id、超20分钟但在容量内仍完整返回（规则同步后）、每条记录/顺序一致、重复时间保留、无库/未知ID、非跑步/越权、空值、坏JSON、整批超限无部分成功、额外范围/指标/分页参数拒绝。全部合成。

技术栈沿用Python3.12/pytest/Ruff/mypy；用户已删除source及rules.md，原配置/测试不再是现存入口，旧CI已按用户授权退役。新实现时同批落实适用本地lint/type/compile/Schema及测试，不新增或主动运行远端CI；迁移必要安全场景，不恢复旧产品，不把文件缺失当成跳过门禁的理由。报告表加入后覆盖只读/不泄露报告的隔离回归。

## 历史来源与证据

- [不可变原件快照](../evidence/ADHOC-0029/history.zip)，条目`docs/exec-plans/active/ADHOC-0025-fit-running-query-tool.md`，原SHA-256：`4eb12742c6a1badf46ace22b6ee035c6c7c5abc50237cbfa603b88ee48147b3a`。
- [来源清单](../evidence/ADHOC-0029/history-manifest.json)、[迁移/编号映射](../evidence/ADHOC-0029/migration-manifest.json)、[原问题与失败计数索引](../evidence/ADHOC-0029/failure-index.json)。原记录中的绝对路径和失效外部证据只说明当时事实，不据此复建旧路径。
- 历史快照仅用于保真审查，不作为现行规范、产品导入、Schema、AI输入或CI运行依赖。当前实际迁移验收见[ADHOC-0029](../completed/ADHOC-0029-agentsmd-upgrade.md)。
