# FIT 详情纠错实施基线

- 状态：F0 共享契约已冻结，等待独立验收
- 起点：`b50274c6a3df55a2ceb82a7f0f6efe17842c4cdd`
- 集成分支：`codex/fit-detail-corrections`
- 工作方式：共享基础串行，隔离单元并行，按波次集成，独立终验

## 1. 目标与非范围

本轮只纠正四个已复现问题：上传区拖放、力量训练语义、攀岩实例等级表达和时间构成圆环。保持现有 v3.4 页面结构、响应式断点、视觉 token 和外部设计不变。

本轮不增加 Garmin Connect、TCX/GPX 后端导入、外部同步、后台队列或新的产品界面；不修改 `AGENTS.md`；不在 PR 合并前重解析真实数据库，也不改真实账号、默认 Compose 服务或私有文件卷。

## 2. 权威输入与隐私边界

用户截图的 SHA-256 为 `32db25a4842a2212f466e9400b32f73fc9c0342f7f10ee6ff15058989394f97e`。三份外部 ZIP 只用于本机只读研究和验收，不进入 Git、测试快照、日志、PR 或文档中的本机路径。禁止提交原始 FIT、GPS、心率、设备序列号、用户标题或其他健康数据。

| ZIP | 委托中的 SHA-256 | 本机核验 | 处理结论 |
| --- | --- | --- | --- |
| `578824608.zip` | `4fcacad7b9a12c32fe2dc708337b39029950c34fb8ee422200f2076b7a150654` | 一致；`training / strength_training` | 可用于只读力量验收 |
| `616634193.zip` | `bc13e87a6a40213bbbee7597ac9f43055505737034a1efa889e5cf768cfb4444` | 一致；`rock_climbing / indoor_climbing` | 可用于只读难度攀岩验收 |
| `616627608.zip` | `fc3886198b0706a3a1d783413d32a5e4ae1e8ef7753a1cc54f5c95727174ad` | 本机为 `fc3886198b0706a3a1d783413d32a5e4ae1e8ef7753a1cc54f5c95727174ad67`；`rock_climbing / bouldering` | 委托值仅 62 位；按本机 64 位值固定本次探索，但不冒充“与预期一致” |

仓库只新增合成、去身份的消息字典 `backend/tests/fixtures/fit_semantics_messages.json`。其中数字字段 69–73 仅用于锁住“未知字段可重放且不被猜测”的边界；只有取得官方格式资料或可复现解码证据后，才允许把它们转成等级语义。

## 3. 术语与实例来源

- `exercise_title`：力量训练动作标题字典；其 `message_index` 只是标题记录索引，不能当成 workout step 键。
- `set`：力量训练唯一的训练组实例来源。`active` 是有效训练组，`rest` 是休息段。
- `wkt_step_index`：`set` 关联 `workout_step.message_index` 的键；合法值 `0` 不得被当成缺失。`workout_step` 的 exercise category/name 身份再关联到 `exercise_title` 的同一身份，最终取得 `wkt_step_name`。
- `split`：攀岩唯一的攀爬/休息实例来源。
- `split_summary`：摘要，不是实例，不参与数量、动作聚合或时间构成累加。
- `semantic`：TrainLab 对原生 FIT 消息做出的、有证据的稳定语义投影。
- `extraData`：保留原始扩展字段用于审计和重放；未知数字键不能直接出现在业务 UI。

## 4. 规范化段契约

后端详情 API 在每个 segment 上保留现有字段和 `extraData`，并新增可选的 `semantic` 对象。冻结的版本 1 结构为：

```json
{
  "schemaVersion": 1,
  "sourceMessage": "set | split | split_summary",
  "exercise": {
    "stepIndex": 0,
    "name": "合成动作甲"
  },
  "climb": {
    "gradeStatus": "available | unavailable",
    "gradeReason": "unknown_profile_field",
    "gradeSystem": "v_scale | yds",
    "grade": "V1 | 5.10a",
    "outcome": "complete | attempt | unknown"
  }
}
```

`exercise` 只在动作关联可证明时存在。每个 `climb_active` 都提供 `climb.gradeStatus`；只有 `available` 才能同时提供 `gradeSystem`、`grade` 和经证明的 `outcome`。当前样本固定为 `unavailable / unknown_profile_field`，其余字段缺失。缺失不是空字符串，也不能用数字键、枚举序号或文件名补造。`extraData.sourceMessage` 在本轮继续保留以兼容既有前端，但新业务读取优先使用 `semantic.sourceMessage`。

