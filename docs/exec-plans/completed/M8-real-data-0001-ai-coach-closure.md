# 执行计划：M8 真实私人数据离线 AI 教练闭环

- 状态：`completed`
- 负责人：主协调 Agent
- Roadmap ID：`M8`
- 阶段/子项目：`M8/real-data-ai-closure`
- Batch ID：`serial-m8`
- 返工来源：`无`
- 开始日期：2026-08-16
- 最后更新：2026-08-17

## 目标与验收标准

在仓库外 candidate 中，以真实 Garmin raw、私人 goal 和 SQLite 副本运行真正由 AI 生成的日报、周报与课表。

固定窗口：日报 `2026-08-12`；周报 `2026-08-09`，先生成 `2026-08-03..09` 七份日报；当前槽位 `2026-08-16` 必须因数据不足返回 `blocked`。

允许 Codex 接收资源专用健康总览、活动 30 秒序列、按需活动片段和 goal；不发送 GPS、原始文件字节、凭据或完整历史日报正文。Garmin、Gmail、Sites 调用数为零，正式 `source/state` 前后摘要不变。

硬性规则：冻结计划后不得为获得 PASS 修改日期、输入范围、Schema、阈值、测试预期、失败语义或验证范围；不得删除测试、隐藏解析错误、用合成数据替换指定真实数据、把固定脚本输出冒充 AI 输出或将 `blocked` 改成成功。若计划本身需要修订，必须停止、保留证据、获得用户批准、建立修订版本并全量重验。

## 范围与非目标

范围包括真实健康/活动解析、健康专用总览、活动 30 秒序列、活动片段细读、AI JSON 生成、确定性校验、candidate SQLite 落库、HTML/JSON/邮件信封/GTS 合同、幂等和三类独立验证。

非目标：修改正式 state、Garmin/Gmail/Sites、发送邮件、创建/删除/排期 Workout、安装 cron、在线补数、正式数据库迁移、提交或推送 Git。

## 适用规则与参考资料

- 已批准规则：A-001、A-004、A-008、A-009，以及根 `AGENTS.md` 的独立 Validator 和隐私规则。
- 运行依据：`source/AGENTS.md`、`source/skills/README.md`、M7 completed plan。

## 依赖与隔离

- 显式依赖：M7 completed；正式 state 中已登记的 9,336 个 raw 文件；本机可用 Python 3.12 与现有离线依赖。
- 任务分支：不创建；按用户授权在当前本地工作树串行修改。
- 允许写入：`source/skills/`、`source/tests/code/`、`source/tests/ai/`、`source/skills/_shared/schemas/`、本计划、M8 Roadmap 和治理记录。
- 禁止写入：`source/state/**`、`source/goal.md`、凭据、`data-backup/`、任何外部服务和用户级配置。
- Candidate：仓库外 `0700`；数据库和文件 `0600`；只复制 DB `raw_files.relative_path` 白名单，不复制 `.DS_Store`、`.gitkeep`、凭据，不用硬链接或符号链接。

## 功能与测试映射

| 功能 | Feature slug | 测试目录 | 必须满足的行为 |
| --- | --- | --- | --- |
| 健康专用总览 | health-overview | `source/tests/code/unit` | 不混合语义字段，睡眠边界和单位正确 |
| 活动总览/片段 | activity-evidence | `source/tests/code/unit`, `contract` | 30 秒序列、无 GPS、细读预算和证据绑定 |
| 真实 AI 提交 | ai-coaching-bridge | `source/tests/code/contract`, `integration` | 严格 JSON、证据引用、数值不可伪造、安全门不可降低 |
| Candidate 闭环 | real-candidate-workflow | `source/tests/code/integration`, `source/tests/ai` | 真实日期顺序、报告、信封、GTS 合同和幂等 |

## 工具采用情况

- Python 3.12、SQLite、FIT/GPX/TCX 解析器、Codex `exec`。
- Ruff、format、mypy、pytest、JSON Schema、compile、隐私/布局/diff 门。
- AI 真实测试使用隔离 candidate、`--ephemeral`、`--ignore-user-config` 和测试专用 output schema；公开 `auto.txt` 仍无日期、模式和 request ID。

