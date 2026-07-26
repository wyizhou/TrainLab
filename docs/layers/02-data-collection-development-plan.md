# 第二层：Garmin 数据采集工具层详细开发需求清单

状态：开发中（L2-01～16 已完成；L2-17 实现完成、待 E-04；L2-18 离线验收
基础设施完成、真实 smoke 未开始；G-02、G-03 已完成）

基线：第二层开发契约 v1、第一层数据基础契约 v2.4。

## 0. 权威来源与本清单边界

本文件是第二层的实施拆分和验收清单，不是新的跨层契约。实现开始前、每次
跨层集成前均须重新校验以下冻结文件；任何实质冲突均上报总控，不通过修改本清单
或反向修改大契约解决。

| 层 | 权威文件 | 已校验 SHA-256 |
|---|---|---|
| 1 | `docs/layers/01-data-foundation.md` | `9bf0a91e61bda47c9dba971c731ca6ec79e064b7f0ea4eb8124a5a216d67e396` |
| 2 | `docs/layers/02-data-collection.md` | `c39ae1b82afcafe9f4fc3c54d1f851b4992c48021c5238038f078fab1ec885d6` |
| 3 | `docs/layers/03-data-analysis.md` | `4a9b3f1ffb92ba1ad4f56e68380344007e48a43e03a3e0f746399c50da794eb8` |
| 4 | `docs/layers/04-mail-agent.md` | `47175280f917dee55d2aa5f663f0705da8ec7baf463eae5933ea391c0770be94` |
| 5 | `docs/layers/05-orchestration-monitoring.md` | `5b1d5abf15689cec2507bd20e36aa83fe49626dd82247a4c0a1b91cc266ce804` |

第二层只负责 Garmin Connect 的采集、归档、解析、投影、质量状态和其运行表。
它是一次性 Python API/CLI tool，不能实现常驻进程、定时、邮件、AI 分析或第五层
编排。第一层只负责一次性 init/DDL；第三层只读稳定数据与质量门；第四层不接触
Garmin；第五层只传请求、读取 receipt/退出码并决定何时重试。

## 1. 外部前置条件（不属于第二层实施）

这些是开始相应波次前必须取得的证据，不得由第二层任务越权补建。

| ID | 状态 | 外部所有者 | 必须具备的起始快照/证据 | 缺失时的处理 |
|---|---|---|---|---|
| E-01 | [x] | 第一层 | `trainlab foundation init` 已产生 v2.4 compatible/ready 数据目录、DDL、稳定视图及 `garmin_sync_*` 表；可用隔离测试库。 | 停止任何会写数据库的第二层实现与集成；上报第一层。 |
| E-02 | [ ] | 部署/账号所有者 | Python >=3.12 受控运行环境、固定 `garminconnect==0.3.6` 依赖锁定方案、受控 Garmin 测试账号、`subject_identities(provider=garmin)` 绑定授权和无敏感数据的 fixture。 | 仅完成纯离线单元；认证和真实网络验收不得开始。 |
| E-03 | [x] | 第五层/总控 | 冻结的 `SyncRequest`/`SyncReceipt` JSON Schema consumer fixture、invocation ID 传递规则和退出码处理测试桩。 | 可完成第二层 API/CLI 自测；不得假定第五层内部实现或加入调度。 |
| E-04 | [ ] | 迁移负责人 | 现有 Drive/Excel/FIT 路径仍独立运行、备份与只读对账窗口已登记；未授权切换生产 canonical。 | 新工具只在隔离环境或 shadow 数据集运行，不修改旧路径。 |

E-01 证据：第一层 FND-01～12 的 compatible/ready、隔离库与完整 Foundation
离线回归均已登记在第一层实施文档。E-03 证据：
`tests/test_orchestration_s5_06.py` 与
`tests/fixtures/garmin_provider_contract_l2_17.json` 固定 invocation、typed argv、
receipt Schema 和退出码 consumer 边界。E-02 的真实账号部分及 E-04 的迁移负责人
登记仍未完成。

## 2. 共同完成规则

- 所有实施条目起始状态必须为 `[ ]`；勾选只能在该条目的完成定义及证据均满足后进行。
- 每个条目须在实现 PR/变更记录中引用其 ID、输入 SHA、测试命令摘要、脱敏结果和
  回退证据。不得将健康 payload、FIT、token、密码、MFA 或完整原始响应作为证据。
- 网络、文件解析和长等待一律在 SQLite 短事务外；原始对象先经临时文件、校验、fsync
  与原子重命名，再发布 revision/canonical。
- 所有跨层交互仅使用冻结的稳定接口、稳定视图和 ID；私有 SQL、provider payload、
  Harness 路径、token 均不是接口。

## 3. 可独立开发与验证的需求单元

### [x] L2-01｜稳定请求、回执与错误语义

- **目的**：建立唯一 application-service 入口、版本化 `SyncRequest`/`SyncReceipt`、
  CLI 退出码与脱敏错误模型，使 API、CLI 和第五层拥有可验证的共同语言。
- **依赖与起始快照**：冻结契约第 4、5、25 节及 E-03 consumer fixture；开始时记录五份
  权威 SHA 和 Python/依赖锁定快照。
- **负责范围**：定义 mode、日期/资源/activity/repair/invocation 字段的严格互斥校验；
  定义全部 receipt 字段、六种状态、计数、日期范围、游标、gap、next retry 与退出码
  映射；定义 stdout 仅一份 receipt JSON 的边界。
- **禁止触碰范围**：不调用 Garmin、不读写业务表、不实现第五层 executor、不添加
  schedule 参数，不在 receipt 输出原始健康数据、FIT、账号或凭据。
- **预期产物**：版本化类型、JSON Schema、序列化/反序列化器、错误 code 枚举、API
  facade 和 CLI 输出/退出码契约测试资产。
- **验证方法与证据**：Schema 正反例、每个 mode 的参数互斥测试、receipt round-trip、
  exit-code matrix 与 stdout 单 JSON 测试；保留 schema hash、脱敏测试报告。
- **完成定义**：任意调用端可仅凭 Schema 构造/验证请求和回执；非法输入在网络和数据库
  写入前拒绝；CLI/API 不复制业务分支。
- **集成顺序与失败回退**：第一波第 1 项，供全部后续单元依赖；Schema 变更失败时回退到
  此冻结版本并停止跨层集成，不兼容变更上报总控。

  证据：`tests/test_garmin_cli_auth_contract.py` 覆盖六种 exit code、单行 Schema receipt、
  嵌套 sync mode 与脱敏失败；`tests/test_garmin_l2_01_04.py` 覆盖 mode 互斥与 invocation replay。

### [x] L2-02｜离线测试骨架、脱敏 fixture 与确定性时钟

