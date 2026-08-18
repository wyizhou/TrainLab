# 执行计划：M9 单日 Garmin MCP 有界真实只读闭环

- 状态：`completed`
- 负责人：主协调 Agent
- Roadmap ID：`M9-0001..M9-0005`
- 阶段/子项目：`M9/garmin-live`
- Batch ID：`serial-m9`
- 返工来源：`无`
- 开始日期：2026-08-17
- 最后更新：2026-08-18

## 目标与验收标准

先保存 M8 本地基线，再用固定版本、本地缓存和 cached-token-only 的 Garmin MCP，在仓库外
candidate 中只读采集香港时区 2026-08-16 的健康/活动和醒来日为 2026-08-17 的主睡眠，完成
capture、解析、SQLite 落账和真实 AI 离线日报。Code、AI 和 Data/Privacy 三类全新只读 Validator
全部 `PASS` 才完成。

完成只证明单日 Garmin MCP 读取链与 candidate 离线日报可用，不授权正式 state 更新、Gmail、
Workout、Sites、cron、远端推送或 M9 代码提交。

## 范围与非目标

- 固定执行日：`2026-08-17`；健康/活动日：`2026-08-16`；主睡眠醒来日：`2026-08-17`；
  时区：`Asia/Hong_Kong`。
- 固定基础工具：`get_rhr_day`、`get_hrv_data`、`get_heart_rates`、`get_vo2max_trend`、
  `get_weigh_ins`、`get_sleep_data`、`get_activities_by_date`。
- 活动追加仅限最多 2 项新/不完整活动的 FIT，各自最多一次；明确户外时各自最多一次 weather。
- 禁止 `activity_summary`、GPX、TCX、CSV、历史 14 天回读、自动重试和未批准工具。
- 不发送 Gmail、不创建/删除/排期 Workout、不调用 Sites、不安装 cron、不修改正式 state、不推送。

## 适用规则与参考资料

- 已批准规则：A-001、A-004、A-008、A-009，以及根 `AGENTS.md` 的隐私、测试先行和独立 Validator 规则。
- 按需读取的 references：无。
- 固定依赖：Garmin MCP commit `3610be6feed93088d85b0f35aba9d7d07c2505a7`、
  `garminconnect==0.3.9`、`mcp==1.29.0`，仅允许本机缓存和 `uvx --offline`。

## 依赖与隔离

- 显式依赖：M8 completed；本地基线提交 `69ed9b4`；本机 Garmin MCP 缓存与 cached token 可用。
- 共享接口和冻结依据：用户本轮批准的固定日期、工具、预算和零外部写入边界。
- 任务分支：不适用——用户要求严格串行且 M9 代码不自动提交。
- Worktree：不适用——仓库外 candidate 承载私人运行数据。
- 集成分支：不适用。
- 允许写入范围：`PLANS.md`、`memory.md`、本计划、`CHANGELOG.md`、`source/requirements.txt`、
  `source/skills/README.md`、`source/skills/garmin-sync/**`、必要的 `source/skills/_shared/**`、
  `source/skills/training-coach/**`、`source/skills/training-report-publisher/**`、
  `source/tests/code/**`；仓库外 candidate/run root。
- 禁止写入范围：正式 `source/state/**`、`source/goal.md`、凭据、Token 目录、`data-backup/**`、
  Gmail/Garmin Workout/Sites/cron、远端 Git。

## 冻结预算

| 边界 | 上限 |
| --- | --- |
| MCP 工具调用 | 11 |
| Provider entry（含缓存会话初始化） | 12 |
| inventory 活动 ID | 10 |
| FIT | 2 |
| weather | 2 |
| 新 Capture/FIT 文件 | 11 |
| 墙钟 | 90 秒 |
| 自动重试 | 0 |

`has_more=true`、活动 ID 超限、日期不符、新/不完整活动超过 2 项、Token 变化或任一预算超限均
立即停止；不得在本计划内重试、扩大范围或改变正确预期。

## r04 AI 阻塞恢复批次

- 用户于 2026-08-17 明确批准复用现有 r04 Candidate，不再读取 Garmin，只以完全相同的
  `prompt.txt`、`context.json` 和 `daily_ai_result_v1` Schema 执行一次新的 Codex attempt 2。
- attempt 1 永久保留为 `exit 1 / 原因未分类`；不得事后改写为 transport/5xx 或 PASS。
- 新增确定性 `training-coach/scripts/run_codex_daily.py`：固定 `--ephemeral`、
  `--ignore-user-config`、read-only sandbox、JSONL events、日报 Schema 和 180 秒上限；不接受日期、
  daily/weekly、request-id 或替代输入。
- attempt 2 必须逐字节匹配 r04 输入 SHA；事件、stderr、结构化 attempt receipt 与成功结果只写入
  Candidate 内新的 owner-only `ai-attempt-2/`，采用临时文件、Schema 校验、fsync 和原子改名。
- 错误分类只允许来自 Codex 结构化 error/failed 事件或受控 CLI stderr，不得因模型正文包含
  `500` 等文字而误判；分类固定为 `transport_retryable`、`server_5xx_retryable`、
  `schema_non_retryable`、`auth_non_retryable`、`sandbox_non_retryable`、`cli_non_retryable` 或
  `unknown_non_retryable`。
- attempt 2 无论失败类型均不再自动重试；失败则保存证据并恢复 `blocked`。成功才允许走既有
  AI 证据校验、Candidate SQLite 不可变提交、open_report 与 workflow receipt；邮件、GTS、
  external action 继续为零。

## r05 Structured Outputs Schema 修正批次

- 用户于 2026-08-17 明确批准在不改变 M9 日期、数据、Prompt、Context、业务 Schema、安全规则
  和正确预期的前提下，修正 Codex Structured Outputs 接口不支持 `allOf` 的兼容性问题，并执行
  唯一一次新的 Codex attempt 3；不得执行 attempt 4。
- attempt 1 当时未保留运行目录，其“exit 1 / 原因未分类”事实继续只由计划历史记录；不得伪造
  `ai-attempt-1/`。attempt 2 的失败目录、回执和分类证据永久保留，不覆盖、不改写、不复用为成功。
- 保留 `daily_ai_result_v1` 作为确定性业务验收 Schema；新增仅用于 Codex 输出约束的
  `daily_ai_result_codex_v1` wire Schema。wire Schema 必须满足官方 Structured Outputs 子集，
  但最终结果仍须通过原业务 Schema、证据引用、数值绑定和安全门，禁止借兼容性修正放宽验收。
- attempt 3 逐字节复用 r04 的 `prompt.txt` 与 `context.json`；只允许 wire Schema 字节和 SHA 与
  attempt 2 不同。调用器固定 `--ephemeral`、`--ignore-user-config`、read-only sandbox、180 秒、
  owner-only 原子产物，并写入新的 `ai-attempt-3/`。
- “Prompt 已送达”在本合同中定义为：父进程已把冻结 Prompt 的全部字节成功写入受信任 Codex CLI
  的 stdin 管道并关闭写端；CLI/模型是否在内部消费每个字节不提供可验证回执，不能以不可实现的
  子进程阅读确认扩大本计划。若管道提前关闭或仍有未写字节，则 attempt 必须失败。
- attempt 3 启动前只允许既有 `ai-attempt-2/`；`ai-attempt-1/`、`ai-attempt-3/`、
  `ai-attempt-4/` 或任何其他 attempt 目录均 fail closed。成功回执采用失败优先发布：任何截止、
  原子写入或终止异常都不得留下成功回执。
- 先以回归测试证明 wire Schema 不含不支持的组合关键字、所有对象字段均为 required 且
  `additionalProperties=false`，并证明原业务 Schema 仍会拒绝缺少成功/阻断必需字段的结果；随后
  由全新只读 Code Validator `PASS` 才能消耗 attempt 3。
- attempt 3 失败时保存结构化证据，M9 恢复 `blocked`，不进行第四次调用。成功时才允许继续
  Candidate SQLite 不可变提交、open_report JSON/HTML、workflow receipt 和确定性幂等重放；
  Garmin、Gmail、Workout、Sites、cron 与 external action 继续为零。

## r06 threat-model closure batch

- 用户于 2026-08-18 批准：不改变 M9 日期、Candidate、Prompt、Context、wire/业务 Schema、
  安全规则或正确预期；180 秒只约束 Codex 启动、Prompt 传输、模型运行和终止。本地同步证据
  收尾不计入该模型截止；永久内核 I/O 阻塞属于 `host_io_unavailable`。
- 固定状态机为：`preflight → pending intent durable → Codex running → process stopped →
  result validated → terminal bundle prepared → atomic directory publish → downstream`。
