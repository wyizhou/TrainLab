# 第一层：数据基础层详细开发需求清单

状态：13 个主单元及 3 个返修单元均已完成并记录离线验收证据；生产切换不属于本层

对应权威契约：[01-data-foundation.md](01-data-foundation.md) v2.4
权威 SHA-256：9bf0a91e61bda47c9dba971c731ca6ec79e064b7f0ea4eb8124a5a216d67e396
更新日期：2026-07-23

## 1. 范围、权威快照与勾选规则

本文记录第一层 v2.4 的实现验收；实现只改第一层必要依赖、owner-only 配置与 Harness Schema，且仅创建隔离临时 foundation 与 projection-only 合成样本；不改 legacy、生产配置、生产数据库、source/ 或五份大契约，不同步或分析真实数据、不发送邮件。

只有完成定义、验证方法和证据均满足的单元才可标为 [x]，并在证据处记录代码/迁移标识、测试命令、结果、环境和日期。

| 权威输入 | 版本 / SHA-256 | 本层使用方式 |
|---|---|---|
| 第一层 | v2.4 / 9bf0…e396 | 唯一数据与 init 语义来源 |
| 第二层 | v1 / afdffa…db14 | Garmin 表、视图与运行表消费者 |
| 第三层 | v2 / 4a9b3f…94eb8 | 分析、计划、主动投递消费者 |
| 第四层 | v2 / 471752…be94 | Gmail、会话、回复、回复投递消费者 |
| 第五层 | v1 / 5b1d5a…e804 | bootstrap、运行表、监控、告警消费者 |

固定边界：

- 第一层只创建和显式维护环境；没有 daemon、scheduler、网络、凭据读取或邮件发送。
- 只改第一层必要依赖、owner-only 配置与 Harness Schema；不改 source/、现有生产 data.db、legacy 命令、生产配置或五份大契约。
- 不把健康、GPS、邮件、token、授权 URL、完整 prompt、原始模型响应或隐藏推理写入测试、日志、receipt 或文档。
- 第二至第五层各自拥有运行时表写入；第一层 init 只创建 schema，不接管业务写入。

正常生命周期：

~~~text
未初始化 / 可安全恢复初始化中
  → FoundationTool.execute(init)
  → 目录 + schema + 视图 + ready 原子完成
  → ready，第一层退出
  → 第五层 bootstrap 仅得到 already_initialized（严格 no-op）
~~~

## 2. 固定接口与开发约束

唯一 application service：

~~~python
FoundationTool.execute(request: FoundationRequest) -> FoundationReceipt
~~~

目标 CLI：

~~~text
trainlab foundation init
trainlab foundation status
trainlab foundation verify
trainlab foundation migrate --target-version VERSION
~~~

FoundationRequest 固定含 mode、invocation_id、target_schema_version（仅 migrate）与 requested_at_utc。FoundationReceipt 固定含 receipt schema 版本、invocation_id、mode、状态、foundation schema 版本、ready、目录/对象计数、migration 范围、next_action、脱敏 warnings/errors 与起止时间。

规则：

- mode 仅允许 init、status、verify、migrate；CLI 和 Python API 必须调用同一个 service。
- init 是唯一正常初始化；status/verify 只读；migrate 是唯一显式 schema 维护入口。
- data root、database、raw、state、ready marker 和 lock 路径仅来自 owner-only 配置，并必须解析在允许根内。
- ready 环境的 init 以及第五层 bootstrap 都不得扫描、补建、迁移、修复或改写。
- stdout 仅输出脱敏 FoundationReceipt JSON；退出码遵循大契约。

## 3. 依赖图、波次和集成门

~~~text
FND-01 接口/配置/路径
  → FND-02 状态机/锁/迁移/no-op
    → FND-03 通用主体/raw/revision/coverage
      ├→ FND-04 健康、生理、睡眠、身体测量
      ├→ FND-05 设备、活动、来源、远端状态
      │   → FND-06 FIT、分段、专项
      ├→ FND-07 第四层邮件、会话、事实、回复投递
      ├→ FND-08 第三层分析、计划、主动投递
      └→ FND-09 第五层 workflow、incident、运维告警
{FND-04,FND-06,FND-07,FND-08,FND-09}
  → FND-10 质量、对账、稳定视图、所有权
    → FND-11 四个 mode、bootstrap、维护恢复
      → FND-12 合成样本、迁移兼容、终验
        → FND-13 第四层邮件状态机兼容迁移
~~~

| 波次 | 单元 | 前提 | 集成门 |
|---|---|---|---|
| 0 | FND-01 | 权威快照已验证 | API/路径契约冻结 |
| 1 | FND-02 | FND-01 | 空临时根 init，重复 init 严格 no-op |
| 2 | FND-03 | FND-02 | 通用外键、revision、coverage 可验证 |
| 3 | FND-04、05、07、08、09 | FND-03 | 各自表族和唯一写入者通过 |
| 4 | FND-06 | FND-05 | 活动/FIT/专项引用完整 |
| 5 | FND-10 | 波次 3–4 | 全部稳定视图与三类 delivery 分离 |
| 6 | FND-11、12 | FND-10 | 维护、合成端到端、回退通过 |
| 7 | FND-13 | FND-02、FND-07、FND-11、FND-12 | 显式 v1→v2 邮件状态 schema 迁移通过 |