- **目的**：让每个采集单元可在无真实账号、无真实敏感 payload 情况下独立验证。
- **依赖与起始快照**：L2-01、E-02；记录六类代表性 FIT（跑步、抱石、室内攀岩、徒步、
  骑行、力量）的脱敏来源清单和 fixture 哈希。
- **负责范围**：建立 fake Garmin transport、可控时钟/随机源、临时 raw/state 根、
  SQLite fixture、错误注入器、payload 脱敏扫描器与 fixture 命名规范。
- **禁止触碰范围**：不把真实 token、GPS、健康值或账号写入仓库；不伪造第一层 DDL，
  不替代 E-01 的 initializer 验证。
- **预期产物**：离线测试 helpers、合成/脱敏 JSON 与 FIT fixture manifest、网络/磁盘/
  中断 fault-injection adapter、日志泄露断言。
- **验证方法与证据**：离线重复运行结果一致；fixture 扫描无凭据和真实身份；故障可稳定
  复现；测试临时目录在结束后清理。
- **完成定义**：后续健康、活动、重试与恢复测试均可不访问 Garmin 执行，且失败报告只含
  受控 ID/摘要。
- **集成顺序与失败回退**：第一波与 L2-01 完成后开放；fixture 不足时新增合成 fixture，
  不从生产 raw 复制数据。

  证据：`tests/test_garmin_l2_02.py` 覆盖注入 monotonic/RNG/sleep 的固定退避序列、
  顺序 fault outcome、合成健康 JSON、fixture manifest 与 receipt/log 敏感模式扫描；
  `tests/test_garmin_collection.py` 覆盖临时 Foundation raw/state/db fixture 与六类本地 FIT 样本。

### [x] L2-03｜配置、凭据目录、认证与 subject 绑定

- **目的**：安全完成 `auth`，并让正常同步只使用受限 token store 与已验证 Garmin identity。
- **依赖与起始快照**：L2-01、E-01、E-02；以契约第 6、7、21 节配置默认值和权限规则为
  起点。
- **负责范围**：校验 `history_start_date`、global/CN region、重试配置和敏感路径；实现
  一次性 TTY credential provider、MFA 输入、token 0700/0600 收紧、profile/self HMAC
  对账、首次 verified identity 与 identity mismatch。
- **禁止触碰范围**：不保存 Garmin 密码/MFA/token 到 SQLite、配置、日志或 receipt；
  不实现账号 rebind，不把认证做成后台刷新服务，不修改第一层 identity DDL。
- **预期产物**：配置 schema/validator、敏感文件权限 helper、认证 application service、
  auth receipt 和安全失败分类。
- **验证方法与证据**：配置边界测试、权限测试、假 token refresh 后 401→auth_required、
  identity match/mismatch 测试；真实认证仅在 E-02 账号下做脱敏 smoke。
- **完成定义**：`auth` 成功仅输出脱敏 receipt；后续同步不用明文密码；身份不一致在任何
  Garmin 事实写入前停止。
- **集成顺序与失败回退**：第一波；认证失败仅保留脱敏错误/安全 token 文件，撤销或删除
  新 token 需由账号所有者执行，业务数据库不发生写入。

  证据：`tests/test_garmin_cli_auth_contract.py` 覆盖 TTY stderr 提示、递归 token 权限、
  symlink 拒绝、identity mismatch 前零 Garmin raw 与二次 401 的最终 run 状态；
  `tests/test_garmin_contracts.py` 覆盖 adapter/token-store monkeypatch。

### [x] L2-04｜运行状态仓储、单写锁、游标与缺口状态机

- **目的**：以第一层已建 DDL 实现可恢复的 run/item/cursor/gap/capability 状态，而非以
  内存或日志推断同步结果。
- **依赖与起始快照**：L2-01、L2-02、E-01；确认 foundation ready/schema version 与
  `garmin_sync_runs/items/cursors/gaps/resource_capabilities` 的精确结构。
- **负责范围**：实现 run 与 invocation 幂等、stage item、独立资源 cursor、gap 去重/
  resolved 历史、capability 生命周期、短事务 repository、单写锁和陈旧锁双重验证。
- **禁止触碰范围**：不创建/迁移 DDL，不写第三、四、五层表，不让第五层直接改 cursor/
  gap，不等待锁形成死锁。
- **预期产物**：状态 repository、允许状态转移表、锁文件 metadata、恢复 processing item
  的算法和只读 status query。
- **验证方法与证据**：相同 invocation 不产生第二业务 run；并发返回 lock_busy；cursor
  不跨 gap；resolved gap 保留；进程中断后可从持久化状态恢复；给出数据库断言脚本输出。
- **完成定义**：每个后续 pipeline stage 可独立持久化、恢复和审计，且只有第二层运行时
  写这些表。
- **集成顺序与失败回退**：第一波在 E-01 后完成；发现 DDL 不匹配时停止并上报第一层，
  不以运行时 SQL 修补 schema。

  证据：`tests/test_garmin_l2_04.py` 覆盖 interrupted running item→pending、单 run
  continuation、完整 receipt 零网络重放、自动 invocation 与锁账本一致、四类 stale-lock
  判定、status 只读、item 时间语义、capability 生命周期、gap resolved 历史及 cursor
  在 partial/error/missing/deferred gap 前停止；`tests/test_garmin_l2_01_04.py` 保留跨单元回归。

### [x] L2-05｜原始对象、revision 与原子发布

- **目的**：落实 JSON/FIT 不可变证据、语义去重、revision 和 canonical 原子切换。
- **依赖与起始快照**：L2-02、L2-04、E-01；以第一层 v2.4 raw/source revision/source
  role/血缘表定义为唯一数据模型。
- **负责范围**：稳定 JSON 哈希、受控 raw 路径、临时写入/fsync/rename、raw metadata、
  source revision、payload no-op、字段目录登记、解析失败保留证据及 source map 关联。
- **禁止触碰范围**：不长期保存 activity ZIP；不删除旧 raw/revision；不在此单元实现
  FIT 解析或修改其他层主体表。
- **预期产物**：raw archive/publisher、revision comparator、source-field catalog 写入器、
  原子 transaction boundary 和恢复清理策略。
- **验证方法与证据**：同 hash 无重复对象/revision；变更产生新 revision；中断不会发布
  半文件或半个 current；未知 JSON 字段登记；路径、权限、哈希与 fsync 行为测试。
- **完成定义**：所有后续 fetcher 可先 archive 再投影；任何 parse/project 失败仍可
  通过原始对象复现，且 canonical 不被错误覆盖。