- `ai-attempt-3.pending/` 是唯一未完成状态；其中先持久化 `attempt-intent.json`。Codex 及其
  日志只能写 pending。只有确认进程结束、证据闭合且双 Schema 通过后，主进程才可把整个目录
  原子改名为 `ai-attempt-3/`。pending 永远不能作为成功或下游输入。
- pending 一旦建立，禁止再次启动 Codex；不得建立 attempt 4。终止不确定、有限本地写入失败
  或崩溃均保持 pending/blocked。永久 I/O 卡死、恶意同 UID/root、内核和硬件故障不属于应用层
  可用性保证，但任何不完整状态仍不得解释为成功。
- 删除后台写线程、取消信号、rollback payload、fallback→success 覆盖、异步启动/reap 和
  finalization reserve。保留冻结输入、attempt 2 证据、只读 Schema FD、Prompt 完整送达、进程组
  终止、日志预算、双 Schema、owner-only 原子发布和错误分类。
- 完整威胁模型、T01～T16 故障矩阵和 r05 Validator 1～10 回归映射冻结在
  `source/tests/code/contract/m9-codex-runner-regressions.md`。所有既有测试场景保留；只把旧的
  “本地落盘也属于180秒”断言改为本次人工批准的模型截止语义，不删测试、不 skip/xfail。
- 先由全新只读 Design Validator 审查上述合同；PASS 后才允许修改调用器。实现完成后由全新
  Code Validator 按冻结矩阵一次性验收；矩阵外发现先判定 scope challenge，不再逐轮扩张合同。

## r07 Structured Outputs v2 与 attempt 4 批次

- 用户于 2026-08-18 批准：继续复用 r04 Candidate，保持日期、Prompt、Context、
  `daily_ai_result_v1` 业务 Schema、训练安全规则与正确预期不变；不再读取 Garmin，不调用
  Gmail、Workout、Sites 或 cron，不修改正式 state、Token、goal 或凭据。
- attempt 2、attempt 3 与 `daily_ai_result_codex_v1` 永久保留原字节和失败语义。新增
  `daily_ai_result_codex_v2`，只为 `schema_version`、`status`、`safety` 和
  `provider_calls` 补齐显式类型；payload 的 `schema_version` 仍为 `daily_ai_result_v1`。
- 新增官方 Structured Outputs 子集 allowlist 检查；必须在创建 pending 或启动 Codex 前递归
  验证根对象、显式类型、enum/const 类型相容、required、`additionalProperties=false`、本地
  `$ref`、数组 items、禁用关键字及规模上限。
- attempt 4 使用新的 intent/receipt v2 和 `ai-attempt-4.pending/ → ai-attempt-4/` 单写者状态；
  intent 绑定 attempt 3 receipt、冻结 Prompt/Context、wire v2、原业务 Schema 与 canary receipt
  的 SHA。attempt 2、3 必须为闭合失败终态；attempt 4 失败或 pending 均继续 blocked，不得 attempt 5。
- 用户授权最多两次新 Codex 调用：先在仓库外 owner-only 临时目录使用公开合成数据与 wire v2
  执行一次 Schema canary；只有 canary PASS 才执行唯一私人 attempt 4。canary 不读取或挂载
  Candidate、goal、正式 state、Token 或私人 Prompt/Context。
- 保留 r06 的 T01～T16、安全边界和全部既有测试；新增 v1 不变、四字段显式类型、allowlist、
  canary、attempt 2→3→4 证据链、attempt 5 禁止及下游重放测试。实现后只交一名全新高风险
  Code Validator 按冻结范围一次性验收，不逐轮扩张新威胁假设。

## 功能与测试映射

| 功能 | Feature slug | 测试目录 | 必须满足的行为 |
| --- | --- | --- | --- |
| MCP 请求与白名单 | `garmin-live-contract` | `source/tests/code/contract/` | 日期、工具、参数、commit/依赖、预算在 Provider entry 前冻结 |
| cached-token-only runner | `garmin-live-runner` | `source/tests/code/integration/` | offline cache、无密码/MFA/刷新、Token before/after 不变、无重试 |
| Capture/FIT 持久化 | `garmin-live-capture` | `source/tests/code/unit/`、`contract/` | 原子 0600、来源标记、SHA/manifest/SQLite 闭合、冲突拒绝 |
| inventory/活动预算 | `garmin-live-inventory` | `source/tests/code/unit/`、`integration/` | page0/size10、has_more/日期/数量 fail closed、最多2项 FIT/weather |
| 日报离线闭环 | `garmin-live-daily` | `source/tests/code/integration/`、`source/tests/ai/` | 有界证据、缺失前置阻断、AI 无 MCP、报告/receipt、零外部动作 |

## 工具采用情况

- 可执行技术栈：Python 3.12、SQLite、JSON Schema、stdio MCP、`uvx --offline`、Codex CLI。
- Linter：`ruff --config skills/_shared/ruff.toml check skills tests/code` 与 format-check。
- 测试：`pytest tests/code`、mypy、compile、Schema/metadata/privacy/layout/diff 门。
- 在线调用前必须由全新高风险只读 Code Validator `PASS`；在线后再由全新 AI 与 Data/Privacy Validator 验证。

## Subagent 派发