## 工作分解

| 步骤 | 状态 | 证据 |
| --- | --- | --- |
| M8-0001 冻结基线、Roadmap 与硬性反绿灯规则 | `completed` | 当前 HEAD `d08a893`；计划、固定窗口和禁止反绿灯规则已冻结 |
| M8-0002 修复真实 weather/sleep/health/activity 解析和片段接口 | `completed` | 真实 weather 381/381 识别为 `activity_weather`+JSON；真实嵌套 sleep 解析为 complete；FIT/GPX/TCX 30 秒序列与 5 秒细读通过 |
| M8-0003 实现真正 AI 日报/周报提交与路径无关幂等 | `completed` | 真实 Codex 日报 8/3..9、8/12 与周报 8/9 成功；周报修复两次严格拒绝后按合同重试成功；同输入重跑复用既有 output |
| M8-0004 建 candidate，运行固定真实日期并生成私有产物 | `completed` | r38 `/private/tmp/trainlab-m8-candidate-r38.YwwZl6` 从正式 state 全新建立；9336 raw/119992332 bytes 闭合；四套报告、两份 prepared 邮件、GTS prepared 合同和 8/16 blocked 产物完成 |
| M8-0005 Code、AI、数据/隐私独立验证 | `completed` | r38 Code、AI、Data/Privacy 三名全新只读 Validator 均 `PASS`；provider/external actions 均为 0 |

## 当前检查点

- 当前 Loop：M8-0005
- 最近完成：M8-0001 至 M8-0005 已在隔离 candidate 中完成；正式 state 未写入、未调用 Garmin/Gmail/Sites。
- 当前焦点：r31/r32/r33/r34/r35/r36/r37 失败证据均保留且不转为 PASS；r38 已按顺序完成 `weekly-fitness-summary → weekly AI`，并完成报告、邮件信封、GTS prepared、工作流回执和重放。
- 下一动作：无。M8 已完成；任何真实 Provider/Gmail/Sites 写入、cron 启用或正式状态切换都需要后续单独授权。
- 已知真实运行证据：首个周报模型调用出现一次 503，重试成功；两次课程合同拒绝均因模型输出违反既有合同，修复提示后才成功，未放宽 Schema。
- 待验证项：候选完整门禁、AI 语义不编造、正式 state 摘要/权限/隐私不变。

## 设计合同

1. 健康解析只输出资源专用字段：sleep、rhr、hrv、heart_rates、max_metrics、weigh_ins；历史趋势由最多 14 份结构化日报生成压缩表，AI 不读取完整历史正文。
2. 活动首层输出完整圈段和固定 30 秒序列，移除 GPS；AI 可按 `activity_inventory_id + start/end + 1|5 秒 + reason_code` 细读昨日活动片段。
3. 每份日报细读最多 5 次、单次最多 10 分钟、累计最多 30 分钟；重复请求复用，越界 fail closed。
4. AI 输出由确定性 Host 校验并写 SQLite；AI 不直接写库，不得降低确定性安全结果。固定 Python 生成器不能伪装成 AI 回退。
5. 真实流程顺序为：日报 `2026-08-12`；日报 `2026-08-03..09`；周报 `2026-08-09`；相同输入重跑；当前缺数据槽位阻断。
6. 报告默认 `open_report`，不可用才回退 `fixed_email`；邮件和 GTS 始终为 prepared，不发送、不写外部系统。

## 任务级独立验证

- 中性交接：完成对应代码和测试后，仅提供冻结计划、验收标准、当前工作树和 candidate 路径。
- Validator：全新、只读、未参与实现；代码任务至少 `medium/medium`，数据和隐私任务 `high/high`。
- 结果：`PASS`。Code Validator：53 tests；Ruff、format、mypy、compile、15 schemas、candidate state/artifact 门全部通过；活动片段锁竞争与预算、receipt、报告嵌套稳定渲染和跨目录幂等均通过。

## 集成级独立验证