- **集成顺序与失败回退**：第二波的共同底座；发布失败仅留可识别临时文件并创建 gap，
  不切换 current，下一次安全清理/重试。

  证据：`tests/test_garmin_l2_05.py` 覆盖 stable JSON no-op、revision/current、
  projector rollback 后 raw 保留、逐级 0700/0600/owner/普通文件验证、symlink 越界、
  create-only 并发竞态、文件和目录 fsync fail-closed、深层字段、FIT 无 ZIP 与 health/activity
  投影失败的 gap/item；`tests/test_garmin_collection.py` 回归活动/FIT 归档。L2-05
  专项 41 项、L2-01～L2-11 分组回归 214 项通过；根会话独立完成 strict JSON、
  零副作用、semantic no-op 与 FIT bypass 探针。

### [x] L2-06｜版本化 GarminResourceSpec 目录与语义去重

- **目的**：将“全部独立健康资源、活动附属资源、条件能力和明确排除”从散落代码变为
  可审计的版本化目录。
- **依赖与起始快照**：L2-01、L2-02；以第二层契约第 8 节完整资源表及 8.2 排除表为
  初始 catalog snapshot。
- **负责范围**：声明 method、scope、分块、required/conditional/ignored、empty/404/
  capability 规则、raw kind、parser 版本、第一层投影、cursor 资格；登记 aliases 和
  `ignored_with_reason`。
- **禁止触碰范围**：不在 catalog 中私自增加 badges、挑战、社交、未来 workout/计划、
  上传/编辑活动或调度；不通过 alias 重复请求同一语义事实。
- **预期产物**：版本化 catalog、catalog lint、endpoint capability mapper、覆盖计划
  生成器和变更审计模板。
- **验证方法与证据**：完整资源矩阵测试；`get_stats`/`get_stats_and_body`/
  `get_stress_data`/morning readiness/weekly wrappers 均有唯一理由；新增删除资源触发
  catalog version 与 audit 测试。
- **完成定义**：full/incremental/snapshot/repair 都从同一目录生成工作项，任何资源的
  缺失、空值、禁用和不支持均有确定语义。
- **集成顺序与失败回退**：第二波，在具体 fetcher 前冻结 v1；目录覆盖不完整时阻断模式
  编排，回退为只执行已验证 resource subset 的隔离测试，不能声称 full 完成。

  证据：`tests/test_garmin_l2_06.py` 静态绑定 `garminconnect==0.3.6` 的全部 catalog
  endpoint/参数形状，覆盖资源矩阵、四种模式、能力/空值语义、alias/exclusion 去重、版本
  变更审计和 fake-client 映射；全量离线 pytest、compileall、diff-check 与五份冻结契约
  SHA-256 均通过。

### [x] L2-07｜Garmin client adapter、节流、重试与错误归类

- **目的**：把 `python-garminconnect==0.3.6` 的网络调用包装为每个逻辑 item 可记录、
  可恢复且不会重复盲重试的行为。
- **依赖与起始快照**：L2-02、L2-03、L2-04、L2-06；锁定 Python >=3.12 和库版本，
  创建 client 时 `retry_attempts=0`。
- **负责范围**：带上下界的伪随机请求间隔、timeout、5 次指数退避加抖动、408/网络/临时 5xx、
  429 Retry-After 和 120 秒内联等待、长 429 deferred、401/403/允许 404/其他 4xx
  分类、冷却时间和 item attempt 记录。
- **禁止触碰范围**：不依赖库的通用 retry；不把 403 变为 empty/not_available；不在
  冷却期再次请求；不输出 provider payload 或凭据。
- **预期产物**：受控 client adapter、错误分类器、rate-limit scheduler、可注入 sleep/
  clock、脱敏 transport telemetry。
- **验证方法与证据**：fake transport 模拟 DNS/timeout/408/5xx、短/长 429、401 refresh
  后失败、403、允许及不允许的 404；断言次数、jitter 边界、next_retry 和 receipt 状态。
- **完成定义**：每个调用以统一语义写 item/gap/run；短故障不阻塞无关项目，长限流不让
  一次性 tool 永久驻留。
- **集成顺序与失败回退**：第二波；adapter 未通过故障矩阵时禁止接入真实账号，改用
  fake transport 保留状态并修正分类器。

  证据：`tests/test_garmin_l2_07.py` 覆盖 DNS/408/5xx 的 5 次内退避和 jitter、短/长
  429 与非默认配置阈值、持久化 cooldown、401 单次 refresh、403、允许/不允许 404、
  其他 4xx、item attempt/next retry/脱敏；使用锁定 `garminconnect==0.3.6` 的实际
  外层 `Garmin.client.cs`/`Garmin.client._api_session` 生产结构及允许的低层 double，
  断言每次 Session request 强制传入配置 timeout 且缺少该结构 fail closed。Garmin 回归、
  全量离线 pytest、compileall、diff-check 和五份冻结契约 SHA-256 均通过。

### [x] L2-08｜基础日级健康资源采集与投影

- **目的**：完成日汇总及常用连续生理数据的 JSON→canonical 可靠管线。
- **依赖与起始快照**：L2-04 至 L2-07、E-01；catalog 中基础资源项：summary、steps、
  floors、heart rate/RHR、hydration、respiration、SpO2、intensity、stress、all-day
  events、sleep/naps、lifestyle、HRV、Body Battery、body composition/weigh-ins、BP。
- **负责范围**：按资源范围抓取、archive、日切分、投影至 `daily_health`、
  `health_samples`、`sleep_sessions`、`sleep_stages`、`body_measurements`、
  `physiology_records/metrics` 与 coverage/capability；验证睡眠阶段边界和样本时间。
- **禁止触碰范围**：不把未启用/不支持写成零；不解释健康意义、不生成分析；不把 snapshot
  partial 当作 completed cursor。
- **预期产物**：基础健康 parser/projector、日期分块器、coverage validator、每资源
  fixture 和字段漂移登记。
- **验证方法与证据**：每资源 fetched/empty/not_enabled/not_available/not_supported、
  revision/no-op、日界/睡眠阶段、字段漂移、coverage 唯一性测试；输出脱敏行数和状态。
- **完成定义**：基础资源均能从同一 raw/revision 管线生成正确 canonical/coverage，
  单项错误仅形成自身 gap，不回滚已完成资源。