### 4.1 力量文本和关联规则

1. 关联链固定为 `set.wkt_step_index → workout_step.message_index → (exercise_category, exercise_name) → exercise_title.wkt_step_name`，不使用 `set.message_index` 直接关联标题。真实样本有 10 个 title、32 个 workout_step 和 59 个 set；title 的 `message_index` 不能替代 workout step identity。
2. 标题优先使用 `wkt_step_name`；只有 `exercise_name` 本身是清晰的人类文本时才作为后备。数字、枚举数组、任意对象不得被字符串化为动作名。
3. 文本清洗只接受字符串、可安全解码的字节串，或可确定为字符序列的值；执行 Unicode NFC、空白归一、控制字符移除和 255 字符上限。清洗失败返回 `null`。
4. 重量大于 1000 的现有克到千克换算保持兼容。`null` 表示缺失；`0 kg` 与缺失不同；自重语义只有 FIT 明确给出时才能标注。
5. 训练动作数和动作表只聚合 `sourceMessage=set` 且非休息的实例。无 exercise identity 的休息段使用稳定“休息”标签，不从脏 category 值造名称；休息保留在时序分段与时间构成中，但不成为动作行。并行 `split` 和 `split_summary` 不重复计算。

### 4.2 攀岩等级证据门

等级映射必须同时满足：字段身份有可信资料或稳定 profile 证据、枚举/数值换算可复现、并能在外部样本的每个 `climb_active` 上交叉验证。单看 `{69:8,70:1,71:3}` 或 `{69:0,70:10,71:3,72:0,73:1}` 不足以建立 V-scale/YDS 映射。