- 集成范围：真实解析、AI 输出、candidate SQLite、报告、幂等、正式 state 不变和零外部调用。
- Validator：全新高风险只读 Agent。
- 结果：`PASS`。AI Validator：8 份日报、1 份周报、8/16 模型前 blocked、证据/课程/报告/邮件/GTS 语义和重放均通过。

## PLANS 回写清单

- [x] Exec plan 归档到 `completed/`
- [x] M8 Roadmap 叶子任务更新为 `[x] completed`
- [x] 阶段状态重新计算
- [x] `memory.md` 删除活动计划指针

## 迭代日志

| 日期/上下文 | 已完成事项与证据 | 发现 | 下一动作 |
| --- | --- | --- | --- |
| 2026-08-16 / M8-0001 | 用户批准 M8；固定真实日期、输入范围和反绿灯规则 | 正式 state 仍需 candidate 升级；真实解析需修复 | 完成 Roadmap/治理回写，开始 M8-0002 |
| 2026-08-16 / M8-0002 | 修复资源专用 health parser、Garmin 嵌套 sleep、weather 后缀/资源识别、活动 30 秒序列与 1/5 秒片段预算；`pytest source/tests/code` 34 passed | 初次真实周报模型输出缺失 climbing/rest 合同字段，按现有合同拒绝 | 仅补充提示约束并在同一固定窗口重试，不改变 Schema 或预期 |
| 2026-08-16 / M8-0003 | 真实 Codex 日报 8/3..9、8/12 与周报 8/9 均经 response schema、证据 SHA、日期和课程安全门后落库；同输入周报/日报重跑均 `reused=true` | 首次周报调用收到 503；两次确定性课程拒绝均保留在 `/tmp/m8-r18-weekly-*` 日志 | 继续 candidate 报告、邮件信封、GTS 合同和 blocked 槽位验证 |
| 2026-08-16 / M8-0004 | candidate r18 9336 raw 全字节闭包；报告 HTML/JSON 0600；邮件与 GTS 均 prepared、provider/external actions 0；`2026-08-16` 返回双缺失错误并未调用模型 | 正式 state 仍保留用户删除后的无 backups/recovery-quarantine 形态，未重建 | 冻结源码/candidate，进入三类独立 Validator |
| 2026-08-16 / M8-0005-r27 | 修复 blocked context 持久化、daily 顶层 stop_conditions Schema、秒到分钟证据换算、报告标题落库和 Gmail 源输出血缘；代码测试 40 passed、Ruff/format/mypy/compile/schema 全绿；r27 完成 8 份真实日报、1 份真实周报、两套模板、两份邮件信封和 GTS prepared 合同；同输入重跑计数不变，正式 state manifest 前后相同 | 代码 Validator 发现证据数值未按引用 raw 限定、跨 workflow 片段缓存可绕过预算、嵌套课表 Schema 失败未落库、GTS 幂等键过窄和导入门失败 | 停止认证，修复实现并建立 r28 candidate；不改变固定窗口、数据、Schema 或失败预期 |
| 2026-08-16 / M8-0005-r28 | 证据数值现在只从对应 `evidence_ref` raw 对象收窄；daily 校验 `recent_trend_sha256`、weekly 校验 `goal_sha256`；片段缓存键绑定 workflow；嵌套课表 Schema 失败写入 blocked run；GTS 幂等键绑定完整课程项；新增回归后 `pytest source/tests/code` 42 passed，Ruff/format/mypy 全绿；r28 重新复制 9336 raw 并通过 `verify_state`，重放日报/周报复用，GTS 重放字节一致，外部调用 0 | r27 验证结果因源码漂移作废；r28 等待三名全新只读 Validator | 保持冻结，完成代码、AI 语义和数据/隐私独立复验 |
| 2026-08-16 / M8-0005-r29 | 发现片段接口仍信任调用者传入的 workflow key，可用伪造 key 绕过每日预算；将 workflow 绑定为 `daily:<activity_date+1>`，并修复活动段导入格式；r29 验证期间发现报告 HTML 仍受 JSON 键顺序影响 | r29 不能认证，源码继续冻结后建立干净 candidate | 修复渲染顺序并从正式 state 重新建立 r30，重新运行全部真实 AI 输入与离线输出 |
| 2026-08-16 / M8-0005-r30 | `body_html` 按稳定键序渲染；从正式 state 重新建立 r30，9336 raw/119992332 bytes，8+1 真实 AI 输出按固定窗口落库，报告 open/fixed 四套、邮件 2 份、GTS prepared 1 份、8/16 blocked；同路径重放报告 HTML 字节一致、日报/周报/GTS/邮件复用且计数不变；verify_state integrity/FK/schema 通过，外部调用 0 | 代码 Validator 发现嵌套 JSON 键顺序和片段预算并发问题，r30 不能认证 | 修复实现并建立 r31，不沿用 r30 证据 |
| 2026-08-16 / M8-0005-r31-fix | 代码 Validator 发现嵌套 JSON 键顺序仍会改变 HTML，并发现片段预算检查存在并发 TOCTOU；已将报告嵌套 JSON 改为递归稳定排序，并让片段读取在预算检查、证据读取和运行预留期间持有 workflow lock；`pytest source/tests/code` 43 passed，Ruff/format/mypy 全绿 | r30 验证作废；必须从正式 state 重新建立候选并由三名全新 Validator 重验，不能沿用 r30 证据 | 建立 r31，重跑固定真实窗口和全部独立验证 |
| 2026-08-16 / M8-0005-r31 | 从正式 state 重新建立 `/private/tmp/trainlab-m8-candidate-r31.8U4lRN`；固定窗口 8+1 真实 AI 提交、四套当前模板报告、两份 prepared 邮件信封、GTS prepared、8/16 blocked；报告/GTS/邮件同输入重放均复用且 HTML 字节一致；candidate 9336 raw/119992332 bytes、integrity/FK/schema 通过，外部调用 0 | 等待三名全新只读 Validator；正式 state 未写入 | 保持源码与 r31 冻结，完成最终代码、AI、数据/隐私复验 |
| 2026-08-16 / M8-0005-r31-data-fail | 数据/隐私 Validator 对 r31 判定 `FAIL`：候选构建器使用普通 `mode=ro` 读取正式 SQLite，正式 `trainlab.db-shm` 的 mtime/ctime 在候选创建后变化；真实输出根还留下 0 字节、0644 的 `reports/replay-result.json`。raw 闭包、SQLite、产物血缘和外部零调用均通过 | 违反“正式 source/state 不写入/不触碰”和 owner-only 产物门禁；r31 不可认证。已修复构建器为 `mode=ro&immutable=1`，但不能抹去 r31 已有的正式 sidecar 触碰证据 | M8 停在 `blocked`，等待用户批准新的修订计划后再重建候选；不沿用 r31 PASS |
| 2026-08-16 / M8-0005-r32-start | 用户批准继续当前 M8 active plan 的 `r32 blocker-recovery batch`；固定窗口、Schema、阈值、输入边界、零外部调用和失败语义保持不变 | r31 的普通 `mode=ro` 读取曾触碰正式 SHM，immutable 模式还必须拒绝非零 WAL；正式 lock/WAL 指纹和产物根完整性需要在同一批次回归 | 先完成代码回归与只读快照门，再从正式 state 全新建立 r32；三名全新 Validator 全部 PASS 前保持 validating/blocked |
| 2026-08-16 / M8-0005-r32-code | 新增正式 state 只读锁、零 WAL 门、DB/WAL/SHM/lock/raw 全树 before/after 指纹；candidate 非零 sidecar 不再删除；新增显式 owner-only 产物 verifier，并将 AI context/报告文件改为 fsync 后原子写入；代码测试 50 passed，Ruff/format/mypy 全绿 | 尚未重新建立真实 candidate；当前旧 r32 candidate 在最新原子写入修复前建立，不得复用 | 重新跑代码门后，建立新的 r32 candidate 并从固定窗口执行全新 AI 调用 |
| 2026-08-16 / M8-0005-r32-ai-fail | r32 全新 candidate 完成 8/12、8/3..8/9 的真实 Codex 调用尝试；8/7 出现一次确定性 `ai_metric_not_in_evidence`，且批量执行器重复写入同名结果文件，导致 candidate 证据不可作为稳定认证快照 | r32 candidate 永久作废；保留其失败日志、blocked run 和先前成功 run，不复用数据库、AI 输出或报告；正式 state 未写入 | 在同一冻结范围内建立全新 r33；驱动器对已存在路径 fail closed，逐日顺序运行并在每步确认结果不可覆盖 |
| 2026-08-16 / M8-0005-r33-gts-driver-fail | r33 完成 8/12、8/3..8/9 七份日报及周报 AI 提交；生成 GTS 时驱动器使用原始模型课表，未使用提交脚本归一化后的 `training_plan` 输出，导致 `garmin_source_unbound`/`garmin_contract_invalid` blocked 合同 | r33 candidate 永久作废；不删除 blocked 记录、不复用其 AI/DB；该错误不涉及业务计划、Schema 或安全阈值 | 建立全新 r34；从 candidate SQLite 已提交的 `training_plan` 读取 GTS 输入，并重新执行全部真实 AI 窗口 |
| 2026-08-16 / M8-0005-r34-recovery | r34 从正式 state 在既有 lock 下以 immutable 零 WAL 快照建立；正式 fingerprint `7cc9f67d...` 前后相同；9336 raw/119992332 bytes 闭合。真实 Codex 新生成 8 份日报与 1 份周报；8/16 在模型调用前以 `daily_review_health_missing`/`daily_sleep_evidence_missing` blocked；GTS 读取已落库 `training_plan` 后 prepared 4 actions；邮件 2 份 prepared；四套报告已渲染；AI、报告、邮件、GTS 同输入重放复用，provider/external actions=0；artifact verifier 89 files PASS，candidate verify_state PASS | r34 尚未经过三名独立 Validator；r31 的 SHM 触碰失败证据仍保留且不被覆盖 | 冻结 r34，交 Code、AI、Data/Privacy 三名全新只读 Validator；全部 PASS 后才可完成 M8-0004/0005 |
| 2026-08-16 / M8-0005-r34-code-fail | Code Validator 复验 50 tests、Ruff/format/mypy、SQLite、artifact、嵌套渲染和正式指纹均通过；但并发活动片段遇到 `state_lock_unavailable` 时异常未转为稳定 blocked run，5 个竞争请求没有写入 SQLite | r34 candidate 永久失效；AI 与 Data/Privacy 的 r34 PASS 不继承，旧候选和产物不复用 | 修复 `activity_segment` 锁竞争记录与回归测试；从正式 state 全新建立 r35，完整重跑固定窗口和三类独立验证 |
| 2026-08-16 / M8-0005-r35-start | 将 `activity_segment` 的正式锁竞争转换为稳定 `blocked/state_lock_unavailable` 运行并写入 candidate SQLite，补充并发回归；Ruff、format、mypy 和 `pytest tests/code` 均通过（51 passed） | r34 的锁竞争失败证据不继承；r35 必须重新从正式 state 建立并重新执行全部真实 AI、报告、邮件/GTS prepared、重放和 8/16 blocked 门禁 | 清理测试缓存后，在正式 lock/WAL 零门下建立新的 r35 candidate；完成后冻结源码与产物并交三名全新 Validator |
| 2026-08-16 / M8-0005-r35-ai-fail | r35 全新 candidate 完成 8/12 与 8/3..8/8 日报；2026-08-09 模型输出未通过既有证据绑定，`commit_ai_result` 持久化 `ai_metric_not_in_evidence` blocked；周报检测到精确日报缺失并在模型输出后按合同 blocked | r35 永久失效；不复用其数据库、AI 输出或 blocked 结果；该失败不是通过放宽证据合同解决，固定 prompt/Schema/日期保持不变 | 从正式 state 全新建立 r36，重新执行 8/12、8/3..8/9 日报和后续周报/报告/重放/8/16 blocked，再交三名全新 Validator |
| 2026-08-16 / M8-0005-r36 | 从正式 state 在既有 lock 下以 immutable 零 WAL 快照建立 r36；formal fingerprint `7cc9f67d...` before/after/current 完全一致；9336 raw/119992332 bytes 闭合。8 份日报和周报由全新 Codex 会话生成并落库，8/16 在模型前记录 `daily_review_health_missing` 与 `daily_sleep_evidence_missing`；GTS 3 actions prepared、邮件 2 份 prepared、报告 open/fixed 四套；重放复用原 output/HTML，candidate integrity/FK/schema/trigger 和 artifact 85 files 通过，provider/external actions 0 | r36 尚未经过三类独立 Validator；正式 state 未写入 | 冻结源码、r36 candidate、产物和 manifest，分别交 Code、AI、Data/Privacy 全新只读 Validator |
| 2026-08-16 / M8-0005-r36-validators | Code Validator `FAIL`：`activity_segment.py` 的 Ruff 导入门、workflow receipt artifact 多余 `output_id`、render replay 回执缺少首次的 `source_output_id/source_output_sha256`；AI Validator `PASS`、Data/Privacy Validator `PASS` 不继承。r36 candidate 和产物完整保留，正式 state 未写入、零外部调用 | r36 永久失效；不得把两个 PASS 与 Code FAIL 拼成阶段 PASS | 修复冻结范围内的三项问题，新增 receipt writer 与 replay 回归；代码门全绿后从正式 state 全新建立 r37 |
| 2026-08-16 / M8-0005-r37-fix | 修复 `render_report.persist_outputs` replay 返回完整 source lineage；新增 `write_workflow_receipt.py`，严格拒绝内部 `output_id` 并原子写 owner-only receipt；新增 replay/receipt 回归，当前 `pytest tests/code` 53 passed、Ruff check/format、mypy 通过 | r37 执行中发现周流程尚未先行运行 `weekly-fitness-summary`，为保持流程合同不掩盖顺序偏差，r37 在最终验收前作废；其 candidate、AI 输出和产物均不复用 | 清理缓存、冻结当前源码，从正式 state 全新建立 r38；日报完成后先运行 `weekly-fitness-summary`，再生成周报、报告、信封和回执 |
| 2026-08-17 / M8-0005-r38 | 从正式 state 在既有 lock 下以 immutable 零 WAL 快照建立 `/private/tmp/trainlab-m8-candidate-r38.YwwZl6`；formal fingerprint `7cc9f67d...` 前后相同；9336 raw/119992332 bytes 闭合。全新 Codex 完成 `2026-08-12`、`2026-08-03..09` 七份日报和 `2026-08-09` 周报；周报前先落库 `weekly-fitness-summary` 精确七日报选择；`2026-08-16` 在模型调用前 blocked。生成四套报告、两份 prepared 邮件、四项 prepared GTS 课程、两份 workflow receipt；所有重放复用 output/HTML，candidate verify_state、artifact verifier、53 code tests、Ruff/format/mypy、provider/external actions=0 通过 | r38 正在等待三类独立 Validator，尚未宣称 M8 完成；r31 的正式 SHM 触碰失败证据继续保留 | 冻结当前源码、r38 candidate 与 `/private/tmp/m8-r38-real.o0jbne`，交 Code、AI、Data/Privacy 三类全新只读 Validator |
| 2026-08-17 / M8-0005-r38-validators | Code、AI、Data/Privacy 三名全新只读 Validator 均返回 `PASS`；Code 53 tests/Ruff/format/mypy/compile/schema、活动片段并发预算、receipt 和报告幂等通过；AI 8 日报+1 周报、8/16 模型前 blocked、七日报顺序、证据/课程/不编造通过；Data/Privacy 正式指纹、raw 闭包、权限/隐私/产物血缘/零外部调用通过 | M8 仅覆盖离线 candidate；真实 Garmin/Gmail/Sites 写入、cron 和正式 state 变更仍未授权 | 归档本计划，更新 PLANS.md 与 memory.md；保留 r31 SHM 触碰失败记录，不声称整个 M8 历史从未触碰 sidecar |