- **集成顺序与失败回退**：第三波先行健康批次；任一 resource parser 失败时保留 raw、
  建立 gap，旧 canonical 不变并交由 L2-14/L2-15 补漏。

  证据：`tests/test_garmin_l2_08.py` 使用脱敏基础健康 fixture 覆盖 summary、步数、楼层、
  HR/RHR、补水、呼吸、SpO₂、强度、压力、全天事件、睡眠/nap、lifestyle、HRV、Body
  Battery、身体组成/称重/BP 的 raw/revision/project/coverage 链路；验证 0/null、能力状态、
  字段漂移、跨午夜睡眠/阶段边界、新加坡日、no-op/修订、投影失败回滚保留 raw/gap 和
  snapshot partial 无 cursor；`garmin_health_nested_l2_08.json` 另覆盖 0.3.6 直接 JSON
  的 `heartRateValues`、`stressValuesArray`、`respirationValuesArray`、
  `bodyBatteryValuesArray`、Connect `spO2HourlyAverages` 时间戳数组、身体组成/BP
  wrapper；验证高频数组不伪投影为 `physiology_metrics`，以及 sleepLevelsMap 的 epoch
  秒字符串、epoch 毫秒字符串和 ISO key 的稳定有界阶段排序。
  另覆盖 fetched→empty/not_enabled→fetched 的 immutable tombstone/current 切换、snapshot
  empty 仍为 partial、非法时间/跨范围与 tuple 超额值回滚并建立 gap、daily_health 标量边界、
  canonical 单位和 source-field mapped/unknown 边界。L2-01～08 聚焦回归、compileall、
  diff-check 与五份冻结契约 SHA-256 通过；全量跨层 pytest 仍受其他层共享工作树失败影响，
  不将其伪记为第二层成功。

### [x] L2-09｜高级生理、账号、设备与长期指标资源

- **目的**：完成设备/配置及所有剩余独立生理资源的条件能力、范围切分和投影。
- **依赖与起始快照**：L2-04 至 L2-08；catalog 中 profile/settings/devices、training
  readiness、max metrics、lactate threshold、training status、running tolerance、
  endurance/hill score、race prediction、fitness age、cycling FTP、女性健康、孕期、
  nutrition、personal records。
- **负责范围**：account/device snapshot 与 HMAC 关联、设备及指标历史投影、daily/range
  限制、conditional capability 探测与再探测、所有字段到 `devices`、
  `physiology_records/metrics` 等第一层既定落点。
- **禁止触碰范围**：不改变 subject identity 绑定；不把地区/设备无能力视为错误零值；
  不抓取 goals、workout templates、scheduled workouts 或 training plans。
- **预期产物**：高级资源 fetcher/parser/projector、capability policy、范围分页和
  profile/device revision 处理。
- **验证方法与证据**：每族脱敏 fixture；支持、禁用、不可用、不支持、forbidden 与
  range limit 测试；account/device 无变化 no-op；新增设备/指标修订测试。
- **完成定义**：契约 8.1 的全部高级数据族均被 catalog 计划并有明确结果，未支持资源
  可作为有证据的 coverage 闭合条件。
- **集成顺序与失败回退**：第三波在 L2-08 后；新 endpoint drift 时标记 item/gap 或
  capability，不中断基础资源和活动同步。

  **验收证据**：`tests/test_garmin_l2_09a.py`（账号、身份、profile/settings/devices），
  `tests/test_garmin_l2_09b1.py`（primary/last-used/settings、FTP、孕期、个人纪录）和
  `tests/test_garmin_l2_09b2.py`（女性健康 day/calendar、14 个高级差集资源、0.3.6
  grain/signature、catalog `max_range_days` 的 15/29 日分块、稀疏 range 的逐日
  empty/fetched（整段能力 tombstone 与单日 empty 分离）及共享 source lineage、范围
  短/长 429、timeout/5xx/401/403/404 分类、完整 raw/quarantine（daily/range/activity
  JSON 统一边界）、解析失败保留 non-current received revision/同 hash reparse/旧 canonical、
  malformed/duplicate range 事务回滚、revision/tombstone/capability/lookback/snapshot/脱敏）均离线通过；L2-01～L2-09 聚焦回归、
  compileall、diff-check 和冻结 SHA-256 复核通过。

### [x] L2-10｜活动 inventory、summary 与远端状态

- **目的**：可靠枚举所有已完成活动，保存 inventory 证据，建立 summary canonical 与
  active/suspected missing/provider_deleted 状态。
- **依赖与起始快照**：L2-04 至 L2-07、E-01；以 full 全历史 count/page、增量/快照
  日期窗口和契约第 13.1、19.5 节为基线。
- **负责范围**：count、分页、日期窗口、page raw archive、activity-ID 去重、summary
  获取与身份/时间/类型校验、`activities` 投影、完整 inventory 缺失观察和两次确认删除。
- **禁止触碰范围**：不删除本地 raw/活动；不把单次列表缺失当 provider deleted；不解析
  FIT、不抓 future activity/workout，不在 incremental 做全历史删除扫描。
- **预期产物**：inventory scanner、summary publisher、activity state reconciler、
  分页漂移和缺失观察记录。
- **验证方法与证据**：多页、重复 ID、through 过滤、分页中断、同日重跑 no-op、一次/
  两次完整 inventory 缺失及重新出现测试。
- **完成定义**：任何 activity 后续阶段都以已验证 summary 为前提；活动远端状态有证据
  可追溯，本地历史不因云端缺失被物理删除。
- **集成顺序与失败回退**：第三波可与健康并行；inventory 不完整时状态为 partial/gap，
  不运行 provider_deleted 判定，也不阻断已确认活动的核心处理。

  **验收证据**：`tests/test_garmin_l2_10.py` 覆盖 full 全历史 count/确定性分页、
  incremental/snapshot 日期窗口、每页 raw/revision、page shape/count/ID 与 summary
  身份/时间/类型校验、重复 ID/分页循环/count 漂移、through 预过滤、同 payload 重跑
  no-op，以及 active→suspected missing→provider_deleted、分页不完整不推进、重新出现恢复
  active；生产 adapter count/page/date-list 契约离线通过。L2-01～L2-10 聚焦回归共
  184 项通过，且活动阶段未调用 ORIGINAL/FIT 下载或 FIT 解析。

### [x] L2-11｜ORIGINAL 临时 ZIP、有效 FIT 归档与 FIT 投影

- **目的**：安全取得并无损落地 FIT 传感器、开发者字段、分段、攀岩线路与力量组。
- **依赖与起始快照**：L2-02、L2-05、L2-07、L2-10、E-01；六类 FIT fixture 和第一层
  FIT 相关表结构为起始快照。
- **负责范围**：ORIGINAL ZIP 同文件系统临时存放、大小/成员/CRC/ZIP Slip/符号链接
  校验、多 FIT 选择、FIT CRC/session/activity identity 校验、仅有效 FIT 原子归档；
  解析 session/record/lap/split/set/workout step/length/interval/developer/device/
  course point/低频与未知 message，投影到第一层既定表。
- **禁止触碰范围**：不长期保存 ZIP，不信任 member 路径，不以无验证 FIT 发布 canonical，
  不把 Connect chart 覆盖 FIT，不删除未采用原始证据以外的历史数据。
- **预期产物**：secure extractor、FIT verifier/parser、metric/source mapper、六类
  activity projector、ambiguous/no-FIT quality issue 处理。