| Attempt | Agent 角色/任务 ID | 风险与复杂度 | 模型档位 | 推理档位 | 选档理由 | 平台支持 | 写入边界 | 产物与门禁 | 结果 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Code Validator / M9-0003 | high | high | high | 首次真实 Provider 读取前验证范围、Token 与预算安全 | supported | 只读 | 完整 code gates 与 fake MCP 对抗验证 | FAIL：发现 Token 刷新/库内重试、正式路径、失败重入、权限、既有 FIT、回执与错误摘要 8 项缺口；Provider 保持 0 |
| 2 | Code Validator / M9-0003 | high | high | high | 对首轮 8 项修正做全新高风险复验 | supported | 只读 | Token 影子+刷新禁用、Candidate 门、一次授权、FIT/回执/错误摘要及完整门禁 | FAIL：发现依赖库 profile/settings 隐藏重试、Candidate DB 符号链接越界、重复活动 ID 与返回回执 Schema 4 项缺口；Provider 保持 0 |
| 3 | Code Validator / M9-0003 | high | high | high | 对第二轮 4 项修正做全新高风险复验 | supported | 只读 | 实际依赖单次 profile/settings、Candidate 路径、活动唯一性、回执 Schema 及完整门禁 | FAIL：发现 raw 子目录 symlink、candidate 未绑定运行 guard、VO₂ 内部 fallback、context 原始字节复核、分页回执与 finalizer scope 6 项缺口；Provider 保持 0 |
| 4 | Code Validator / M9-0003 | high | high | high | 对第三轮 6 项修正做全新高风险复验 | supported | 只读 | Candidate 全路径、受验证 runtime guard、Provider 单入口、context SHA、分页与 finalizer scope | FAIL：初始化仍有2次 Provider 进入，最坏总量13；日报输出目录可 symlink 越界；Provider 保持0 |
| 5 | Code Validator / M9-0003 | high | high | high | 对第四轮 2 项修正做全新高风险复验 | supported | 只读 | 零Provider初始化、最坏11次实际工具进入、Candidate内报告输出边界及完整门禁 | FAIL：零初始化无法取得RHR所需display_name，首个工具在Provider前失败；Provider保持0 |
| 6 | Code Validator / M9-0003 | high | high | high | 对第五轮初始化修正做全新高风险复验 | supported | 只读 | 单次profile初始化、无settings、最坏12次实际Provider进入及完整门禁 | FAIL：activity evidence 未绑定同步回执中的精确 FIT raw ID，多修订时可选中旧文件；Provider 保持0 |
| 7 | Code Validator / M9-0003 | high | high | high | 对第六轮 FIT 回执绑定修正做全新高风险复验 | supported | 只读 | 精确 raw ID、路径/权限/链接/大小/SHA 复核、双 FIT 修订与完整门禁 | FAIL：finalizer 可接受 receipt 外 raw、成功重放不复核 raw、两字段 Candidate marker 可伪造；Provider 保持0 |
| 8 | Code Validator / M9-0003 | high | high | high | 对第七轮证据闭包与 Candidate provenance 修正做全新高风险复验 | supported | 只读 | finalizer 重建 context、重放 raw 复核、DB 绑定 Candidate 构建收据及完整门禁 | FAIL：HRV `_ms` 字段丢失、封存后 raw 未限来源、初始化失败少记 Provider、running receipt 可误复用；Provider 保持0 |
| 9 | Code Validator / M9-0003 | high | high | high | 对第八轮解析、来源链、计数与终态修正做全新高风险复验 | supported | 只读 | 实际 HRV 字段、post-seed raw provenance、初始化失败计数、仅 succeeded receipt 复用及完整门禁 | FAIL：Candidate 未精确绑定正式 source、nap/多主睡眠边界不完整、空 JSON 健康壳可进入 AI、计划写入范围漏列；Provider 保持0 |
| 10 | Code Validator / M9-0003 | high | high | high | 对第九轮 Candidate 正式来源、睡眠和空健康门做全新高风险复验 | supported | 只读 | 正式 seed/fingerprint 绑定、唯一主睡眠、至少一项有效非睡眠健康证据及完整门禁 | FAIL：下游上下文/AI提交/finalizer 可接受所属 run 仍为 running 的回执；Provider 保持0 |
| 11 | Code Validator / M9-0003 | high | high | high | 对第十轮同步终态下游绑定修正做全新高风险复验 | supported | 只读 | context、commit、finalizer 三层只接受 succeeded run 回执及完整门禁 | FAIL：Candidate 只验自洽指纹，未在放行前与当前正式 state 重新核对；Provider 保持0 |
| 12 | Code Validator / M9-0003 | high | high | high | 对第十一轮正式 state 即时核对修正做全新高风险复验 | supported | 只读 | Provider 前持正式锁重算 fingerprint 与 DB raw seed，与 Candidate receipt 精确相等，再跑完整门 | FAIL：blocked context 仍生成 AI Prompt 且 CLI 返回0；Provider 保持0 |
| 13 | Code Validator / M9-0003 | high | high | high | 对第十二轮 AI 前 blocked 门修正做全新高风险复验 | supported | 只读 | blocked context 只留审计 JSON、不生成 Prompt、CLI 非0且 AI 调用0，再跑完整门 | FAIL：旧 Prompt 路径未在入口 fail closed；90秒未包含 Candidate/正式指纹和 Token 准备；Provider 保持0 |
| 14 | Code Validator / M9-0003 | high | high | high | 对第十三轮 Prompt 新路径与全流程墙钟修正做全新高风险复验 | supported | 只读 | Prompt path 必须初始不存在；90秒从 collect 入口开始且 Provider 前再查；完整门 | FAIL：Candidate 非零 WAL 可被 immutable 读取忽略，post-seed 写入可绕过来源门；Provider 保持0 |
| 15 | Code Validator / M9-0003 | high | high | high | 对第十四轮 Candidate SQLite sidecar 静止门做全新高风险复验 | supported | 只读 | Provider 前拒绝非零 WAL、活动 SHM、symlink/异常 sidecar；保持写连接探针与完整门 | FAIL：正式 raw/DB/WAL/SHM 的 mode/nlink 与活动 SHM 门不完整；清理和回执未纳入完整墙钟；Provider 保持0 |
| 16 | Code Validator / M9-0003 | high | high | high | 对第十五轮正式 state 元数据和完整墙钟修正做全新高风险复验 | supported | 只读 | owner/mode/nlink、活动 SHM、Finder 杂项隔离、90秒内清理落账及完整门 | FAIL：回执写入期超时未降级、外部空闲SQLite连接未拒绝、Candidate根目录未验0700；Provider保持0 |
| 17 | Code Validator / M9-0003 | high | high | high | 对第十六轮外部句柄、Candidate根和回执期限修正做全新高风险复验 | supported | 只读 | 外部空闲/活动SQLite、Candidate根0700、回执写入超时降级及完整门 | FAIL：回执后第二次期限检查可降级内存/run，却未追加对应blocked回执；Provider保持0 |
| 18 | Code Validator / M9-0003 | high | high | high | 对第十七轮回执终态一致性修正做全新高风险复验 | supported | 只读 | 收口预留、回执写入跨线时返回/最新receipt/run三者一致及完整门 | PASS：106 tests与全部静态/对抗门通过；Provider/MCP/网络为0 |
| 19 | Code Validator / M9-0004 | high | high | high | Candidate r01 在安全收口门失败后复验 checkpoint 修正 | supported | 只读 | Candidate writable schema应用后显式checkpoint、仅清理零WAL、全新构建与完整门 | PASS：107 tests、合成全构建和静态门通过；Provider为0 |
| 20 | Code Validator / M9-0004 | high | high | high | Candidate r02 暴露失活非零SHM后复验安全清理 | supported | 只读 | WAL必须为零；SHM仅在无句柄/锁时可清理，活动SHM保留并fail closed；真实形态全构建 | FAIL：检查结束后释放SHM锁、再删除旁车，真实SQLite连接可在两步之间进入；Provider保持0 |
| 21 | Code Validator / M9-0004 | high | high | high | 对SHM检查/删除同锁原子化修正做全新高风险复验 | supported | 只读 | 持SQLite SHM排他锁到零WAL与失活SHM删除完成；活动连接、并发进入、部分删除和完整构建均fail closed | FAIL：扫描后仍可出现新数据库句柄，且第二次unlink失败会留下部分清理；Provider保持0 |
| 22 | Code Validator / M9-0004 | high | high | high | 对Candidate旁车非破坏保留策略做全新高风险复验 | supported | 只读 | checkpoint后WAL为零、SHM无活动连接；不unlink任何旁车；live门接受失活SHM并拒绝活动连接/非零WAL；完整构建与静态门 | FAIL：可写打开/checkpoint发生在首次旁车检查前，预存非零WAL会被合并进主库；Provider保持0 |
| 23 | Code Validator / M9-0004 | high | high | high | 对Candidate写前/写后双旁车门做全新高风险复验 | supported | 只读 | 每次可写打开前拒绝并原样保留非零WAL/活动SHM；写后checkpoint并再次验证；非破坏保留与完整构建 | FAIL：首次门返回后、原库connect前仍可注入崩溃WAL并被合并；Provider保持0 |
| 24 | Code Validator / M9-0004 | high | high | high | 对Candidate数据库写时复制发布做全新高风险复验 | supported | 只读 | 原库只immutable读取；Schema/receipt写私有副本；发布前复核原库/旁车未变后原子替换；两处WAL竞态、失败保全与完整构建 | FAIL：最终复核与普通replace之间的原库变化仍会被覆盖；Provider保持0 |
| 25 | Code Validator / M9-0004 | high | high | high | 对Candidate数据库原子交换后验验证做全新高风险复验 | supported | 只读 | Darwin原子交换新旧DB；从交换后的旧inode验证复核前状态，漂移则原子换回；WAL/主库各阶段注入、失败保全与完整构建 | FAIL：私有工作库未放在state子目录，合法零WAL/32KB失活SHM被路径门误拒；Provider保持0 |
| 26 | Code Validator / M9-0004 | high | high | high | 对受控私有state工作库与原子交换做全新高风险复验 | supported | 只读 | 私有work_root/state复用相同sidecar锁门；当前六表Schema checkpoint、完整build+receipt、交换竞态与全部静态门 | FAIL：后验失败且原子换回也失败时finally删除了保存旧库的work_root；Provider保持0 |
| 27 | Code Validator / M9-0004 | high | high | high | 对原子换回失败证据保全做全新高风险复验 | supported | 只读 | 换回失败返回独立错误，保留0700 work_root与0600旧DB；Candidate判废；正常完整build与全部门 | PASS：115 tests与全部静态/对抗门、完整Candidate、正式state不变均通过；Provider/MCP/网络为0 |
| 28 | Code Validator / M9-0004 | high | high | high | 对live_sync独立CLI启动修正做全新高风险复验 | supported | 只读 | 从仓库根/任意cwd且无PYTHONPATH加载CLI；不启动MCP的help门；完整116 tests和此前安全门不回退 | PASS：三种cwd、116 tests与全部门通过；r03无live run/capture，Provider/MCP/网络为0 |
| 29 | Code Validator / M9-0004 | high | high | high | 对在线后离线日报启动器修正和r04整体做全新高风险复验 | supported | 只读 | Python 3.12 offline/no-PYTHONPATH 的 Prompt/finalizer CLI；118 tests；r04 live回执/raw闭合/正式state不变 | PASS：118 tests与全部门通过；r04为9,342 raw/120,646,692 B、8 MCP/9 Provider、重放Provider=0、external_actions=0；本Validator未调用外部服务 |
| 30 | Code Validator / M9-0004 r06 | high | high | high | 对合并修正后的 T01～T16 冻结矩阵做最终高风险复验 | supported | 只读 | 进程组静默、双 Schema、正式 state/Token 门、有限 I/O、attempt 3 状态机与完整代码门 | FAIL：仅 T06/T12 仍不完整；发送终止信号后没有观察进程组实际消失即可返回成功，其余门通过且外部调用为0 |
| 31 | Final Code Validator / M9-0004 r06 | high | high | high | 对严格进程组消失证明及完整冻结矩阵做最终复验 | supported | 只读 | 能终止的后代进程须在发布前消失；无法证明消失则保留 pending；180 tests与全部静态门 | PASS：完整套件两次180 passed、晚到后代20/20、T01～T16与全部静态门通过；r04仍只有attempt 2，外部调用0 |
| 32 | Code Validator / M9-0004 r07 | high | high | high | 对 wire v2、离线 allowlist、公开 canary 与 attempt 4 证据链做一次性冻结范围复验 | supported | 只读 | FAIL：完整 `$defs`/引用深度与 canary 根隔离缺口 | completed |
| 33 | Final Code Validator / M9-0004 r07 | high | high | high | 只复验冻结范围内的合并修正、既有安全矩阵和完整代码门 | supported | 只读 | FAIL：canary隔离未贯穿消费端；计划写入范围漏列Skills索引 | completed |
| 34 | Definitive Code Validator / M9-0004 r07 | high | high | high | 最终复验共享canary根门、冻结Schema/attempt链和完整代码门 | supported | 只读 | FAIL：专用根仍可嵌套于temp下的state/token/private目录 | completed |
| 35 | Boundary Code Validator / M9-0004 r07 | high | high | high | 复验系统临时目录直接子级边界、冻结Schema/attempt链和完整代码门 | supported | 只读 | PASS：207 tests、全部冻结门、r04 attempt2/3闭包与零外部动作通过 | completed |
| 1 | AI Validator / M9-0005 | high | high | high | 私人健康/训练语义与不编造复核 | supported | 只读 | 日报证据、训练解释、报告一致性 | blocked：attempt 3 未产生 AI result，不能执行语义认证 |
| 1 | Data/Privacy Validator / M9-0005 | high | high | high | 正式 state、Token、raw/capture 血缘与权限高风险复核 | supported | 只读 | 指纹、闭包、预算、零外部动作 | PASS：仅认证 attempt 3 安全失败闭包，不认证 M9 完成 |
| 2 | AI Validator / M9-0005 r07 | high | high | high | 复核attempt4日报证据、结论、安全、不编造及报告一致性 | supported | 只读 | 私人AI结果、bounded evidence、报告/SQLite/receipt一致 | PASS：日期与证据边界、数值绑定、安全降级、不编造、attempt链及报告一致性全部通过；无外部动作 |
| 2 | Data/Privacy Validator / M9-0005 r07 | high | high | high | 复核正式边界、Candidate闭包、权限、血缘与零外部动作 | supported | 只读 | state/Token稳定门、raw/capture/AI/report/receipt闭包、幂等 | PASS：9,342 raw双向闭包、SQLite/权限/血缘、正式state与Token稳定、幂等及零外部动作全部通过 |