同波次只允许独立表族并行；migration registry、foundation_state、公共 API、稳定视图和最终集成串行。共享基础变更时停止受影响工作，更新快照后再验收。

## 4. 需求单元总表

| ID | 状态 | 名称 | 依赖 |
|---|---|---|---|
| FND-01 | [x] | Foundation API、CLI、配置与受限路径 | 无 |
| FND-02 | [x] | 初始化状态机、锁、迁移与 strict no-op | FND-01 |
| FND-03 | [x] | 主体、原始对象、revision、coverage、字段目录 | FND-02 |
| FND-04 | [x] | 健康、生理、睡眠、身体测量 schema | FND-03 |
| FND-05 | [x] | 设备、活动概要、来源、远端状态 schema | FND-03 |
| FND-06 | [x] | FIT 样本、分段、定义、未知 message、专项 schema | FND-05 |
| FND-07 | [x] | 第四层邮件、会话、事实、回复/投递 schema | FND-03 |
| FND-08 | [x] | 第三层分析、计划、主动投递 schema | FND-03 |
| FND-09 | [x] | 第五层编排、健康、incident、运维告警 schema | FND-03 |
| FND-10 | [x] | 质量、对账、稳定视图、读写所有权门禁 | FND-04 至 FND-09 |
| FND-11 | [x] | init/status/verify/migrate 与 bootstrap 合约 | FND-02、FND-10 |
| FND-12 | [x] | 合成样本、迁移兼容、备份/重建与最终验收 | FND-01 至 FND-11 |
| FND-13 | [x] | 第四层邮件 processing_state 冻结状态机兼容迁移 | FND-02、FND-07、FND-11、FND-12 |

## 5. 单元详细契约

### [x] FND-01：Foundation API、CLI、配置与受限路径

**目的**：建立唯一 FoundationTool、四个一次性入口、Request/Receipt Schema、退出码和 owner-only 路径校验，隔离 legacy 自动建库。

**依赖与起始快照**：无；使用第 1 节全部权威快照。

**负责范围**：类型、JSON Schema、CLI 参数解析、同一 application service、data_root/database/raw/state/ready/lock 解析与路径包含检查。

**禁止触碰范围**：不建业务表、不执行 migration、不改 legacy、非本层配置/依赖或第五层。

**预期产物**：接口定义、CLI 路由、路径校验器、receipt 序列化器、接口测试。

**验证方法与证据**：测试 mode/null 规则、退出码、危险路径/路径逃逸、stdout 脱敏、CLI/API 共用 service、未触发 legacy migrate；记录命令、结果、变更标识、日期。

**完成定义**：无效请求和越界路径被拒绝；四个 mode 只能形成有效请求；没有数据库、网络、线程或子进程副作用。

**集成顺序与失败回退**：最先合并；接口或 Schema 失败则回退本单元，不允许下游基于临时类型开发。

**证据**：2026-07-24；`src/trainlab/foundation.py`、`src/trainlab/cli.py`、`harness/schemas/foundation_{request,receipt}.schema.json`；新增 `tests/test_foundation_fnd01_contract.py`，连同 `tests/test_foundation_interface_contract.py` 共 14 项，验证严格 Request 条件/UTC、bool 与 integer、未知 JSON key、Unicode/超长 invocation、CLI/API 等价 receipt、owner-only 配置、危险根/路径逃逸/中间 symlink/配置 symlink/权限异常、无 I/O 副作用和无 worker。`.venv/bin/pytest -q tests/test_foundation*.py`（536 项）、Schema 自校验、`compileall`、`git diff --check` 与五份冻结契约哈希均通过。

### [x] FND-02：初始化状态机、锁、迁移与 strict no-op

**目的**：实现一次性 foundation 生命周期、并发互斥、可证明恢复、ready 原子发布和显式 migration。

**依赖与起始快照**：FND-01；空临时 data root。

**负责范围**：foundation_state、schema_migrations、migration registry/哈希、foundation lock、foreign_keys、WAL、busy timeout、短事务、ready marker 与 initializing 恢复。

**禁止触碰范围**：不创建领域表；不自动升级 ready 环境；不清库、不重置、不实现第五层 lease。

**预期产物**：状态机、migration 执行器、锁、ready 标记和恢复测试。

**验证方法与证据**：新根 init、重复 init 数据库/目录哈希、并发 lock_busy、initializing 中断、高版本、不安全权限、损坏 SQLite、ready 原子性测试。

**完成定义**：全部 migration 和 verify 成功后才 ready；ready init 返回 already_initialized 且零写入；不确定现场 failed/incompatible，不静默修复。

**集成顺序与失败回退**：FND-01 后；失败仅回滚未提交事务或影子对象，保留原库、raw 和 state。