- **验证方法与证据**：六类代表性 FIT；跑步 developer fields、攀岩 route、力量 set；
  ZIP Slip/绝对路径/符号链接/多 FIT/损坏 ZIP/FIT CRC/身份错配；确认临时 ZIP 清除且
  FIT hash/path/relation 正确。
- **完成定义**：有效 FIT 覆盖自带及第三方传感器 record 流，并保留标准/开发者字段来源；
  不安全或歧义文件只产生可修复 gap/质量问题，绝不污染 canonical。
- **集成顺序与失败回退**：第四波核心活动项；下载/解析失败删临时 ZIP、保留 summary 和
  failure evidence，转 L2-12 降级或 L2-15 repair。

  证据：`tests/test_garmin_l2_11.py` 的 34 项完整 FIT 回归通过；根会话独立完成
  exact activity-key/day gap 隔离探针，确认单个活动成功不会掩盖同日其他活动缺口。

### [x] L2-12｜活动 enrichments、无 FIT 降级与 JSON/FIT 对账

- **目的**：完成 Connect 专属的 splits/sets/zones/weather/gear，并确定双源 canonical
  选择和无 FIT 时的受控降级。
- **依赖与起始快照**：L2-05、L2-07、L2-10、L2-11；契约第 13.4、13.5、14 节和
  第一层 source role/source map/reconciliation 表为基线。
- **负责范围**：抓取并独立 archive/revise summary、splits、typed splits、split
  summaries、exercise sets、HR/power zones、weather、gear；按需投影 extras/source map；
  无有效 FIT 时 get_activity_details chart 的 `connect_chart` fallback；字段容差、结束
  时间推导、reconciliation result/data quality issue。
- **禁止触碰范围**：不让 chart 覆盖 FIT；不丢弃低频 JSON；不把 `None`/缺失/0 合并；
  不因活动无 FIT 伪称完整。
- **预期产物**：enrichment adapters/projectors、fallback publisher、reconciler、
  source-selection rules 与质量报告。
- **验证方法与证据**：typed split/exercise set/zones/weather/gear fixture；无 FIT chart
  降级、后续 FIT 替换、数值差异越阈值、结束时间推导和 source map 测试。
- **完成定义**：Connect 和 FIT 各自优势字段可共存且选择可解释；已知无 FIT 具备
  fallback/partial 证据，后续 FIT 到达可无损提升 canonical。
- **集成顺序与失败回退**：第四波在 L2-11 后；单个 enrichment 失败保持核心 summary/FIT
  并建立阶段 gap，不能回滚已发布核心活动。

  **验收证据**：`tests/test_garmin_l2_12.py` 的 26/26 项聚焦回归通过；L2-01～L2-12
  分组回归共 240/240 项通过。总控复验的三类 phantom hidden probes 全部通过：
  unknown-only typed split/exercise set 不生成 canonical segment/set/route，unknown/invalid
  chart 不生成 null sample 或 active fallback/source map，mixed payload 只发布逐行验证通过的
  canonical 数据并保留 source index 与 received/valid/dropped/persisted 证据。

### [x] L2-13｜Full、incremental 与 snapshot 统一编排

- **目的**：用同一 catalog/fetch/archive/project pipeline 实现三种日期语义和可恢复
  工作计划，而非三套不一致逻辑。
- **依赖与起始快照**：L2-04 至 L2-12；契约第 10、11、12、16、20 节和
  `history_start_date`/14-day lookback 默认值。
- **负责范围**：full 健康历史至昨天及全活动 history；incremental 每资源独立 cursor、
  最近 14 个完整日重拉、最多 100 个 due gap；snapshot 新加坡今天 partial、不推进
  cursor、仅已上传活动；完整/部分 coverage 与 receipt effective range。
- **禁止触碰范围**：不含 scheduler；不让 full/incremental 推进到今天；不把 snapshot
  成功误记为完整日；不跨 gap 推 cursor，不绕过统一 pipeline。
- **预期产物**：mode planner、work-item scheduler、cursor advance algorithm、range
  validator、resume planner 和 mode-level receipt aggregator。
- **验证方法与证据**：full 中断续跑；14 日窗口；资源游标分离；gap 阻断；100 项上限；
  snapshot 重复 no-op/同日修订/上传后补 FIT；非法日期拒绝；状态/coverage 断言。
- **完成定义**：三种模式均可从任意已持久化状态安全重入，且 full 成功只在所有适用资源
  和活动阶段满足完成规则时出现。
- **集成顺序与失败回退**：第五波，建立在具体资源单元完成后；模式异常时不推 cursor，
  仅保留完成 item 和 open/deferred gap，下一调用恢复。

  **验收证据**：新增 `garmin_modes.py` 纯日期/游标规划器，三种模式继续调用同一
  account/health/activity archive-project pipeline；incremental 在主范围完成后仅处理
  调用前已存在且到期的最多 100 个 gap。`tests/test_garmin_l2_13.py` 的 7/7 项通过，
  覆盖 full 同 invocation 中断恢复、逐资源 cursor 窗口、gap 阻断、100 项上限、
  snapshot no-op/修订/活动复查和非法日期的 provider 前拒绝。第二层现有离线测试
  共 267/267 项通过；未连接真实 Garmin，未加入 scheduler、daemon 或
  后台线程。

### [x] L2-14｜Repair、reparse、reconcile、audit 与只读 status

- **目的**：将错漏、字段漂移、原始文件问题和远端 inventory 差异变为可审计、可选择、
  不盲目重抓的修复工具。
- **依赖与起始快照**：L2-04 至 L2-13；以契约第 19 节、gap reason/state 和 source
  revisions 为起始快照。
- **负责范围**：`auto/refetch/reparse/reconcile` 路由；离线 reparse 影子投影与原子
  current 切换；audit coverage/cursor/gap/activity count/ID/FIT/raw hash/字段签名扫描；
  provider deleted 两次完整 inventory 规则；status 仅本地读取。
- **禁止触碰范围**：不无界 repair；不修改 Garmin 云端；reparse/reconcile 不联网；
  status 不访问 Garmin；不删除失败 raw/revision/gap 历史。
- **预期产物**：repair planner、offline reparser、reconciliation runner、auditor、
  gap lifecycle manager、read-only status formatter。
- **验证方法与证据**：按不同 reason 的 auto 决策；refetch no-op/revision；reparse 成功/
  失败不损旧 current；reconcile 规则版本变化；audit 发现/解决 gap、cursor 跨越、
  raw 缺失、两次 inventory 缺失；status 无 network mock 断言。
- **完成定义**：任何可定位问题均有明确 repair 策略或人工处理状态；audit 不篡改健康
  事实却能建立质量/gap 证据，修复后的历史可追溯。