只读证据审计确认：两份攀岩 FIT 的 header profile 为 21.201；字段 69–73 是原生 split 字段而非 developer fields，基础类型分别为 enum、uint32、enum、uint16、enum。但是 Garmin Python SDK 21.208.0 和 Garmin 官方最新 Tools `Profile.xlsx` 均未定义这些字段。Garmin 的 [FIT Protocol](https://developer.garmin.com/fit/protocol/) 只证明未知 product-profile 字段应被兼容保留；[官方 SDK Tools](https://github.com/garmin/fit-sdk-tools) 将 `Profile.xlsx` 定义为消息和类型参考，但未给出 69–73 的名字或枚举。因此当前证据门明确未通过。

U2 仍须修正实例来源、保留未知字段，并为每个 active split 提供 `semantic.climb.gradeStatus=unavailable` 与 `gradeReason=unknown_profile_field`。U4 显示“文件包含尚未获得可靠映射的等级字段”，不得显示数字键或猜测等级。本状态作为明确未解决项进入 PR，不能伪造完成。

解除阻塞的最小证据是两条活动按路线顺序导出的去隐私 Garmin Connect typed-splits（等级系统、等级标签、完成/尝试、跌落次数），或同一设备对已知 V1/V2/V3、5.10a/相邻等级和结果的受控录制。样本内映射仍不能外推到未观测的完整等级枚举。

## 5. 完整导入的原子安全重解析

现有 `replay_import()` 只用于 `pending`、过期 `processing` 或 `failed`，且 `_replace_activity()` 会删除再创建 Activity；它不能用于真实 complete/partial 数据纠错。

U2 提供仅本机运维 CLI 可调用的管理入口：

```text
trainlab reparse-fit --username <username> --import-id <uuid> [--import-id <uuid> ...] [--apply]
```

- 默认是无写入预检；只有显式 `--apply` 才修改投影。
- 不增加普通用户 HTTP 重解析端点，不允许按不受约束的文件路径或其他用户 ID 操作。
- 用户名归一化后必须精确找到一个用户；所有 import 必须属于该用户、状态为 `complete` 或 `partial`、不处于删除/处理状态，并且各自原文件可由现有私有存储边界读取。读取时重新计算 SHA-256，必须与 import 记录一致。
- 先完成整批原文件读取、SHA 校验和解析，解析阶段零数据库写入。随后按 UUID 排序锁定 `ActivityImport` 与对应 `Activity` 行，避免死锁，并重新验证 user/status/storage key/SHA 与预检快照一致；出现并发变化立即失败。
- 投影替换在一个数据库事务内完成。全部成功才一次提交，任一读取、解析、并发校验或持久化失败则整体回滚。
- Activity 原行就地更新，保留 `Activity.id`、`user_id`、`source_import_id`、`created_at`；保留 `ActivityImport.id`、`user_id`、`storage_key`、`sha256`、`original_filename`、`title_override` 和原文件。子投影可在同一事务内删除重建。
- 成功后更新 parser 版本、完成状态、warning、attempt 和 replay metadata；`processing_token` 在提交时必须为 `null`。失败后原状态、原投影、标题覆盖和 token 原样保留。
- 与删除、重试和再次重解析通过同一 import 行锁串行化；旧解析结果不能在删除或新重解析之后复活数据。
- CLI 只输出 import/activity ID、预检/成功状态和计数，不输出原文件路径、文件名、标题、健康字段或异常原文。

## 6. 依赖图、文件所有权与集成波次

```text
F0 共享契约
 ├─ U1 上传拖放 ─────────────┐
 ├─ U2 FIT 语义与安全重解析 ─┼─ 集成门 1（U2 → U1 → U3）
 └─ U3 时间构成 SVG 圆环 ────┘
                                  └─ U4 力量/攀岩前端结构
                                       └─ I0 全量门禁与终验 → ready PR
```

- U1 只修改 `FileUpload.tsx`、`FileUpload.css`、`FileUpload.test.tsx` 和专属拖放 e2e。
- U2 只修改后端 importer、活动导入/运维服务、必要 CLI、schema/OpenAPI 与后端测试。
- U3 只修改 ActivityDetail 的 composition 组件、专属样式和测试，不修改 `activityProfiles` 语义。
- U4 从已集成 U2/U3 的提交分叉，修改 `activityProfiles.ts`/测试及确有必要的 ActivityDetail 表达/测试。
- 共享计划、项目状态、backlog、runbook、聚合 CI 和冲突只由集成负责人修改。

任何单元需要改变上述 API 字段、实例来源或文件所有权时必须停止，先形成新的 F0 快照；不能在单元内私下猜契约。

## 7. 验收矩阵

| 问题 | 必须证据 | 阻断条件 |
| --- | --- | --- |
| 上传拖放 | 单/多文件、混合合法非法、重复、超 50 MB、坏扩展、FIT 后端、TCX/GPX 预览、键盘/手选、Playwright DataTransfer | 浏览器打开文件、第二套 ingest、拖态不恢复或手选回归 |
| 力量语义 | 合成契约和外部只读样本均证明 title 关联；真实样本 10 动作、30 active、29 rest、59 set；不重复 split；时间 1393.485/2171.271 秒 | 数字/数组/脏字节动作名、休息成为动作行、split 重复累计 |
| 攀岩语义 | 只用 split；boulder 21+21、1323.975/1273.663 秒；lead 5+5、974.835/740.835 秒；当前每个 active 实例明确 `gradeStatus=unavailable / unknown_profile_field` | 计入 split_summary、rest 造等级、显示数字键或猜测等级 |
| 时间构成 | SVG/等价稳定几何；百分比与弧长同源；0/100、39/61、无数据、小尺寸、四档视口与可访问名称 | 弧长、图例和百分比不一致或改变整体布局/token |
| 安全重解析 | 身份、标题覆盖、所有权、原文件与 import 不变；多条单事务；失败整体回滚；并发 fencing | Activity UUID 改变、跨用户、普通 HTTP 可调用、失败留下半投影 |
| 隐私 | Git、日志、截图、OpenAPI 和 PR 中无外部 FIT/绝对路径/健康数据 | 任何真实私有数据进入提交或日志 |

## 8. 最终门禁与真实数据迁移边界

最终至少运行后端 format/lint/mypy/pytest/coverage、OpenAPI 与隔离 Compose；前端 typecheck/lint/unit、专属 e2e、完整 e2e、视觉回归和 build。外部三份 FIT 仅在本机隔离环境只读导入验收，不复制进仓库。

PR 合并前只生成迁移方案，不执行真实重解析。合并后必须先停止写入并取得 PostgreSQL 与私有文件卷同一停写点的双卷备份；校验 manifest/SHA 后，在新镜像上对三个已知 import 先运行无写入预检，再用一个 `--apply` 命令原子重解析；随后重建/重启、检查 readiness，并在浏览器复核身份、用户标题、力量 10/30/29、攀岩 5/21、等级证据状态、时间构成与下载 SHA。任一步失败立即保持停写并从双卷备份恢复，不用 Alembic downgrade 回滚用户数据。