**证据**：2026-07-24；`src/trainlab/foundation.py`；正常 init 与 phase-1 recovery 共用 `_apply_phase2_schema` reviewed builder 与精确 migration receipt verifier。新增 `tests/test_foundation_fnd02_lifecycle.py`，连同 recovery/concurrency/lock/marker 安全测试共 49 项，覆盖空 owner-only 根、两进程单写与立即 `lock_busy`、锁内重检、精确 phase-1 metadata checkpoint 继续创建、metadata 两表规范 SQL/列/default/PK/CHECK/NOT NULL 指纹、DDL 事务中断回滚、phase-2/marker 中断、伪造/额外 phase-1 table/index/view/trigger/metadata 现场 fail-closed、ready 全树 bytes/mtime 严格 no-op、foreign_keys/WAL/busy_timeout、schema/migration/integrity 成功后才 marker 原子发布、权限/版本/损坏库/未知现场 fail-closed 及无 lock/snapshot 残留。`.venv/bin/pytest -q tests/test_foundation*.py`（554 项）、Schema 自校验、`compileall`、`git diff --check` 和五份冻结契约哈希均通过。

### [x] FND-FS-A：受控目录与文件原语返修

**目的**：将 Foundation 目录创建、目录 fsync 与只读文件读取收敛到 owner-only、`O_NOFOLLOW` 的受控基础原语。

**范围**：仅 `_ensure_dir_chain`、`_fsync_directory`、`_secure_read_file`；逐级 `openat/mkdirat`，目录和名称 inode 复验，缺失/过大/替换文件安全失败。

**禁止范围**：不改变 lock、marker、SQLite 代理协议，不修改任何冻结大契约或其他层。

**证据**：2026-07-24；`src/trainlab/foundation.py`、`tests/test_foundation_filesystem_security.py`；Foundation 聚焦 pytest（50 passed）和 `git diff --check` 通过。全仓 `compileall` 当前被其他层既有的 `src/trainlab/analysis/run_state.py:336` 语法错误阻断，未将其冒充为本子单元通过。

### [x] FND-FS-C：允许根祖先兼容返修

**目的**：允许项目根及 data root 之前既有、非 group/other writable 的用户目录（如 `0755`），同时维持 data root 与全部内部目录严格 `0700`。

**证据**：2026-07-24；真实 YAML/Schema `FoundationConfig.load(project_root)` 路径测试验证 `project_root/state=0755` 可 init、Foundation data root 为 `0700`；writable ancestor 拒绝且不创建。主 FND 状态不变。

### [x] FND-LOCK：Foundation 锁 inode claim 返修

**范围**：锁 parent fd 内的 `openat/statat/renameat/unlinkat`、严格限长锁记录、stale/release claim 与 fsync；不修改 marker、SQLite 或运行层。

**证据**：2026-07-24；`src/trainlab/foundation.py`；Foundation 锁与并发聚焦测试通过，证据已并入 FND-02 验收。

**证据**：2026-07-23；`tests/test_foundation_recovery.py`、`tests/test_foundation_concurrency.py`、`tests/test_foundation_interface_contract.py` 覆盖阶段中断、可恢复 initializing、lock_busy、锁内重检、ready strict no-op 和显式 migrate；隔离 CLI 实测 `init → status → verify → init → migrate` 全部成功；本轮全量 236 passed。

### [x] FND-03：主体、原始对象、revision、coverage 与字段目录

**目的**：提供五层共用的 subject、身份、不可变 raw、source revision、资源覆盖和字段漂移基础。

**依赖与起始快照**：FND-02；基础 schema ready。

**负责范围**：data_subjects、subject_identities、raw_objects、source_revisions、resource_coverage、source_field_catalog 的 migration、索引、HMAC/路径/唯一性约束。

**禁止触碰范围**：不调用 Garmin/Gmail；不存 BLOB、凭据或明文身份；不归档真实文件；不实现运行层写逻辑。

**预期产物**：通用 migration、数据字典、raw/revision 仓储规格和合成约束测试。

**验证方法与证据**：active subject、HMAC identity、SHA-256 raw、相对路径、相同内容 no-op、内容变化 revision/current、全部 coverage 状态、未知字段目录测试。

**完成定义**：五层均能以统一 subject/revision 引用数据；无记录不等同零；raw 仅以文件路径/哈希表示。

**集成顺序与失败回退**：领域表共同基础；约束错误回滚本 migration，禁止下游使用临时外键。

**证据**：2026-07-23；`tests/test_foundation_domain_contracts.py`、`tests/test_foundation_final_contract.py`、`tests/test_foundation_sample.py` 和 `tests/test_foundation_garmin_runtime_schema.py` 覆盖 SHA/path、revision/current、coverage 八状态、字段目录、Garmin invocation/stage/cursor/gap/capability 约束、FK/integrity；本轮全量 236 passed。

### [x] FND-04：健康、生理、睡眠与身体测量 schema

**目的**：承载第二层全部独立 Garmin 健康资源与未来字段扩展。

**依赖与起始快照**：FND-03；UTC/Singapore、单位与 revision 规则已可用。

**负责范围**：daily_health、health_samples、physiology_records、physiology_metrics、sleep_sessions、sleep_stages、body_measurements；current、value origin、单位、时间窗、extras/source map 约束。