- **集成顺序与失败回退**：第五波与 L2-13 后；修复失败保持旧 canonical 和 gap，返回
  partial/deferred/failed 的结构化 receipt，不发起无限重试。

  **验收证据**：`src/trainlab/garmin.py` 提供 durable gap 驱动的
  auto/refetch/reparse/reconcile 路由、完全离线的 reparse/reconcile、事务内旧投影
  清理与重建、成功后 current 切换，以及 bounded audit/read-only status。
  `tests/test_garmin_l2_14.py` 的 7/7 项覆盖无显式日期的 raw-key 恢复、失败回滚保留旧
  current、refetch no-op/修订、raw hash gap 建立/关闭、audit 日期窗和 status 零网络；
  L2-10 继续覆盖两次完整 inventory 才确认 provider deleted。

### [x] L2-15｜数据质量门、隐私日志与分析可读状态

- **目的**：将 coverage、活动阶段、cursor、gap、capability 和对账问题汇总为第三层
  可验证的周分析质量事实，也为第五层提供脱敏监控状态。
- **依赖与起始快照**：L2-04、L2-08 至 L2-14；第一层稳定视图、第二层第 20、21 节及
  第三层只读质量门接口。
- **负责范围**：日级/活动完整性校验、样本时间/睡眠边界/FIT 身份/JSON-FIT 一致性、
  ready 判定、warning/error 阻断规则、脱敏日志/错误摘要、质量状态查询和 retention
  边界。
- **禁止触碰范围**：不让第二层生成分析、建议或计划；不替第三层决定其产物；不让第五层
  直接写质量状态；不输出完整健康数据、GPS、FIT、token 或密码。
- **预期产物**：quality evaluator、week readiness query、structured warning/error
  builder、payload redaction tests 和下游只读查询说明。
- **验证方法与证据**：ready、ready-with-warning、blocked 情况；snapshot partial 后由
  completed-day 覆盖；error gap/required stage 阻断；日志/receipt/DB error 敏感内容
  扫描；第三层 consumer fixture 只读验证。
- **完成定义**：候选周是否可供分析有确定、可重演、可解释的答案；任何阻断可定位到
  resource/activity/gap，而不会泄露业务 payload。
- **集成顺序与失败回退**：第六波；质量评估异常时保守返回 blocked/partial 并上报，
  不以人工 cursor 修改绕过门禁。

  **验收证据**：`src/trainlab/garmin_quality.py` 提供只读、版本化的七日 readiness 与
  collection integrity facts；覆盖 capability、coverage、cursor、gap、活动阶段、
  reconciliation、睡眠/样本边界和 subject 隔离。`tests/test_garmin_l2_15.py` 的 7/7
  项覆盖 ready/warning/blocked、snapshot 后完成态、跨 subject 隔离、日期窗与数据库
  失败保守阻断；返回值只含受控 code/entity，不含业务 payload。

### [x] L2-16｜一次性 CLI 装配、进程清理与运维可观测性

- **目的**：将 application service 正确暴露为冻结的 `trainlab garmin` 命令集，并确认
  调用完成即退出。
- **依赖与起始快照**：L2-01、L2-03、L2-13 至 L2-15；契约第 4、4.1、18、21 节。
- **负责范围**：auth/full/incremental/snapshot/repair/audit/status 参数解析、严格日期/
  strategy 验证、统一 API 调用、唯一 receipt stdout、exit code、stderr 脱敏、资源
  清理和无后台线程/监听/daemon 验证。
- **禁止触碰范围**：不提供 `--daemon`、`--schedule`、`--watch`、`--interval`；不替
  第五层调度；不改/删 legacy `trainlab sync`、`ingest` 或其 daemon。
- **预期产物**：CLI command tree、help/validation 文案、process-lifecycle tests、
  structured diagnostic policy。
- **验证方法与证据**：每命令参数/退出码/receipt 测试；stdout JSON 唯一性；非法输入无
  网络；子进程/thread/socket 清理检查；status mock 证明无 Garmin 请求。
- **完成定义**：第五层或人工可在不解析自然语言日志的情况下安全调用每一命令；任意
  命令退出后不存在残留采集服务。
- **集成顺序与失败回退**：第六波，在 service 已完成后接线；CLI regression 时回退到
  API 离线测试，不启用第五层调用或生产切换。

  **验收证据**：`src/trainlab/cli.py` 在加载配置/凭据/provider 前完成严格日期、
  strategy、resource 和参数互斥校验，固定使用 `Asia/Singapore` 解释日期、UTC 完成
  时间、唯一 API 调用和稳定退出码；`activities` 是明确活动资源别名，未知资源拒绝。
  `tests/test_garmin_l2_16.py` 与 auth contract 共 25/25 项通过，覆盖唯一 receipt、
  无监听/后台线程、status 零 transport、非法输入零 provider 及 legacy CLI 保留。

### [ ] L2-17｜跨层 request/receipt 合约与 legacy 并存验证

- **目的**：验证第二层只通过稳定边界参与第五层编排，并为第三层质量读取和旧路径
  对账提供不越权的集成证据。
- **依赖与起始快照**：L2-01、L2-15、L2-16、E-03、E-04；五层权威 SHA 再次校验。
- **负责范围**：第五层 fake executor 的 invocation/exit code/receipt schema/ID/date
  一致性测试；第三层只读 quality consumer fixture；legacy 与 Connect 重叠日期/活动
  对账报告格式、shadow 边界、备份/回滚前置检查。
- **禁止触碰范围**：不实现第五层 scheduler/workflow/incident；不调用第三层 AI 或
  第四层 Gmail；不将新旧来源静默混为 canonical；不关闭旧 daemon。
- **预期产物**：第二层 provider-side contract fixtures、receipt compatibility matrix、
  legacy reconciliation report schema、切换前风险清单与 rollback checklist；完整
  跨层端到端测试由总控方案 `X-02` 唯一拥有。
- **验证方法与证据**：第五层只能传 SyncRequest/read SyncReceipt；无权直接写
  `garmin_sync_*` 的权限/contract 测试；第三层不调用 Garmin；shadow 对账仅生成
  脱敏差异摘要；legacy 命令回归不受影响。
- **完成定义**：第二层提供方职责和数据所有权均可自动验证，且没有任何第二层代码路径
  承担定时、邮件或分析；总控 `X-02` 可直接复用 fixture，生产切换仍是独立未来任务。