## 工作分解

| 步骤 | 状态（`pending`、`in_progress`、`blocked`、`done`） | 证据 |
| --- | --- | --- |
| M9-0001 保存 M8 本地基线 | `done` | `69ed9b4 feat: complete real-data AI coaching closure`；M8 53 tests 与静态门重跑通过 |
| M9-0002 实现确定性 Garmin MCP 采集器与三个合同 | `done` | 采集、mcp_capture/FIT、Token/预算、live context、AI提交/报告/receipt 已实现；fake MCP 14项专项通过 |
| M9-0003 冻结在线范围、完整离线测试并获 Code Validator PASS | `done` | 第十八名全新只读 Code Validator PASS；106 tests、依赖/权限/预算/证据闭包与全部静态门通过；Provider entry 为 0 |
| M9-0004 建立 candidate、一次真实只读采集并生成离线日报 | `done` | r04读取复用；r07 canary与唯一attempt4成功，summary/output/report/workflow receipt已落Candidate，幂等重放行数/ID/SHA/HTML不变 |
| M9-0005 AI 与 Data/Privacy 独立验证并回写 | `done` | 全新 AI 与 Data/Privacy Validator 均 PASS；证据、安全、数据闭包、权限、血缘、幂等和零外部动作均通过 |

## 当前检查点

- 当前 Loop：M9 已完成，状态 `completed`。
- 最近完成：Code、AI、Data/Privacy 三类全新只读 Validator 全部 PASS；公开 canary 与唯一 attempt 4 成功；Candidate SQLite 日报、open_report 和 workflow receipt 完成，确定性重放不新增行且 HTML 字节不变。
- 当前焦点：无；等待用户审核 owner-only 报告与未提交代码。
- 下一动作：无自动动作；正式 state 迁移、提交、推送及任何外部写入均须另行授权。
- 阻塞项：无。
- 已变更文件：M9 治理、wire/attempt/canary Schema、Structured Outputs 检查器、Codex attempt 状态机、日报 finalizer、回归说明和合同测试。
- 待验证项：无；真实 Garmin 与模型调用均已结束且不得重复。

## 决策与发现

- MCP JSON 保存为 candidate 私有 `mcp_capture` 证据，不冒充 Garmin HTTP raw；FIT 仍是活动原始文件。
- `auto.txt` 不增加日期、daily/weekly 或 request ID；固定历史日期只由隔离 Harness 注入。
- Token 指纹只比较“是否变化”，日志、SQLite、计划和收据均不得保存 Token 内容或摘要值。

## 任务级独立验证

- 中性交接：验证当前仓库 M9 实现是否在首次 Provider entry 前严格满足固定日期、工具、预算、
  cached-token-only、无重试、capture 血缘、幂等和零未授权外部能力。
- Validator 身份/上下文：全新、只读、未参与实现。
- 模型/推理档位：high/high。
- 命令与观察：Attempt 1 运行完整测试与对抗探针；确认测试本身通过，但实现仍允许 Token 自动刷新/401 二次请求、正式路径写入、失败后重入、0644 同内容复用、既有 FIT 未进回执、reused 缺回执 ID、MCP error 摘要丢失和实际 mcp 环境 unused-ignore。
- 结果：Attempt 1 至 Attempt 17 均 `FAIL`；Attempt 18 `PASS`。
- 未满足项与剩余风险：首次真实Provider返回及私人数据可用性仍未知；既有后台MCP进程可能独立影响Token目录，真实调用前必须只读核对并fail closed。

## 集成级独立验证

- 集成范围：一次真实 MCP 读取、candidate SQLite/capture/FIT、离线 AI 日报、正式 state/Token 不变。
- 中性交接：在线结果完成后分别交全新 AI 与 Data/Privacy Validator。
- Validator 身份/上下文：全新、只读、未参与实现。
- 模型/推理档位：high/high。
- 完整 lint/test 与回归观察：r07 Boundary Code Validator 207 tests 与全部静态门 PASS；AI Validator 和 Data/Privacy Validator 均 PASS；Candidate 重放保持 ID、SHA、HTML 和数据库行数不变。
- 结果：`PASS`——单日 Garmin MCP 只读采集、真实 AI 日报、报告、工作流回执、数据/隐私边界和零外部动作全部满足冻结合同。
- 未满足项与剩余风险：无交付阻塞；Candidate DDL 与当前建库模板存在两处历史演进差异，但权威 Schema、触发器、完整性和合同检查均通过，不影响本次结果。

## PLANS 回写清单

- [x] Exec plan 已归档到 `completed/`
- [x] Roadmap 叶子任务已更新为 `[x] completed`
- [x] 子项目和阶段状态已重新计算
- [x] `memory.md` 中的活动计划指针已删除

## 迭代日志