**禁止触碰范围**：不调用 Garmin、不决定来源优先级、不生成建议、不用健康 EAV 存高频活动流。

**预期产物**：健康域 migration、指标/单位约束、数据字典、合成投影测试。

**验证方法与证据**：日汇总、HR/HRV/压力/Body Battery/血氧/呼吸、睡眠/小睡、体重/血压、训练状态/准备度/预测、未映射指标、值类型/单位/时间测试。

**完成定义**：v2.4 健康资源均有表或 extras 承载；无效单位、时间、value 组合和 current 冲突被拒绝。

**集成顺序与失败回退**：可与 FND-05/07/08/09 并行；失败仅回滚本表族。

**证据**：2026-07-23；`tests/test_foundation_domain_contracts.py`、`tests/test_foundation_final_contract.py`、`tests/test_foundation_sample.py` 覆盖值类型/JSON、睡眠 source map、current 与人工兼容视图语义、Body Measurement 和合成生理资源；本轮全量 236 passed。

### [x] FND-05：设备、活动概要、来源与远端状态 schema

**目的**：建立所有运动类型共享的活动身份、多来源、设备和传感器归因基础。

**依赖与起始快照**：FND-03。

**负责范围**：devices、activity_devices、activity_metric_sources、activities、activity_source_revisions；provider activity 唯一性、source role、字段级来源时窗、active/suspected_missing/provider_deleted。

**禁止触碰范围**：不下载/解析 FIT，不扫描远端 inventory，不把整行 sample 绑定单一设备。

**预期产物**：活动基础 migration、role/状态约束、canonical source map 规格与测试。

**验证方法与证据**：多来源/多设备、summary/FIT/splits/sets/zones/weather/gear role、两次完整 inventory 后删除、重新出现恢复 active、未知来源测试。

**完成定义**：所有 FIT/JSON 专项表可稳定引用 activity/source revision；远端状态不删除本地原始证据。

**集成顺序与失败回退**：FND-06 的前置；失败仅回滚活动基础表族。

**证据**：2026-07-23；`tests/test_foundation_domain_contracts.py`、`tests/test_foundation_final_contract.py` 和合成样本覆盖 provider state、字段级设备来源、unknown attribution、source role 枚举及 active partial unique；本轮全量 236 passed。

### [x] FND-06：FIT 样本、分段、定义、未知 message 与专项 schema

**目的**：承载通用传感器、developer fields、未知 message、攀岩、力量和路线数据，并允许解析器重建。

**依赖与起始快照**：FND-05。

**负责范围**：activity_segments、activity_samples、fit_metric_definitions、activity_aux_messages、fit_unknown_message_catalog、climbing_routes、strength_sets、course_points，以及顺序、revision、extras 和外键约束。

**禁止触碰范围**：不实现 FIT 下载、ZIP、CRC 或 parser；不展开未知高频 message；不按运动类型复制原始表。

**预期产物**：FIT/专项 migration、字段定义承载、六类合成 FIT 映射和重建规格。

**验证方法与证据**：跑步 developer fields、抱石、室内攀岩、徒步、骑行、力量 active/rest；record/lap/split/set/workout step、未知 message、sample/时间、course point 和重复投影测试。

**完成定义**：每类活动都可存通用概要/segment/sample/extras；专项可投影，未知值仍可由 raw FIT/catalog 追溯。

**集成顺序与失败回退**：FND-05 后；失败不切换 canonical activity source，仅回滚本表族。

**证据**：2026-07-23；`tests/test_foundation_domain_contracts.py`、`tests/test_foundation_final_contract.py`、`tests/test_foundation_sample.py` 覆盖六类 projection、developer definition、unknown message、sample/segment/course 唯一性与 climbing/strength trigger；本轮全量 236 passed。

### [x] FND-07：第四层邮件、会话、事实、回复与回复投递 schema

**目的**：提供第四层独占写入的入站 Gmail、会话、用户事实、mail agent、回复 revision 和恢复投递存储。

**依赖与起始快照**：FND-03；第四层 v2 的 self-only、阶段和 receipt 规则仅作为消费者约束。

**负责范围**：mail_threads、mail_messages、mail_attachments、conversation_events、user_facts、mail_agent_runs、mail_agent_items、mail_response_artifacts、mail_response_inputs、mail_deliveries、mail_delivery_artifacts、mail_poll_cursors；包含 revision、阶段、幂等、supersession、输入血缘和 precise-reply 关联。

**禁止触碰范围**：不调用 Gmail MCP、不 poll/process/send；不写 analysis/training/analysis_delivery；不写 operational alert。

**预期产物**：邮件域 migration、item/delivery 状态约束、事实可信度/作用域约束、合成线程 fixture。

**验证方法与证据**：message/thread 身份、raw revision、重复消息/event、facts supersession、prior_model_output 不升级、item 阶段幂等、回复重生成、accepted 先保存后发送、unknown/sent 回执、精确 revision 关联测试。

**完成定义**：第四层能独立恢复发现、回复和投递；第三/五层写入此表族被访问边界和集成测试拒绝。