- **集成顺序与失败回退**：第七波；合约不兼容即停止该集成，保持新工具隔离和旧路径
  原样，不以适配私有 SQL 临时绕过。

  **当前实现证据（尚不代表验收完成）**：
  `tests/fixtures/garmin_provider_contract_l2_17.json`、L2-17 的 7 项 contract test、
  `garmin_legacy.py`、聚合-only report Schema 与
  `docs/runbooks/garmin-layer-contract.md` 已通过离线验证；第五层无
  `garmin_sync_*` 私有写，第三层无 Garmin provider，第四层仅可读 canonical
  health/activity 且不调用或修改 Garmin，legacy sync/ingest 仍保持原路由。由于 E-04
  的备份与只读 shadow 窗口尚未由迁移负责人登记，本项保持未勾选。

### [ ] L2-18｜受控真实账号 smoke、重复运行与最终回归

- **目的**：在最小授权范围内证明真实 Garmin Connect 行为、文件安全、幂等与一次性
  生命周期符合契约，并为后续迁移提供可审计验收包。
- **依赖与起始快照**：L2-01 至 L2-17、E-01 至 E-04；真实账号书面授权、短日期窗口、
  数据备份、停止/回退方案和无敏感输出环境。
- **负责范围**：在统一健康/活动起点的一至十四天短窗口内，按 `auth`、`incremental`、
  重复 `incremental`、`snapshot`、重复 `snapshot`、`repair`、`audit`、`status` 固定八次
  运行 smoke；代表性活动与不支持健康资源验证；真实 429/缺口若出现的安全 receipt
  记录；进程退出核验。每项记录非敏感耗时，顶层记录端到端总耗时。L2-18 不执行 `full`。
  本次实际 smoke 固定使用三个完整日的共同健康/活动起点；evidence 框架仍允许一至十四天。
- **禁止触碰范围**：不扩大日期范围或权限、不执行生产迁移、不删除/编辑 Connect 云端、
  不把真实 raw/FIT/健康详情复制到测试报告、日志或本文件。
- **预期产物**：脱敏 smoke runbook、run/receipt hash 清单、no-op 对比、质量/gap
  摘要、退出清理检查、问题清单及可执行回退记录。
- **验证方法与证据**：真实短窗后同请求 no-op；一项已上传活动的 summary/FIT/segments/
  samples/enrichment 结构检查；一项 capability 结论；无 daemon/thread/timer/socket；
  receipt/日志/运行表泄露扫描。
- **完成定义**：所有离线验收与真实 smoke 均通过，或每项未通过均有可复现原因、gap/
  incident 交接和总控接受的阻断结论；不以“能下载一次”替代完整验收。
- **集成顺序与失败回退**：最终波；任何异常立即停止扩大测试、保留本地不可变证据和
  脱敏 receipt，按 repair/audit 或账号运维处理，不切换 legacy/第五层生产调度。

  **当前准备证据（尚不代表真实验收完成）**：
  `src/trainlab/garmin_smoke.py`、`scripts/verify_garmin_smoke.py`、严格 evidence
  Schema、19 项 L2-18 聚焦测试及
  `docs/runbooks/garmin-real-account-smoke.md` 已通过独立离线复验。验证器只接受固定
  格式授权/invocation/run ID、统一健康/活动起点的一至十四天新加坡窗口、E-01～E-04、
  备份恢复、legacy 独立、凭据权限、`bounded_activity_window_verified`、request/receipt
  Schema/hash、incremental 与 snapshot 两组重复 no-op、活动结构、capability、安全清理和
  回滚证据及各 stage/端到端计时；它本身不访问 Garmin、
  config、token、数据库或 raw。当前缺少 E-02 真实账号/token、E-04 真实备份恢复和
  shadow 窗口和命名操作员，因此本项保持未勾选。

## 4. 依赖图与开发波次

```text
E-01 ─┬─ L2-03 ─┬─ L2-07 ─┬─ L2-08 ─┐
      │          │          ├─ L2-09 ─┤
      ├─ L2-04 ──┼─ L2-05 ─┤           ├─ L2-13 ─ L2-14 ─ L2-15 ─ L2-16 ─ L2-17 ─ L2-18
      │          └─ L2-06 ─┘           │
      └─ L2-10 ───── L2-11 ─ L2-12 ───┘
E-02 ───── L2-02 ───────────────────────┘
E-03 ──────────────────────────────────────────────────────────────────────── L2-17
E-04 ──────────────────────────────────────────────────────────────────────── L2-17/L2-18
L2-01 ─────────────────────────────────────────────────────────────────────── all implementation units
```

| 波次 | 可开始的单元 | 集成门 |
|---|---|---|
| W0：外部准备 | E-01～E-04 | 权威 SHA 全部匹配；无跨层冲突。 |
| W1：接口和可测性 | L2-01～L2-04 | Schema、fake transport、认证安全、运行状态/锁均离线通过。 |
| W2：采集底座 | L2-05～L2-07 | archive/revision、catalog、retry 分类通过，允许接入 resource 单元。 |
| W3：健康与活动核心 | L2-08～L2-12 | 所有资源族和六类 FIT 通过离线测试；无长期 ZIP。 |
| W4：模式与恢复 | L2-13～L2-15 | full/inc/snapshot、repair/audit、质量门/隐私全部通过。 |
| W5：工具与跨层 | L2-16～L2-17 | CLI 是一次性、第五层仅 request/receipt、legacy 保持并存。 |
| W6：真实验收 | L2-18 | 受控账号短窗、重复 no-op、回退证据完成。 |

## 5. 集成门、真实环境验收门与最终完成门

### [ ] G-01｜基础集成门

L2-01～L2-07 完成，且 E-01/E-02 已满足。必须证明依赖锁、配置权限、Schema、
raw/revision、run/gap/cursor、限流/错误分类均在离线环境可重现；未通过不得连接真实
Garmin。

### [x] G-02｜数据语义集成门

L2-08～L2-12 完成。必须覆盖契约全部健康数据族、活动 inventory、六类 FIT、
enrichments、fallback 与对账；任一必需族仅有占位实现时不得宣称 full 支持。

证据：六类本地 FIT、全部 catalog 健康族、activity inventory/summary/FIT/enrichment/
fallback/reconciliation 的第二层完整离线回归通过。

### [x] G-03｜可恢复工具集成门

L2-13～L2-16 完成。必须证明 full 续跑、14 日重拉、逐资源游标、gap 限额、snapshot
partial、repair/audit/status、429/认证/中断恢复、单写锁和无后台生命周期。

证据：L2-13～16 聚焦回归、错误/认证/锁/中断测试及完整 `tests/test_garmin*.py`
离线回归通过；独立只读复验确认一次性生命周期、repair 原子回退、audit 窗口和质量门。

### [ ] G-04｜跨层接口门

L2-17 完成。必须证明第五层只能传 invocation/request 并读 exit code/receipt/稳定
状态，第三层只读质量，第四层零 Garmin 耦合；不得因集成需求新增第二层调度。

### [ ] G-05｜真实环境验收门