| 日期/上下文 | 已完成事项与证据 | 发现 | 下一动作 |
| --- | --- | --- | --- |
| 2026-08-17 / M9-0001 | M8 门禁重跑通过并本地提交 `69ed9b4`；用户批准 M9 固定单日范围 | 正式 state、Token 和 Provider 均未触碰 | 建立测试与确定性采集器；Code Validator PASS 前不进入 Provider |
| 2026-08-17 / M9-0002 | 三个 live Schema、pinned/offline stdio adapter、cached-token-only 采集器、capture/FIT原子登记、live日报context和无邮件/GTS finalizer完成；67 tests与静态门通过 | 离线 `uv run` 无法应用 tool override，因为上游声明 garminconnect 0.3.2；生产命令使用支持 `--overrides` 的 `uvx --offline`，需由 Validator 核对缓存与命令，不能为验证提前启动会话 | 冻结源码，执行首次Provider entry前Code Validator |
| 2026-08-17 / M9-0003 attempt 1 | 独立 Code Validator 返回 FAIL；未调用 Provider、未读取私人 raw/Token 内容、未修改正式 state | 固定 garminconnect 仍含 refresh/401 retry；另有 Candidate、一次授权、权限、既有 FIT、reused ID、错误摘要和 mypy 共 8 项真实缺口 | 保持计划/日期/预算不变，先加回归再修实现，交全新 Validator |
| 2026-08-17 / M9-0003 attempt 2 | 第二名独立 Code Validator 返回 FAIL；74 tests 与静态门通过，Provider/MCP/网络调用均为 0 | 固定依赖 profile/settings 各有隐藏三次循环；Candidate DB symlink 可越界；重复 activity ID 可重复 FIT；返回回执多出未声明 ID | 保持计划、日期、预算与正确预期不变，新增 4 项回归并修实现，交第三名全新 Validator |
| 2026-08-17 / M9-0003 attempt 3 | 第三名独立 Code Validator 返回 FAIL；77 tests 与静态门通过，Provider/MCP/网络调用均为 0 | raw 子目录可 symlink 越界；真实 MCP 使用 candidate guard；VO₂ fallback 产生额外 Provider 进入；AI context 不复核字节；分页回执与日报 finalizer scope 不完整 | 保持计划、日期、预算与正确预期不变，新增 6 类回归并修实现，交第四名全新 Validator |
| 2026-08-17 / M9-0003 attempt 4 | 第四名独立 Code Validator 返回 FAIL；82 tests 与静态门通过，Provider/MCP/网络调用均为 0 | profile/settings 初始化仍有2次Provider进入，使最坏13>12；日报输出目录symlink可越界 | 保持计划、日期、预算与正确预期不变，改为零Provider初始化并收紧Candidate内输出目录，交第五名全新Validator |
| 2026-08-17 / M9-0003 attempt 5 | 第五名独立 Code Validator 返回 FAIL；83 tests 与静态门通过，Provider/MCP/网络调用均为0 | 零Provider初始化导致真实Garmin实例display_name为空，RHR工具在Provider前失败；fake测试用cached-user掩盖差异 | 保持预算不变，初始化仅单次读取profile、不读settings，最坏12次，交第六名全新Validator |
| 2026-08-17 / M9-0003 attempt 6 | 第六名独立 Code Validator 返回 FAIL；83 tests 与静态门通过，Provider/MCP/网络调用均为0 | 同一活动存在多个 FIT 修订时，AI 前 activity evidence 可自行选旧 raw，未绑定本次同步回执 | 保持范围与预算不变，新增精确 raw ID 和全字节复核、双修订回归，交第七名全新 Validator |
| 2026-08-17 / M9-0003 attempt 7 | 第七名独立 Code Validator 返回 FAIL；84 tests 与静态门通过，Provider/MCP/网络调用均为0 | finalizer 可接受回执外旧 raw；成功重放不复核已登记字节；Candidate marker 缺 DB 构建来源绑定 | 保持范围与预算不变，重建并比对 context、重放验 raw、增加 DB 内 Candidate 构建收据和完整 marker 验证，交第八名全新 Validator |
| 2026-08-17 / M9-0003 attempt 8 | 第八名独立 Code Validator 返回 FAIL；86 tests 与静态门通过，Provider/MCP/网络调用均为0 | 固定 MCP 的 HRV `_ms` 字段未识别；封存后伪 raw 可注入；初始化失败少记 Provider；running receipt 可误复用 | 保持范围和预算不变，补资源字段、post-seed run provenance、保守初始化计数及 succeeded-only receipt，交第九名全新 Validator |
| 2026-08-17 / M9-0003 attempt 9 | 第九名独立 Code Validator 返回 FAIL；90 tests 与静态门通过，Provider/MCP/网络调用均为0 | Candidate 可由任意合成 source 封存；nap 和多主睡眠未 fail closed；五类健康空 JSON 仍 ready；计划漏列 Coach/Publisher 写入范围 | 不改日期、预算和预期，补正式 seed 绑定、睡眠唯一性、有效健康门和计划边界，交第十名全新 Validator |
| 2026-08-17 / M9-0003 attempt 10 | 第十名独立 Code Validator 返回 FAIL；94 tests 与静态门通过，Provider/MCP/网络调用均为0 | 同步回执先写入、run 后终态之间崩溃时，context/commit/finalizer 未核对所属 run 已 succeeded | 不改范围与预期，三层关联 skill_runs 且 fail closed，补端到端回归后交第十一名全新 Validator |
| 2026-08-17 / M9-0003 attempt 11 | 第十一名独立 Code Validator 返回 FAIL；95 tests 与静态门通过，Provider/MCP/网络调用均为0 | Candidate marker/DB 仅内部自洽，放行前未与当前正式 state 即时比对，可伪造空快照 | 不改范围与预期，放行前持正式锁重算 fingerprint/seed 并精确绑定，补回归后交第十二名全新 Validator |
| 2026-08-17 / M9-0003 attempt 12 | 第十二名独立 Code Validator 返回 FAIL；96 tests 与静态门通过，Provider/MCP/网络调用均为0 | 睡眠/健康等前置 context 已 blocked 时，Prompt 生成器仍写文件并返回0，无法证明模型前停止 | 不改范围与预期，blocked 时只写审计 context、禁止 Prompt 且返回2，补回归后交第十三名全新 Validator |
| 2026-08-17 / M9-0003 attempt 13 | 第十三名独立 Code Validator 返回 FAIL；97 tests 与静态门通过，Provider/MCP/网络调用均为0 | blocked 路径如已有旧 Prompt 则不会清晰 fail closed；90秒未包含正式快照核对和 Token 准备时间 | 不改预算数值，要求全新 Prompt path，墙钟从 collect 入口开始并在 Provider 前查剩余时间，补回归后交第十四名全新 Validator |
| 2026-08-17 / M9-0003 attempt 14 | 第十四名独立 Code Validator 返回 FAIL；98 tests 与静态门通过，Provider/MCP/网络调用均为0 | 封存后保持写连接并提交 WAL 时，immutable Candidate 读不见 post-seed 写入却仍放行 | 不改范围与预期，Provider 前拒绝非零 WAL/活动 SHM/异常 sidecar，补保持写连接回归后交第十五名全新 Validator |
| 2026-08-17 / M9-0003 attempt 15 | 第十五名独立 Code Validator 返回 FAIL；99 tests 与静态门通过，Provider/MCP/网络调用均为0 | 正式 raw/SQLite 文件的 mode/nlink 和活动 SHM 未全部 fail closed；90秒检查早于 Token 复核、清理和回执 | 不改范围、日期、预算与预期，补 owner/mode/nlink、活动 SHM 双门及15秒本地收口预留；103 tests与静态门通过后交第十六名全新 Validator |
| 2026-08-17 / M9-0003 attempt 16 | 第十六名独立 Code Validator 返回 FAIL；103 tests 与静态门通过，Provider/MCP/网络调用均为0 | 外部空闲SQLite连接未被锁区发现；Candidate根可0755；回执写入期间跨过90秒仍可成功 | 不改范围、日期、预算与预期，增加外部句柄门、Candidate根0700及回执后期限降级；106 tests与静态门通过后交第十七名全新 Validator |
| 2026-08-17 / M9-0003 attempt 17 | 第十七名独立 Code Validator 返回 FAIL；106 tests 与静态门通过，Provider/MCP/网络调用均为0 | 第一次回执写后两个期限检查之间跨线时，返回/run为blocked但最新回执仍succeeded | 将单一缺陷拆为收口预留和回执终态一致性：75秒后不再发布成功，任何回执后降级立即持久化blocked修订；完整门通过后交第十八名全新 Validator |
| 2026-08-17 / M9-0003 attempt 18 | 第十八名独立 Code Validator 返回 PASS；106 tests、依赖版本、墙钟/回执、Candidate/正式state与全部静态门通过 | 真实MCP/Provider/网络调用仍为0 | M9-0003完成；进入M9-0004全新Candidate和唯一一次获批真实读取 |
| 2026-08-17 / M9-0004 candidate r01 | 正式state复制与代码文件完成后，Candidate当前schema应用产生非零WAL，清理门返回`candidate_wal_nonempty`；Provider/MCP/网络均为0 | Candidate写入后缺少允许的显式checkpoint，不能直接清理非零sidecar | r01永久失效；增加Candidate-only checkpoint和回归，107 tests与静态门通过后交第十九名全新Validator；PASS后全新建r02 |
| 2026-08-17 / M9-0004 candidate r02 | 第十九名Validator PASS后全新构建；Candidate WAL已清零并消失，但失活SHM为32768B，旧门仍按非零统一拒绝；Provider/MCP/网络均为0 | SHM大小不能代表活动状态，不能直接删除也不能与WAL共用零字节规则 | r02永久失效；仅对无句柄/SQLite锁的owner-only单链接SHM允许Candidate清理，活动SHM保留并失败；108 tests与静态门通过后交第二十名全新Validator |
| 2026-08-17 / M9-0004 attempt 20 | 第二十名独立Code Validator返回FAIL；完整代码门通过且Provider/MCP/网络为0 | 无句柄检查释放SHM锁后才执行unlink，真实SQLite连接可在检查与删除之间进入 | 不改范围、预算或预期；持SHM排他锁到零WAL和失活SHM删除完成，释放后复核未重建；109 tests与静态门通过后交第二十一名全新Validator |
| 2026-08-17 / M9-0004 attempt 21 | 第二十一名独立Code Validator返回FAIL；109 tests与静态门通过，失活32KB SHM合成构建通过，Provider/MCP/网络为0 | 扫描后仍可出现新数据库句柄；第二个unlink失败会使零WAL已删而SHM仍在，多文件删除不具事务性 | 不改范围、预算或正确预期；停止删除旁车，只验证并保留零WAL与失活SHM，live门同步fail closed；完整门通过后交第二十二名全新Validator |
| 2026-08-17 / M9-0004 attempt 22 | 第二十二名独立Code Validator返回FAIL；109 tests与静态门通过，失活32KB SHM与live scope通过，Provider/MCP/网络为0 | checkpoint在首次旁车检查前运行，预存12392字节WAL可被静默合并并删除，未批准表进入主库 | 不改范围、预算或正确预期；每次可写打开前先做非破坏旁车门，写后再次checkpoint/复核；110 tests与静态门通过后交第二十三名全新Validator |
| 2026-08-17 / M9-0004 attempt 23 | 第二十三名独立Code Validator返回FAIL；110 tests与静态门通过，失活SHM/完整构建/live门通过，Provider/MCP/网络为0 | 写前门返回到原库connect之间仍可注入16512字节崩溃WAL；checkpoint与seal都会合并未批准表 | 不改范围、预算或正确预期；原库只immutable读取，所有写入在私有副本完成，发布前复核原库/旁车未变后原子替换；112 tests与静态门通过后交第二十四名全新Validator |
| 2026-08-17 / M9-0004 attempt 24 | 第二十四名独立Code Validator返回FAIL；112 tests与静态门、写时复制和完整构建通过，Provider/MCP/网络为0 | 发布前最终指纹复核到普通os.replace之间注入主库变化时，函数仍成功并覆盖该变化 | 不改范围、预算或正确预期；使用Darwin原子交换，新旧交换后从旧inode做后验验证，漂移则原子换回；113 tests与静态门通过后交第二十五名全新Validator |
| 2026-08-17 / M9-0004 attempt 25 | 第二十五名独立Code Validator返回FAIL；113 tests与静态门、原子交换竞态通过，Provider/MCP/网络为0 | 私有work_database父目录不名为state，当前六表Schema写入后合法0B WAL+32768B失活SHM被`candidate_sidecar_unsafe`误拒，完整build无receipt | 不改范围、预算或门；work_root内增加state子目录并复用原锁门，补当前Schema checkpoint回归；114 tests与静态门通过后交第二十六名全新Validator |
| 2026-08-17 / M9-0004 attempt 26 | 第二十六名独立Code Validator返回FAIL；114 tests与静态门、当前Schema、完整Candidate build+receipt均通过，Provider/MCP/网络为0 | 后验漂移触发换回且第二次原子交换也失败时，finally仍删除work_root，旧DB恢复证据丢失 | 不改范围、预算或正确预期；换回失败时保留work_root/旧DB并返回独立错误，Candidate判废；115 tests与静态门通过后交第二十七名全新Validator |
| 2026-08-17 / M9-0004 attempt 27 | 第二十七名独立Code Validator返回PASS；115 tests、完整合成Candidate、写时复制/换回故障、正式state指纹和全部静态门通过 | 发现3组在Validator开始前已存在的Garmin MCP后台进程，未由本任务启动或调用 | 允许进入r03构建；真实读取前只读核对既有进程与Token边界，不能停止或计作本次Provider，也不能在不确定时消耗授权 |
| 2026-08-17 / M9-0004 candidate r03 | 从正式state全新构建成功；9336 raw、119992332B、SQLite integrity=ok/FK=0/schema exact，全部目录0700/文件0600、无symlink/hardlink/.DS_Store/.gitkeep/WAL/SHM；正式state unchanged | Token目录元数据安全且既有MCP无打开Token文件句柄；尚未调用Provider | 构建时合格；随后launcher前置失败使r03永久失效，不复用 |
| 2026-08-17 / M9-0004 r03 launcher | 固定命令在导入`skills`时退出1；Candidate live_runs=0，Token无打开句柄，未启动新MCP且Provider/网络为0 | `live_sync.py`作为文件从仓库根运行时，Python只加入脚本目录，未加入`source/` | 该失败发生在在线边界前，不消耗冻结Provider读取；r03永久失效。CLI自行加入source根并补无PYTHONPATH回归，116 tests/静态门通过后交第二十八名全新Validator；PASS后全新建r04 |
| 2026-08-17 / M9-0004 attempt 28 | 第二十八名独立Code Validator返回PASS；三种cwd/无PYTHONPATH CLI、116 tests、Candidate写时复制与全部门通过 | r03无live run/capture，正式state不变；通用Garmin MCP后台进程非M9固定guard且未被调用 | 允许从正式state全新建立r04；验证通过后执行唯一一次固定live_sync |
| 2026-08-17 / M9-0004 candidate r04 | 从正式 state 全新建立；9,336 raw/119,992,332 B、SQLite 完整性/FK/六表/62 triggers、权限、链接、旁车和正式指纹门全部通过 | Token 目录无打开句柄，固定 M9 进程为 0；Provider/MCP/网络调用仍为 0 | 执行用户批准的唯一一次固定 live_sync；失败即停止且不重试 |
| 2026-08-17 / M9-0004 live read | 固定窗口成功；8 MCP/9 Provider、1 inventory、1 FIT、6 个新文件，Token unchanged、weather=0、external_actions=0；完全相同输入重放为 reused、MCP/Provider=0 | 实际数据返回未触及 11/12/10/2/2/11/90s 任一冻结上限；未调用 Gmail/Workout/Sites/cron | 停止所有 Garmin 读取；仅在 r04 内离线生成 AI 日报和报告 |
| 2026-08-17 / M9-0004 attempt 29 | 第二十九名独立Code Validator返回PASS；118 tests、Prompt/finalizer CLI、r04 SQLite/raw/live回执与正式state不变全部通过 | 离线上下文随后证明 ready：4类健康、1活动、inventory complete、已结束主睡眠 | 以 `--ignore-user-config` 执行一次 ephemeral AI，严格 Schema 验证后才允许落库/报告 |
| 2026-08-17 / M9-0004 AI attempt 1 | 以冻结 Prompt/context/Schema、`--ephemeral --ignore-user-config`执行；进程 exit 1，未生成 `ai-result.json`；Candidate 中无 daily summary/email/GTS，external_actions=0 | 调用输出未被 owner-only 保留，无法事后确认是 transport/5xx 还是 Schema/其他失败；按冻结规则不得假设为可重试 | M9-0004 标记 blocked；不重试、不改 Prompt/Schema、不再读 Garmin，等待新授权或不消耗模型调用的取证改进 |
| 2026-08-17 / M9-r04 recovery Code Validator 1 | 新调用器 20 项定向测试与 138 项完整测试、静态门均通过；未启动 Codex/MCP/Provider | SHA 核验后重新读取 Prompt/Context/Schema，存在 TOCTOU；探针可让实际输入与回执 SHA 不一致 | 不改日期、Prompt、Schema 或预期；一次读入冻结字节，Prompt 以内存字节传入，Schema 以匿名只读 FD 传入；补回归后交全新 Code Validator |
| 2026-08-17 / M9-r04 recovery Code Validator 2 | 原路径替换回归、21 项定向测试、139 项完整测试和静态门均通过；未启动 Codex/MCP/Provider | 匿名 Schema FD 仍以 `O_RDWR` 继承，恶意子进程可改写后仍让回执记录旧 SHA | 不改业务计划；写完后以 `O_RDONLY|O_NOFOLLOW` 重开并核对 inode，unlink 且关闭写 FD，只把只读 FD 交给 Codex；补写入拒绝回归后交全新 Validator |
| 2026-08-17 / M9-r04 recovery Code Validator 3 | PASS：21 项定向、139 项完整测试及全部静态门通过；原路径替换后仍使用冻结字节，Schema FD 写入返回 `EBADF/EACCES`；未启动 Codex/MCP/Provider | 无代码阻塞；Validator 使用本机离线缓存建立仓库外 Python 3.12 环境 | 允许最终只读前检；全部不变时消耗用户授权的唯一一次 Codex attempt 2 |
| 2026-08-17 / M9-r04 AI attempt 2 | 完全相同 Prompt/context/Schema 通过冻结 SHA 前检后执行；三份 0600 失败证据有效，正式 state/Token 前后相同，Candidate SQLite integrity/FK/合同通过，外部动作0 | Codex 结构化输出接口以 HTTP 400 拒绝 Schema 中的 `allOf`；未生成 `ai-result.json`。既有回执为不可改写 `unknown_non_retryable`，事件证据证明实际是 `schema_non_retryable` | M9-0004 设为 blocked；不调用第三次、不改冻结 Schema、不生成日报/报告；分类器补充 `invalid_json_schema` 回归，等待用户批准新计划修订 |
| 2026-08-17 / M9-r04 failure Code Validator 1 | 140 项测试和静态门通过；未调用外部服务 | 真实嵌套 `error.code/status/details` 未被分类器读取；原回归仅覆盖顶层 message 内嵌 JSON | 不改既有回执；解析嵌套 error 对象并补无 message 回归，交全新 Validator |
| 2026-08-17 / M9-r04 failure Data/Privacy Validator | PASS：三份失败证据 owner-only/非空/闭合；Candidate 9,342 raw、SQLite、正式 state、Token 边界和零外部动作全部通过 | 无 AI 结果，因此只认证安全失败收口，不认证 M9 完成 | 保持 M9 blocked；不运行 AI Validator |
| 2026-08-17 / M9-r04 failure Code Validator 2 | PASS：嵌套与顶层 `invalid_json_schema` 均为 `schema_non_retryable`，模型正文500不误判；23 项定向、141 项完整测试和全部静态门通过 | 既有 attempt 2 收据不可改写，仍保留运行当时的 `unknown_non_retryable` | 代码收口完成；不得第三次调用，等待用户决定是否批准 Schema 修订与新模型调用 |
| 2026-08-18 / M9-r05 Code Validator 1 | 新 wire Schema、业务 Schema 后验和冻结输入测试通过；未启动 Codex/MCP/Provider | 调用器信任调用方提供的 Prompt/Context SHA，未绑定 attempt 2 回执 | 从 attempt 2 回执读取并强制匹配冻结 SHA，补篡改回归后交全新 Validator |
| 2026-08-18 / M9-r05 Code Validator 2 | 冻结 SHA 回绑与标准代码门通过；未启动 Codex/MCP/Provider | 同步写入子进程 stdin 可因背压绕过 180 秒上限 | 改为非阻塞有界写入，将 Prompt 送达纳入同一硬截止并补大输入回归 |
| 2026-08-18 / M9-r05 Code Validator 3 | 输入背压回归与静态门通过；未启动 Codex/MCP/Provider | 进程启动、证据发布或 kill 异常仍可能越过截止且缺结构化回执 | 将启动、终止和发布纳入同一截止，所有终止错误收敛为失败回执 |
| 2026-08-18 / M9-r05 Code Validator 4 | 截止与终止回归通过；未启动 Codex/MCP/Provider | Prompt 未完整写入仍可成功；成功回执发布跨线时可能残留错误终态 | 要求全部 Prompt 字节写入并关闭写端；成功终态采用失败优先发布 |
| 2026-08-18 / M9-r05 Code Validator 5 | wire Schema、冻结 FD、截止和大输入门通过；未启动 Codex/MCP/Provider | wait 异常、attempt 历史闭包和成功回执异常安全仍有缺口；子进程阅读确认不可由 Codex CLI 提供 | 按冻结合同以“全部字节写入受信任 stdin 并关闭写端”定义送达；封闭 attempt 历史并补异常回归 |
| 2026-08-18 / M9-r05 Code Validator 6 | 154 项测试和全部静态门通过；未启动 Codex/MCP/Provider | 未核对 attempt 2 的 events/stderr 字节与回执；fallback 回执失败时可留下已发布 AI 结果 | 先补失败回归；校验两份旧证据的大小/SHA，并确保 fallback 回执安全前结果只存在于隐藏临时文件 |
| 2026-08-18 / M9-r05 recovery after Validator 6 | 39 项定向、157 项完整测试、Ruff、format、mypy、只读编译、JSON/Schema 与 diff 门通过；缓存已清理；未启动 Codex/MCP/Provider | 两项阻塞均已由回归覆盖，attempt 2 实际 events/stderr 的大小与 SHA 也已只读核对一致 | 交第七名全新只读 Code Validator；PASS 前不得执行 attempt 3 |
| 2026-08-18 / M9-r05 Code Validator 7 | attempt 2 实际三份证据闭合，39 项定向、157 项完整测试及全部静态门通过；未启动 Codex/MCP/Provider | 结果未再次通过 wire Schema；成功回执 post-replace 异常可残留成功状态；终止等待可越过硬截止 | 不改冻结计划，补三项失败回归；双 Schema 后验、成功回执撤销和有界异步 reap 后交第八名全新 Validator |
| 2026-08-18 / M9-r05 recovery after Validator 7 | 42 项定向、160 项完整测试、Ruff、format、mypy、只读编译、全部 JSON/Schema 与 diff 门通过；未启动 Codex/MCP/Provider | 三项阻塞均已由对抗回归覆盖，业务 Schema 与 frozen input 未改变 | 交第八名全新只读 Code Validator；PASS 前不得执行 attempt 3 |
| 2026-08-18 / M9-r05 Code Validator 8 | r04 attempt 2 三份真实证据、双 Schema、42 项定向、160 项完整测试及全部静态门通过；未启动 Codex/MCP/Provider | 空 capture 的回执大小仍记录为0；失败回执同步写入可突破硬截止 | 修正占位后的实际大小；以有界原子写线程覆盖全部回执路径，补截止后无延迟写入回归后交第九名全新 Validator |
| 2026-08-18 / M9-r05 recovery after Validator 8 | 43 项定向、161 项完整测试、Ruff、format、mypy、只读编译、全部 JSON/Schema 与 diff 门通过；未启动 Codex/MCP/Provider | 两项阻塞均已由大小/SHA闭包和延迟发布对抗回归覆盖 | 交第九名全新只读 Code Validator；PASS 前不得执行 attempt 3 |
| 2026-08-18 / M9-r05 Code Validator 9 | 43 项定向、161 项完整测试和全部静态门通过，r04 attempt 2 与冻结输入闭合；未启动 Codex/MCP/Provider | 成功回执的后台替换可在调用器已超时返回后晚到，覆盖失败终态 | 为有界写入增加取消信号和 post-replace/post-fsync 回滚；成功回执以原 fallback 字节恢复，补直接延迟 replace 回归后交第十名全新 Validator |
| 2026-08-18 / M9-r05 recovery after Validator 9 | 44 项定向、162 项完整测试、Ruff、format、mypy、只读编译、全部 JSON/Schema 与 diff 门通过；未启动 Codex/MCP/Provider | 晚到替换回归证明返回后最终回执仍为 failed 且无 ai-result；冻结业务输入未改变 | 交第十名全新只读 Code Validator；PASS 前不得执行 attempt 3 |
| 2026-08-18 / M9-r05 Code Validator 10 | 44 项定向、162 项完整测试及全部静态门通过；未启动 Codex/MCP/Provider，attempt 3 未消耗 | 同步 capture 持久化在文件系统阻塞时可越过 180 秒；异步失败优先发布若在替换后阻塞，则返回时可能尚无可靠 fallback。两项要求在无限阻塞 I/O 假设下不能同时无条件成立 | M9-0004 标记 blocked；保留全部失败证据，停止实现与验证，向用户请求最小合同修订 |
| 2026-08-18 / M9-r05 plan conflict | 未修改日期、数据、Prompt、Context、Schema、安全规则或正确预期；未调用任何外部服务 | 当前唯一冲突限于 Codex 180 秒截止与本地证据持久化语义 | 用户未批准修订前不得执行 attempt 3；r05 任何旧 PASS 不可释放后续依赖 |
| 2026-08-18 / M9-r06 approval | 用户确认 180 秒只约束 Codex 子进程，并要求清理多轮修复冗余、保留既有测试、增加回归测试和 Block 说明 | 业务日期、数据、Prompt、Context、两个 Schema、安全规则与零外部动作不变 | 冻结状态机/威胁矩阵，先交 Design Validator；PASS 前不改调用器、不执行 attempt 3 |
| 2026-08-18 / M9-r06 Design Validator 1 | 只读审查状态机、信任边界、故障矩阵和回归映射；未修改文件、未调用外部服务 | FAIL：终止时点、目录锁/fsync线性点、终态白名单与intent绑定、I/O阶段、final重放、下游绑定及44场景映射共7项未决 | 一次性补齐七项设计合同，再交另一名全新只读 Design Validator；PASS 前不改调用器 |
| 2026-08-18 / M9-r06 Design Validator 2 | 全新只读审查返回 PASS；单写者目录锁、pending→final 原子发布、T01～T16、44 场景保留映射和下游信任合同均已决策完整 | 无设计阻塞；未修改文件、未调用外部服务 | 允许按冻结设计重构实现；不得扩大威胁模型或提前执行 attempt 3 |
| 2026-08-18 / M9-r06 implementation | 调用器拆为 18 行薄入口与单写者状态模块；删除 daemon writer、取消/rollback、异步启动/reap、finalization reserve；下游不再接受任意 AI JSON；新增 intent Schema、Block 说明与状态机回归 | 170 项 Code 测试、Ruff、format 和 mypy 自检通过；尚未由独立 Code Validator 认证 | 冻结实现，交一名全新只读 Code Validator 一次性检查完整矩阵；PASS 前不执行 attempt 3 |
| 2026-08-18 / M9-r06 Code Validator 1 | 全新只读 Validator 按冻结 T01～T16 一次性检查；170 tests 与全部静态门通过，r04 仍只有 attempt 2，外部调用为0 | FAIL：进程组晚到子进程可改 final；本地 fsync 误计模型超时；业务 Schema 未回绑 attempt 2；正式 state/Token 漂移门缺失；final 未强制 attempt=3；有限 I/O 未统一收敛且矩阵回归不足 | 保持计划不变，将六类缺陷合并为单一修正批次；完成全部回归和实现后只交一名全新最终 Code Validator |
| 2026-08-18 / M9-r06 consolidated recovery | 六类缺陷一次修正：完整进程组静默、模型 elapsed 线性点、双 Schema 回绑、正式 provenance/Token 稳定前检、attempt=3 强制与有限 I/O blocked 收敛；新增对应回归与 Block 说明 | 179 tests、Ruff、format、mypy、AST、21 JSON/Schema 与 diff 门自检通过；无真实 Codex/MCP/Provider 调用，attempt 3 未消耗 | 冻结源码，交一名全新最终 Code Validator；不得再逐轮扩大冻结矩阵 |
| 2026-08-18 / M9-r06 final Code Validator + recovery | 全新最终 Validator 仅发现 T06/T12 仍以“成功发送 SIGKILL”代替“观察进程组消失”；其余冻结矩阵和静态门通过 | 调用器现等待并确认整个进程组消失；能终止的后代在发布前停止，始终存在或状态不明时保持 pending；180 tests与全部静态门自检通过，外部调用0 | 冻结源码，交最后一名全新只读 Code Validator；PASS 前不得执行 attempt 3 |
| 2026-08-18 / M9-r06 final Code Validator PASS | 全新只读 Validator 两次完整运行均为180 passed，晚到后代20/20；Ruff、format、mypy、AST、21 Schema、隐私/布局/diff与T01～T16全部通过 | r04仅有attempt 2且失败证据闭合；attempt 3/pending/attempt 4不存在；未启动Codex/MCP/Provider或网络 | 允许进行正式前检；全部边界不变时执行唯一attempt 3 |
| 2026-08-18 / M9-r06 AI attempt 3 | r04、冻结 Prompt/Context/双 Schema、正式 state 与 Token 前检全部通过后执行唯一 Codex 调用；无 Garmin/Gmail/Workout/Sites | Codex 返回 HTTP 400 `invalid_json_schema`：`schema_version` 子 Schema 只有 `const`、缺少显式 `type`；终态为 failed，无 AI result、pending 或 attempt 4 | 按冻结计划停止；不提交日报、报告或 workflow receipt，不执行第四次调用，M9-0004 设为 blocked |
| 2026-08-18 / M9-r06 failure Data/Privacy Validator | PASS：attempt 2保持；attempt 3 四文件 owner-only/非空/SHA与Schema闭合；Candidate 9,342 raw/120,646,692B、SQLite、正式 state与Token边界通过 | 仅认证安全失败，不认证M9完成；provider_calls=0、external_actions=0，无日报/报告/email/GTS | 保持M9 blocked，等待用户决定是否批准新的 Schema 与模型调用修订 |
| 2026-08-18 / M9-r07 implementation | 新增只补四个 type 的 wire v2、递归官方子集 allowlist、公开 owner-only canary、attempt intent/receipt v2 与 `2失败→3失败→canary成功→4成功` 下游链；wire v1 SHA 保持 `b223f5b5…` | 203 tests、Ruff、format、mypy、AST、25 Schema、AI布局、Markdown、隐私与diff门自检通过；Codex/Garmin/Gmail/Workout/Sites调用均为0 | 冻结源码，交唯一一名全新只读 Code Validator；PASS 前不执行 canary 或 attempt 4 |
| 2026-08-18 / M9-r07 Code Validator 1 | 203 tests与全部静态门通过；wire v1、attempt 2/3闭合且无外部调用 | FAIL：未引用/嵌套 `$defs`、重复引用深度与重复 `required` 可绕过检查；canary root 可指向 Candidate/state | 按冻结范围合并一次修正：全定义遍历、逐引用深度、required唯一性、专用仓库外canary根与对应回归；完成后只交一名全新最终 Code Validator，不执行模型 |
| 2026-08-18 / M9-r07 consolidated recovery | 全定义遍历、逐引用深度、required唯一性与专用canary根已实现；新增Candidate/state/未声明文件拒绝回归 | 206 tests、Ruff、format、mypy、AST、25 Schema、布局、隐私与diff门通过；外部调用0 | 冻结源码，交一名全新最终 Code Validator；PASS 前不执行 canary 或 attempt 4 |
| 2026-08-18 / M9-r07 final Code Validator | 206 tests与全部门通过；attempt历史和Candidate闭包正常 | FAIL：下游未复用canary专用根门；计划允许范围漏列已修改的Skills索引 | 将根门抽为生产/消费共享模块，正向夹具移出Candidate、增加复制品拒绝回归，并显式补齐计划写入范围；不改业务目标或模型输入 |
| 2026-08-18 / M9-r07 definitive recovery | canary生成端、attempt4与finalizer现共用同一仓库外专用根门；Candidate复制品拒绝，测试夹具移出Candidate，计划写入范围闭合 | 207 tests、Ruff、format、mypy、AST、25 Schema、隐私/布局/diff门通过；wire v1与attempt2/3未改，外部调用0 | 冻结源码，交全新最终 Code Validator；PASS 前不执行 canary 或 attempt4 |
| 2026-08-18 / M9-r07 definitive Code Validator | 207 tests与全部门通过；共享门已覆盖生产与消费 | FAIL：专用根仍可嵌套在temp中的state、tokens或private-context祖先下 | 收紧为系统临时目录直接子级；增加三类嵌套拒绝回归，不改Schema、Prompt、Context、attempt历史或业务规则 |
| 2026-08-18 / M9-r07 boundary Code Validator | PASS：207 tests、Ruff/format/mypy/AST/25 Schema/Markdown/privacy/diff与专用temp直接子级边界全部通过；r04 attempt2/3闭合，无attempt4/5 | 无代码阻塞；未启动任何外部调用 | 允许执行一次公开合成canary；失败则停止，成功才允许唯一私人attempt4 |
| 2026-08-18 / M9-r07 schema canary | 公开合成数据、wire v2、同一Codex 0.147.0、ephemeral/ignore-user-config/read-only执行成功；provider_calls=0、external_actions=0 | canary证据位于仓库外专用owner-only目录，不挂载Candidate | 只读复核r04/正式state/Token/冻结SHA后执行唯一attempt4 |
| 2026-08-18 / M9-r07 AI attempt 4 | 唯一私人Codex调用成功；双Schema、证据、安全与正式state/Token稳定门通过；provider_calls=0、external_actions=0，无pending/attempt5 | 不再允许任何模型重试；Garmin/Gmail/Workout/Sites/cron调用均为0 | 运行确定性提交、open_report与workflow receipt，并重放验证幂等 |
| 2026-08-18 / M9-r07 downstream | Candidate新增summary output 12、report output 13、receipt output 14；SQLite integrity/FK/合同通过；重放前后runs=6、outputs=14、actions=0，ID/SHA/HTML字节完全不变 | 报告仅在Candidate，0600文件/0700目录；正式state未生成backup/recovery目录 | 交全新AI与Data/Privacy Validator；全部PASS后完成M9 |
| 2026-08-18 / M9-r07 AI Validator | PASS：日报日期边界、原始证据引用、实测数值、安全等级、恢复建议、不编造、attempt链与报告/SQLite一致性全部通过 | VO2 Max与体重缺失未逐项展开，但未被推断或伪造，不构成阻塞 | 接受AI语义验收结果 |
| 2026-08-18 / M9-r07 Data/Privacy Validator | PASS：Candidate六表/62 triggers/integrity/FK、9,342 raw与120,646,692B双向闭包、权限、血缘、重放、正式state/Token不变及零外部动作全部通过 | Candidate DDL与当前模板有两处历史演进差异，权威合同检查通过 | 接受数据/隐私验收结果 |
| 2026-08-18 / M9 completion | 三类独立Validator全部PASS；M9-0001..0005完成，未提交、未推送、未迁移正式state、未启用任何外部写入 | r04 Candidate和owner-only报告保留供用户审核 | 归档计划并等待用户决定后续动作 |