**集成顺序与失败回退**：可与 FND-04/05/08/09 并行；失败仅回滚邮件表族，绝不触及另两类 delivery 表。

**证据**：2026-07-23；`tests/test_foundation_domain_contracts.py`、`tests/test_foundation_final_contract.py`、`tests/test_foundation_sample.py` 覆盖方向/角色/作用域、run/item/cursor、response supersession、trust class、精确回复投递与恶意文本 untrusted；本轮全量 236 passed。

### [x] FND-08：第三层分析、训练计划与主动投递 schema

**目的**：提供第三层独占写入的 accepted 分析、计划 revision、输入血缘和日报/周报/计划修订自投递恢复存储。

**依赖与起始快照**：FND-03；第三层 v2 的 route、质量门禁和自投递边界。

**负责范围**：analysis_runs、analysis_artifacts、analysis_artifact_inputs、analysis_artifact_relations、training_plans、training_plan_items、analysis_deliveries、analysis_delivery_artifacts；包括 daily/weekly/plan revision/regeneration、current/supersession、paired relation、七日计划和精确 artifact delivery。

**禁止触碰范围**：不调用 Codex/Gmail、不生成内容、不发送；不创建 interactive/mail route；不写 mail 或 operational 表。

**预期产物**：分析/计划/主动投递 migration、关系/状态约束、delivery 状态规格和合成 fixture。

**验证方法与证据**：run/artifact kind 限制、accepted/current 唯一、input 有序哈希、prior_model_output、weekly paired relation、计划日期/项目、plan supersession、analysis delivery 幂等及精确 revision 关联测试。

**完成定义**：第三层可在发送前原子发布 artifact/plan 并独立恢复同一投递；第四层回复/inbound 事实不能进入该表族。

**集成顺序与失败回退**：可与 FND-07 并行；失败只回滚分析表族，旧 current artifact/plan 保持。

**证据**：2026-07-23；`tests/test_foundation_domain_contracts.py`、`tests/test_foundation_final_contract.py`、`tests/test_foundation_sample.py` 覆盖 route/artifact 枚举、weekly plan trigger、七日项目窗口、revision/supersession、prior_model_output 与精确 analysis delivery；本轮全量 236 passed。

### [x] FND-09：第五层编排、健康、incident 与独立运维告警 schema

**目的**：提供第五层唯一写入的调度投影、lease、workflow/step、健康检查、incident 和不含业务正文的运维告警投递存储。

**依赖与起始快照**：FND-03；第五层 v1 的 workflow、receipt、lease 和安全边界。

**负责范围**：scheduler_jobs、scheduler_leases、orchestrator_runs、orchestrator_steps、service_health_checks、operational_incidents、operational_alert_deliveries；workflow key、step 转换、receipt hash、incident 去重、retention 和 alert 幂等约束。

**禁止触碰范围**：不实现 Supervisor、schedule、systemd、子进程、健康检查、告警发送或重试；不改第二至第四层业务表；不复用 analysis_delivery 或 mail_delivery。

**预期产物**：第五层运行表 migration、状态/引用/去重约束、保留策略规格、合成 workflow fixture。

**验证方法与证据**：workflow key、允许 step 转换、lease owner/expiry、receipt hash 无正文、incident 去重/恢复、alert 元数据、三类 delivery 交叉引用禁止、运行表无业务 payload 测试。

**完成定义**：第五层能以引用 ID/receipt hash 编排审计而不代写业务状态；运维告警与第三层主动投递、第四层回复投递完全隔离。

**集成顺序与失败回退**：可与 FND-07/08 并行；失败仅回滚第五层运行表。

**证据**：2026-07-23；`tests/test_foundation_domain_contracts.py`、`tests/test_foundation_sample.py` 覆盖 scheduler/lease/workflow/step、deferred、incident/alert 和三类 delivery 的 schema 隔离；本轮全量 236 passed。

### [x] FND-10：质量、对账、稳定视图与读写所有权门禁

**目的**：把已建表族转化为五层稳定只读接口，并以质量、对账和访问边界阻止语义漂移。

**依赖与起始快照**：FND-04 至 FND-09。

**负责范围**：data_quality_issues、reconciliation_results；全部 v2.4 current/history/quality/orchestrator/incident 稳定视图；只读访问角色或仓储边界。

**禁止触碰范围**：不执行第二层 audit/repair、第三层门禁、第四层状态机或第五层健康检查；不在视图泄露 raw HTML、附件、payload、token 或隐藏推理。

**预期产物**：质量/对账 migration、版本化 view 定义、列字典、所有权与 consumer contract tests。

**验证方法与证据**：空库、current 切换、历史 revision、quality open/resolved、JSON/FIT 冲突、analysis/mail history prior_model_output、plan reason、三类 delivery 分离、第五层只读和隐私测试。

**完成定义**：下游仅依赖稳定视图、Request/Receipt 与各自运行表；每张可写表有唯一 owner，视图只读。

**集成顺序与失败回退**：所有表族后串行集成；视图/权限回归回滚视图版本，保留底层 revision。