E-01～E-04 与 L2-18 完成。受控真实账号只执行批准短日期窗；相同请求重跑 no-op，
并完成敏感信息泄露扫描、临时 ZIP 清理、进程退出、备份和回退演练。

### [ ] G-06｜第二层最终完成门

仅当 G-01～G-05 均完成，并逐项满足第二层契约第 24 节的 15 条完成定义时，第二层
才可标记“已验证”。此门不授权关闭 legacy、开启第五层正式调度或修改任何其他层。

## 6. 大契约覆盖矩阵

下表逐节映射第二层 v1 的实现义务；“外部”表示该条件必须被验证，但不由第二层
实现。每行至少有一个可勾选开发单元或门，避免遗漏。

| 第二层契约条款 | 覆盖单元/门 | 覆盖结果 |
|---|---|---|
| 1 目标 | L2-01、L2-05、L2-08～L2-13、L2-16 | 一次性采集、raw/revision/canonical/coverage 的完整链路。 |
| 2 非目标与生命周期 | L2-01、L2-04、L2-16、G-03 | 无 scheduler/daemon，短事务和退出清理。 |
| 3 核心决策 | L2-03、L2-05～L2-07、L2-11～L2-13、L2-17 | Python/库锁定、双源优先级、昨天/快照和 legacy 并存。 |
| 4 CLI | L2-16 | 全部命令、参数边界与无调度参数。 |
| 4.1 退出码 | L2-01、L2-16、L2-17 | receipt/exit code 一致性和第五层消费。 |
| 5 API 与类型 | L2-01、L2-16、L2-17 | 单一 service、Schema、invocation ID。 |
| 6 配置 | L2-03、L2-07 | 日期下界、region、token 权限、重试默认值。 |
| 7 认证与绑定 | L2-03 | TTY/MFA、token、HMAC、identity mismatch、401。 |
| 8 资源目录 | L2-06 | versioned spec、scope、coverage 和投影目标。 |
| 8.1 健康资源全表 | L2-08、L2-09、G-02 | 基础和高级全部数据族及 conditional capability。 |
| 8.2 去重与排除 | L2-06 | alias/包装/本地重算及明确非目标理由。 |
| 9 raw/revision | L2-05 | hash/no-op/changed revision/field catalog/parse failure。 |
| 10 full | L2-10～L2-13 | 历史健康、全活动 inventory、阶段完成和断点恢复。 |
| 11 incremental | L2-04、L2-10、L2-13 | 独立游标、14 日回拉、100 gap、活动窗口。 |
| 12 snapshot | L2-10、L2-13 | 今天 partial、无 cursor 推进、已上传活动/FIT 补齐。 |
| 13.1 inventory/summary | L2-10 | count/page/ID、summary identity 和 provider state。 |
| 13.2 ORIGINAL/FIT | L2-11 | ZIP 仅临时、安全校验、FIT 归档和多文件策略。 |
| 13.3 FIT projection | L2-11 | samples/segments/metrics/devices/routes/sets/unknown catalog。 |
| 13.4 enrichments | L2-12 | splits/sets/zones/weather/gear 独立 revision。 |
| 13.5 无 FIT 降级 | L2-11、L2-12 | chart fallback、partial 和未来 FIT 替换。 |
| 14 JSON/FIT 对账 | L2-12、L2-15 | source map、容差、结束时间、质量问题。 |
| 15 运行表 | L2-04 | runs/items/cursors/gaps/capabilities 与唯一写入权。 |
| 16 幂等/游标/gap | L2-04、L2-05、L2-13、L2-14 | raw/revision/canonical/invocation 幂等及连续闭合。 |
| 17 重试/错误 | L2-07、G-03 | 5 次退避、短/长 429、401/403/404、item/run 分类。 |
| 18 原子/锁/并发 | L2-04、L2-05、L2-16 | 单写锁、短事务、原子文件和中断恢复。 |
| 19 repair/reparse/reconcile/audit | L2-14 | 四种策略、离线重建、inventory 删除确认、status。 |
| 20 数据质量/完成门 | L2-08～L2-15、G-02/G-03 | coverage、活动阶段、周质量门和不可绕过状态。 |
| 21 安全/隐私 | L2-02、L2-03、L2-05、L2-07、L2-11、L2-15～L2-18 | credential、ZIP、敏感日志/fixture/输出保护。 |
| 22 legacy 迁移 | E-04、L2-16、L2-17、L2-18 | 并存、shadow 对账、回退；不提前切换。 |
| 23 测试样本 | L2-02、L2-07～L2-18、G-01～G-05 | unit/fixture/FIT/mode/fault/真实 smoke 全覆盖。 |
| 24 完成定义 | G-06 | 15 条定义均作为最终 gate 的逐条核验项。 |
| 25 固定接口 | E-01、E-03、L2-01、L2-04、L2-15～L2-17、G-04 | 第一层 DDL、第三层只读、第四层隔离、第五层 request/receipt。 |

## 7. 跨层影响与越权检查矩阵

| 相邻层冻结边界 | 第二层必须提供/遵守 | 对应条目 | 第二层明确不做 |
|---|---|---|---|
| 第一层 v2.4 | 使用 init 已建目录、DDL、raw/revision/稳定视图；独占 Garmin 运行时写入。 | E-01、L2-04、L2-05 | init 后重建目录/表、schema migration、写非 Garmin 所有者表。 |
| 第三层 v2 | 提供 canonical、coverage、gap、quality 的只读可验证事实。 | L2-15、L2-17 | 直接调用 Codex、生成日报/周报/计划或写 `analysis_*`。 |
| 第四层 v2 | 与 Gmail/邮件事实隔离。 | L2-17 | Gmail MCP、收件、回复、标签和 `mail_*` 写入。 |
| 第五层 v1 | 接受受限 `SyncRequest`（含可选 invocation ID），返回 receipt/退出码，支持 repair/audit/status。 | L2-01、L2-14、L2-16、L2-17 | cron、Supervisor、workflow、重试编排、incident 或直接让第五层写 cursor/gap。 |

## 8. 未决问题登记规则

本清单当前不改变任何大契约。后续出现以下问题必须记录为阻断项并报总控：

1. 第一层 v2.4 DDL/稳定视图无法表达第二层既定 source role、coverage 或运行表字段；
2. 固定 `garminconnect==0.3.6` 的真实 endpoint 行为与 resource catalog 的语义不一致；
3. 第五层 consumer 无法验证冻结 receipt Schema、invocation ID 或 exit code；
4. 真实 Garmin 账号权限、地区或健康资源能力使“required/conditional”归类需要改变；
5. legacy 对账显示同一对象的 canonical 归属存在未在冻结契约中规定的冲突。

在总控明确更新大契约前，第二层只能以 `partial`、`deferred`、gap/capability 证据
停止相应范围，不能自行扩大边界。