**证据**：2026-07-23；`harness/schemas/foundation_schema_manifest.json` 及 `tests/test_foundation_manifest.py`、`tests/test_foundation_garmin_runtime_schema.py` 验证表/索引/enum/FK/view/trigger 与 Garmin 运行表 partial unique；`tests/test_foundation_domain_contracts.py`、`tests/test_foundation_final_contract.py`、`tests/test_foundation_sample.py` 查询全部 23 个稳定视图并验证 current/history/trust/reason/open；本轮全量 236 passed。

### [x] FND-11：init/status/verify/migrate 与第五层 bootstrap 合约

**目的**：在完整 schema/视图基础上验证四个 mode，并固定 Supervisor bootstrap 的严格 no-op。

**依赖与起始快照**：FND-02、FND-10；全量 schema 已在新临时根建立。

**负责范围**：init 空环境创建与 ready no-op；status 只读摘要；verify 只读完整性/兼容性；显式 migrate target/version/回退；第五层只消费 receipt 的 bootstrap contract test。

**禁止触碰范围**：不实现 Supervisor；不自动修复 ready；不让 status/verify/普通 bootstrap migrate；不触碰生产数据库。

**预期产物**：四 mode 行为、退出码映射、bootstrap contract test、维护 runbook 草案。

**验证方法与证据**：首次 init、重复 init 哈希 no-op、status/verify 零写入、显式 migrate 的顺序/失败影子回退、ready 后目录异常拒绝、模拟 bootstrap 仅接受 already_initialized。

**完成定义**：常规启动对 ready foundation 零文件/数据库写入；只有显式 migrate 可改变 schema，失败不替换唯一数据库。

**集成顺序与失败回退**：FND-10 后；维护失败保留 last known-good，operator 显式决定恢复。

**证据**：2026-07-24；`src/trainlab/foundation.py`、`src/trainlab/orchestration/foundation_adapter.py`、`tests/test_foundation_fnd11_contract.py`、`tests/foundation_v1_fixture.py`、`tests/test_orchestration_s5_01.py` 与 `docs/runbooks/foundation-maintenance.md`。41 项 FND-11 聚焦测试覆盖首次 init、ready init 全树 bytes/SHA-256/文件与目录 mtime 严格 no-op、status/verify 对 live WAL/SHM/DB 零写入、完整 state/receipt/manifest/integrity/FK/路径兼容门、ready 文件系统异常拒绝、六类退出码与 receipt identity、四 mode 无 thread/subprocess/daemon、v1 source 非规范 UTC 拒绝、显式 migration 在 transaction 前/中/提交后/marker 后四个发布边界的回滚或确定性恢复，以及仅 `already_initialized` 可通过第五层 bootstrap。`.venv/bin/pytest -q tests/test_foundation*.py tests/test_orchestration_s5_01.py tests/test_garmin_l2_01_04.py` 共 643 项通过（Foundation 618、第五层 bootstrap 15、Layer-2 共享 Foundation 回归 10）；`py_compile`、`git diff --check` 通过。FND-12 保持未验收。

### [x] FND-12：合成样本、迁移兼容、备份/重建与最终验收

**目的**：证明第一层可安全实现、验证、迁移和恢复，且测试不触及真实数据或生产路径。

**依赖与起始快照**：FND-01 至 FND-11。

**负责范围**：合成 sample database/fixture 设计；备份、影子重建、恢复、integrity、migration rollback、legacy 并存规格；六类 FIT、健康、邮件、分析、计划、三类 delivery、workflow/incident 端到端合成验收；真实环境切换前检查表。

**禁止触碰范围**：不执行真实迁移、切换、备份恢复、Garmin/Gmail/Codex 调用；不删除 legacy 数据、文件或 daemon。

**预期产物**：fixture 规范、sample generator、验收脚本设计、backup/restore runbook、legacy mapping/对账规格。

**验证方法与证据**：新临时根完整 init、表/索引/视图、外键/约束、三类 delivery owner、隐私扫描、shadow rebuild 行数/哈希/引用对账、失败恢复和 strict no-op。

**完成定义**：完整 schema 能在合成环境重复构建并验证；真实验收、回滚和跨层切换条件可执行且无未声明假设。

**集成顺序与失败回退**：最终单元；失败回退至最小表族/视图/维护单元，不通过删库或重跑 init 解决。

**证据**：2026-07-24；`src/trainlab/foundation_sample.py`、`src/trainlab/foundation.py`、`scripts/verify_foundation_acceptance.py`、`tests/test_foundation_fnd12_acceptance.py`、`docs/runbooks/foundation-synthetic-sample.md` 与 `docs/runbooks/foundation-final-acceptance.md`。确定性 projection-only sample 使全部 Foundation 表（另含 migration ledger）非空并查询 23 个稳定视图，覆盖六类 FIT shape、健康 current/history、邮件与回复 revision、分析/建议、计划/reason、三类 delivery、workflow/incident 及 lineage/current/history；验收 manifest 固定行数、规范内容 SHA-256、外键引用 SHA-256、view/raw hash，隐私扫描拒绝凭据、地址、授权 URL、raw HTML、完整 payload/model response 与隐藏推理。离线终验验证 repeat init/status/verify 全树 strict no-op、AES-256-GCM 错误密钥/篡改/既有目标拒绝、restore FK/integrity/逐表对账、原子 shadow rebuild、发布前失败清理、发布后确定状态、v1 migration transaction rollback 与 legacy/current 并存，且无网络、provider、model、thread 或 subprocess。FND-12 聚焦 11 项通过；`.venv/bin/pytest -q tests/test_foundation*.py` 629 项通过；分析/计划、邮件、第五层编排及 Layer-2 共享 Foundation 消费者回归 1003 项通过；`py_compile`、`git diff --check` 通过，冻结 `docs/layers/01-data-foundation.md` SHA-256 仍为 `9bf0a91e61bda47c9dba971c731ca6ec79e064b7f0ea4eb8124a5a216d67e396`。未执行任何真实迁移、备份恢复、切换、provider/model 调用或生产路径访问。

### [x] FND-13：第四层邮件 processing_state 冻结状态机兼容迁移

**目的**：落实 [第四层 v2 §11](04-mail-agent.md#11-消息处理状态机) 的首版邮件处理状态机，使全新初始化可持久化主链、等待/终态，并保持旧 `new`、`processed`、`error` 值可读可写；不让第四层自行改表。

**依赖与起始快照**：FND-02、FND-07、FND-11、FND-12；第一层 schema v1 的 `mail_messages.processing_state` 仅允许 `new`、`processed`、`ignored`、`error`，与第四层冻结状态集不兼容。

**负责范围**：将 Foundation schema 升至 v2；全新 init 使用完整状态约束和 `discovered` 默认值；仅通过显式 `foundation migrate --target-version 2` 对 ready v1 数据库事务性重建 `mail_messages` CHECK 约束，逐列原样复制既有行、重建稳定视图、记录 migration 2、发布新 marker，并支持 marker 发布中断后的显式幂等恢复。

**禁止触碰范围**：不修改第四层代码、CLI、状态迁移逻辑或大契约；不在 `init`、status、verify、第五层 bootstrap 中自动迁移；不删除业务行、重建 ready 项目、篡改旧 processing state，或由第四层运行时执行 DDL。

**预期产物**：v2 `mail_messages` DDL、静态 manifest enum、v1→v2 maintenance migration、migration receipt/marker 策略和第一层兼容测试。

**验证方法与证据**：新临时根接受第四层 §11 的全部主链/等待/终态并拒绝非法值；旧库含 `new` 状态时 init 返回 `incompatible/explicit_migrate` 且字节不变；显式 migrate 后行值、行数、FK/integrity、manifest、view 均通过；重复 migrate 与迁移后 init 均为 no-op；运行第四层 repository 相关测试、全量离线 pytest、compileall、diff-check 和五份冻结契约 hash。

**完成定义**：schema v2 是唯一当前 Foundation 版本；v1 只可经显式、审计的 migrate 升级，旧值不丢失；所有冻结合法状态均受 SQLite 接受、非法状态拒绝，且第四层仍是 `mail_messages` 唯一运行时写入者。

**集成顺序与失败回退**：最后串行维护单元；迁移事务、copy count、integrity/FK 任一失败即 rollback 并保留 v1 现场。DB 已提交而 marker 未发布时仅允许显式同目标 migrate 验证 manifest 后发布 marker；普通 init 保持拒绝，不自行修复。

**证据**：2026-07-23；`src/trainlab/foundation.py` 将 Foundation schema 从 v1 升至 v2，并固定已发布 v1 的 manifest SHA-256 `e406492dc044dcc17c5e08776614b9f73ec08580b6c56c14898d9085708e6e88`、migration 1 hash（同值）和完整 SQLite 对象 SHA-256 `781db677d022d7f7904aaea3569662c025d76c659da224ae5876486eeade6732`；`harness/schemas/foundation_schema_manifest.json` v2.0 固定第四层 §11 全部状态及旧值兼容；`tests/test_foundation_mail_processing_migration.py` 直接重建该已发布 v1 fixture，覆盖全新 init、全部合法状态、非法拒绝、v1 行逐列保留、init 拒绝自动升级、显式 v1→v2 migrate、重复 migrate no-op、伪造 marker/manifest/migration/DDL/额外或缺失对象在写入前拒绝、以及已完成 v2 才能 marker republish；第一层聚焦测试通过，第四层 repository `tests/test_mail_agent_m4_{01,02,03}.py` 51 passed；本轮全量离线 282 passed、compileall、diff-check 与冻结契约 hash 通过。

## 6. 大契约覆盖矩阵

| v2.4 条款 | 覆盖单元 | 覆盖内容 |
|---|---|---|
| §1–2 目标、非目标、生命周期 | FND-01、02、11 | 一次性、四 mode、无网络/daemon |
| §2.1 bootstrap 严格 no-op | FND-02、11 | ready 后 only already_initialized |
| §2.2 Request/Receipt、CLI、路径 | FND-01、11 | 同一 service、Schema、显式 migrate |
| §3 核心决策/所有权 | FND-03 至 FND-10 | raw/revision、单位/时区、唯一写入者 |
| §4–6 数据流、布局、通用类型 | FND-01、03 至 09 | data/raw/state、安全、UTC/Singapore |
| §7.1 通用/raw/revision/coverage | FND-03 | 主体、身份、raw、revision、catalog |
| §7.2–7.5 设备/健康/活动/FIT/专项 | FND-04、05、06 | Garmin canonical 全部承载 |
| §7.6 邮件/事实/mail agent | FND-07 | 第四层独占邮件和回复投递 |
| 第四层 §11 邮件处理状态机 | FND-07、FND-13 | 第一层 DDL/manifest 与显式 v1→v2 兼容迁移；第四层唯一运行时写入 |
| §7.7 分析/计划/主动投递 | FND-08 | 第三层独占 analysis delivery |
| §7.8 质量和对账 | FND-10 | issue、reconciliation、消费边界 |
| §7.9 第五层运行表 | FND-09、10 | scheduler/orchestrator/health/incident/alert |
| §8–10 幂等、revision、FIT、质量 | FND-03 至 FND-10 | hash/current、质量、精确 delivery |
| §11 SQLite/并发 | FND-02、10、11 | WAL、短事务、锁、single writer |
| §12 隐私安全 | FND-01 至 FND-12 | owner-only、脱敏、无 secrets/CoT |
| §13 稳定读取视图 | FND-10 | current/history/operational views |
| §14 重建/备份/迁移 | FND-02、11、12 | 显式维护、影子重建、可回退 |
| §15 样本/测试 | FND-06 至 FND-09、12 | 合成 FIT/健康/邮件/分析/运行 |
| §16 完成定义 | FND-11、12 | init、schema、视图、三 delivery、第五层表 |
| §17 后续层接口 | FND-01、07 至 FND-10 | 不越权、表所有权、稳定接口 |

## 7. 集成门、真实环境验收门与最终完成门

### 集成门

1. 基础门：FND-01、02 后，空临时根 init 成功且重复 init 严格 no-op。
2. schema 门：FND-03 至 FND-09 后，表、索引、外键、约束和唯一 owner 通过。
3. 读取门：FND-10 后，五层视图、历史 revision、质量和三类 delivery 一致。
4. 维护门：FND-11 后，status/verify 零写入，migrate 显式可回退，bootstrap 零写入。

### 真实环境验收门

本清单当前不执行真实验收。实施和合成集成门全部通过后，受控发布任务才可：

- 备份现有数据库和 raw 清单，在隔离副本验证 schema/视图。
- 由第二至第四层各自执行真实 Garmin/Gmail/Codex smoke test；第一层只验证 ready、schema、权限和 backup/restore。
- 由第五层 shadow workflow 验证 bootstrap；ready 后不得触发 migration。
- 完成 legacy 对账、三类 delivery 所有权、回滚和新旧调度互斥验证。

### 最终完成门

1. FND-01 至 FND-13 均勾选且证据完整。
2. 所有 migration 可从空临时根顺序应用，全部稳定视图可查询。
3. ready 环境 init 与第五层 bootstrap 都严格 no-op。
4. 每张可写表有唯一运行时 owner；第三层主动投递、第四层回复投递、第五层运维告警投递互不共表、互不代发。
5. 合成数据覆盖 Garmin、FIT、邮件、分析、训练、三类 delivery、第五层运行状态并通过隐私扫描。
6. 显式 migrate、备份、影子重建、恢复、legacy 并存的失败回退已演练。
7. 真实环境验收由独立切换任务完成；此前不得宣称生产迁移完成。
8. 本层完成不等同于真实 Garmin ORIGINAL/FIT 下载与解析、真实 Gmail/Codex 调用或生产切换：前两者分别由第二、第四、第三层的受控真实验收负责，生产数据库迁移/切换由独立发布验收负责。

## 8. 已交付接口与后续跨层边界

本清单已交付以下第一层接口与共享存储边界：

- 第一层 init/migration 创建 Garmin canonical/raw/revision/coverage/quality 基础及 `garmin_sync_runs`、`garmin_sync_items`、`garmin_sync_cursors`、`garmin_sync_gaps`、`garmin_resource_capabilities`；第二层是这些 Garmin 运行表的唯一运行时写入者。
- 第三层的 analysis/training/analysis_delivery 表及稳定视图；第三层自行投递 artifact。
- 第四层的 Gmail/会话/fact/mail response/mail delivery 表及视图；第四层不得代发分析 artifact。
- 第五层的 ready/schema、运行表、health/incident 视图和 bootstrap receipt；第五层不得用 bootstrap 修复或 migrate。

后续层与独立发布验收负责的外部边界：

1. 真实账号、备份密钥、服务账户权限、Gmail MCP 部署、systemd 配置均需在受控真实环境验收阶段另行授权。
2. 真实 Garmin FIT 下载、解析器兼容性、Gmail/Codex 真实交互、业务投递和生产迁移切换不属于第一层完成证据；它们分别留给第二至第五层及独立发布验收。
