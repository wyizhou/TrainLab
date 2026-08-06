# TrainLab 更新记录

本文件采用只追加、不覆写历史条目的维护方式。每次代码、配置、运行行为或部署方式发生更新时，都必须在末尾增加一条带日期的记录。

## 2026-08-05：修复容器 PID 耗尽导致的定时任务失败

- 现象：香港时间 09:00 的 morning workflow 在 Garmin `current_snapshot` 阶段返回 `process_start_failed`。
- 根因：容器 PID 上限为 512，检查时已使用 508；共有 437 个由 PID 1 未回收的僵尸进程，其中 401 个来自 Node。cgroup 已记录 69 次 PID 上限命中。
- 关联现象：`gmail-mcp` 的 Node 子进程生成了 core dump；该崩溃发生在 morning workflow 失败约 47 分钟后，不是 morning 的直接失败步骤，但与进程资源压力一致。
- 代码修复：Linux 下的 Gmail MCP stdio 客户端在启动 `npx` 前启用 child subreaper；MCP 进程运行在独立进程组，关闭时终止整个进程组，并回收被收养的后代进程，避免其继续成为 PID 1 下的僵尸进程。
- 安全处理：`core` 与 `core.*` 已加入 `.gitignore`，防止可能包含内存敏感信息的崩溃转储进入 Git。
- 恢复要求：现有僵尸进程无法由 TrainLab 回收，部署修复版本前必须重启当前容器一次；重启后再验证 PID 数、morning workflow、Gmail MCP 和 Supervisor lease。

### 验证记录

- Gmail/MCP 相关针对性测试 49 项通过。
- Ruff 致命错误检查、Python 编译检查、仓库质量门和 Git diff 检查通过。
- 当前 Linux 环境已确认支持并成功启用 child subreaper。
- Supervisor 已停止，避免容器重启前继续消耗剩余 PID 配额。

## 2026-08-05：修复 morning workflow 对 Garmin 快照回执的误判

- 现象：容器重启后，受控重试中的 Garmin 增量采集和当天快照都实际成功，但编排器仍将 `current_snapshot` 标记为失败；边界诊断返回 `receipt_target_mismatch`。
- 根因：Garmin 快照的正式回执使用 `requested_range.from=null`、`requested_range.through=快照日期`，编排器却错误要求请求范围的起止日期都等于快照日期。
- 代码修复：编排器现在按正式快照回执契约验证请求目标；对于 `succeeded` 或 `partial` 回执，仍严格要求 `effective_range` 的起止日期都精确等于请求的快照日期，避免接受越界回执。
- 防回归：新增合法快照回执、非空请求起点、缺失终点和实际范围越界测试，并同步修正全部生产模式的离线边界夹具。
- 验证：编排边界测试 199 项全部通过；Garmin 快照及回执相关针对性测试 8 项全部通过。容器 `/tmp` 为 `noexec`，涉及临时可执行文件的测试改用已忽略的 `state/test-tmp` 临时目录运行。

### 生产恢复验证

- 修复提交 `f819373` 已推送到远程 `main`。
- 对原失败 workflow 2035 执行受控重试后，新 workflow 2202 完整成功：Garmin 增量采集、2026-08-05 当天快照、2026-08-04 数据质量审计、每日分析均为 `succeeded`，且未创建新 incident。
- 今日分析 run 102 成功，最新 analysis delivery 28 状态为 `sent`，无 `delivery_unknown` 或 `failed`。
- 通过当前 Codex 环境中已注册并授权的精确 `gmail` MCP 核实，“已发送”中存在主题为“TrainLab｜每日训练简报｜回顾2026年8月4日｜安排2026年8月5日”的邮件。

### 本机服务恢复

- `trainlab supervisor doctor` 的 configuration、contracts、foundation、Gmail 和 subject 五项检查均为 ready。
- 本机 Supervisor 已重新启动；即时检查确认仅有 1 个精确匹配的 `trainlab.local_supervisor` 进程，`local-supervisor.lock` 已在启动时刷新，容器 PID 使用量为 69/512。
- 按本机测试约定，仅完成启动与一次健康核验，不进行持续监控。

## 2026-08-05：修复历史分析投递持续触发健康告警

- 14 天稳定性测试的首轮基线检查发现，7 条历史日报回算产生的 `pending` delivery 使 `health:analysis:delivery` 持续告警，健康检查因此一直为 `partial`。
- 这些 delivery 对应 2026-07-28 至 2026-08-03 的历史回算，以及一次 HRV 上下文验证；用户要求发送的是最新周报和当日日报，直接重试这些旧 delivery 会错误补发历史邮件。
- 修复后，只有在同一用户、同一报告类型存在创建时间更晚且状态为 `sent` 或 `already_sent` 的投递证据时，旧 `pending`/`failed` 才从运维待办中退役；`sending` 和 `delivery_unknown` 始终保留为必须核对的状态。
- 分析状态与健康检查采用同一判定语义，不删除历史 delivery 和分析产物，也不伪造发送证据。生产只读状态验证已从 7 个可重试投递变为 0，`next_action` 变为 `none`。
- 按稳定性测试规则，发现问题后已停止 Supervisor；修复、测试、提交和重新部署完成前不开始累计 14 天稳定时间。

### 14 天稳定性计时重置

- 修复提交 `8865a0c` 已推送到远程 `main`，相关测试 20 项、Ruff 致命错误检查、Python 编译检查和仓库质量门均通过。
- Supervisor 重新启动后完成约 9.8GB 的启动读取校验并建立 active lease；受控健康检查 workflow 2217 为 `succeeded`，0 warning、0 error、0 incident，系统 open incident 数为 0。
- 新稳定起点：`2026-08-05T05:11:23Z`（香港时间 `2026-08-05 13:11:23`）；连续 14 天目标时间：`2026-08-19T05:11:23Z`。
- 计时状态和每次检查收据分别保存在本机忽略目录中的 `state/runtime/stability-monitor.json` 与 `state/runtime/stability-checks.jsonl`，不进入 Git，也不包含健康数据或凭据。

## 2026-08-05：修复 Supervisor 心跳绕过 SQLite 忙重试

- 14 天稳定性测试在第三次检查时发现，本地 Supervisor worker 曾以 `supervisor_lease_failed`、`lease_heartbeat` 退出，local launcher 随后自动拉起新 worker；服务已按测试规则停止，原稳定计时作废。
- 数据库审计显示旧 worker 最后一次健康任务成功、新 worker 接管后任务也继续成功，期间没有业务 workflow 失败。旧版本将具体租约错误统一脱敏，无法从历史输出反推出唯一底层异常。
- 代码核查发现一个与现象一致的确定缺陷：心跳只重试直接抛出的 SQLite `busy/locked`；连接层若将同一底层异常包装成 schema 读取异常，心跳会绕过既有重试预算并立即退出。
- 修复后，心跳会沿受控异常因果链识别真正的 SQLite `OperationalError` busy/locked，并继续使用原有的最长 10 秒、低于 90 秒租约 TTL 的有界退避；非 busy 数据库错误仍立即失败关闭。
- Supervisor 输出现在可区分固定且不含敏感信息的 `lease_database_unavailable`、`lease_ownership_lost` 和 `lease_clock_anomaly`，未知异常仍统一为 `supervisor_lease_failed`。
- 防回归测试覆盖包装后的临时锁重试、超出预算失败、非 busy 不重试、安全错误码保留和未知错误脱敏；租约与 Supervisor 针对性测试 49 项通过。

## 2026-08-05：修复分析状态读取与 WAL checkpoint 竞态

- 租约修复部署后的基线复核中，`trainlab run --slot morning --analysis-only --status` 在创建只读一致性快照时遇到 `data.db-wal` 于检查后、打开前被 checkpoint 删除，原实现泄漏了未受控的 `FileNotFoundError`。
- 按稳定性测试规则，发现后立即停止 Supervisor；该次候选基线不计入 14 天稳定时间。
- Foundation 现在把 WAL/SHM 快照成员在绑定窗口内消失统一转换为固定的 `sqlite_wal_state_unsafe`，继续保持 fail-closed，不接受混合时点快照。
- 只有只读分析状态入口会对这个精确错误最多重新打开 3 次；路径替换、权限异常、内容变化和其他 Foundation 错误不会重试。
- 新增测试覆盖 WAL 在初检后消失、精确瞬时错误重试以及其他安全错误不重试。完整相关套件中 478 项通过；另 2 项旧 SHM mtime 断言在未修复提交 `7331def` 的隔离副本中也同样失败，确认不是本次变更引入，且 inode、权限、大小和内容哈希均未改变。

### 14 天稳定性计时再次重置

- 修复提交 `8c0f821` 已推送到远程 `main`；部署前 doctor 的 configuration、contracts、foundation、Gmail 和 subject 全部 ready，Gmail 为当前环境注册的 `gmail_mcp_available`。
- Supervisor 启动后，原失败命令在并发运行状态下返回 `succeeded`、`next_action=none`，可操作的 pending/failed/delivery_unknown 均为 0，最新 delivery 28 为 `sent`。
- 基线健康检查 workflow 2295 为 `succeeded`，0 warning、0 error、0 incident；open incident 为 0，部署后没有非成功 workflow，launcher 和 worker 各 1，PID 使用量 68/512，无新增 PID 上限命中。
- 新稳定起点：`2026-08-05T06:42:44Z`（香港时间 `2026-08-05 14:42:44`）；连续 14 天目标时间：`2026-08-19T06:42:44Z`。下一次 30 分钟检查时间为 `2026-08-05T07:12:44Z`。

## 2026-08-05：14 天测试因执行环境暂停再次重置

- 08:42:44Z 周期检查发现 Supervisor worker 从 8328 变为 12923，launcher 缓冲收据为 `lease_lost`；08:16:57Z 至 08:44:33Z 间没有调度任务，健康任务最大间隔约 27 分 36 秒。
- 同一窗口内，监控会话的 600 秒等待跨越了约 30 分钟系统时间；旧 worker 恢复后发现 90 秒 lease 已过期并安全退出，launcher 按 15 秒退避启动新 worker。业务 workflow、健康结果和分析投递均没有失败，但连续运行要求已被破坏。
- 这次不修改 lease 的 fail-closed 语义：进程经历长时间暂停后不得续接已过期所有权。运维修复是取消超过 55 秒的监控等待，避免执行环境被长时间阻塞/挂起；每轮检查新增对 worker PID 集合和健康 workflow 最大间隔的连续性验证。
- 服务已立即停止，原稳定计时作废。完成文档提交、doctor、重启和新基线前不重新计时。

### 环境暂停后的新基线

- 运维记录提交 `3dba5ab` 已推送；doctor 五项全部 ready，Gmail 为 `gmail_mcp_available`。
- 新 worker 13640 完成约 5.4GB 启动读取后建立 active lease；基线 health workflow 2416 succeeded，分析状态为 ready/none，且无失败 workflow 或 open incident。
- 新稳定起点：`2026-08-05T09:07:39Z`（香港时间 `2026-08-05 17:07:39`）；连续 14 天目标时间：`2026-08-19T09:07:39Z`。后续监控等待严格限制为每段不超过 55 秒。

## 2026-08-06：执行环境故障后的恢复与当日日报补录

- 2026-08-05 09:13Z 后，Supervisor worker 13640 在 lease heartbeat 阶段以固定错误 `lease_database_unavailable` 安全退出；本地 launcher 首次观察到子进程退出码 `-7`（SIGBUS），其后三次重启均因执行入口不可用返回 127 并停止重试。
- 同一时刻，项目外的基础命令与文件补丁操作也统一返回 `Bad file descriptor`。故障同时影响 shell、launcher 和文件访问，且数据库中的最后 6 个业务 workflow 均已成功、open incident 为 0；现有证据更符合容器/virtiofs 执行环境故障，而不是 TrainLab 业务逻辑失败。服务保持停止，原 14 天稳定计时作废。
- 环境重启后，`trainlab supervisor doctor` 的 configuration、contracts、foundation、Gmail 和 subject 全部 ready；Gmail 为当前 Codex 环境注册的 `gmail_mcp_available`。SQLite 只读状态、WAL journal mode 和业务查询恢复正常；重启前遗留 lease 已过期，未手工篡改数据库状态。
- 由于 2026-08-06 09:00（香港时间）的定时任务在服务停止期间错过，使用唯一受控入口补跑 `morning`。Garmin 增量采集补齐至 2026-08-05，当天快照至 2026-08-06，2026-08-05 audit 成功，三步均为 0 失败。
- 日报 analysis run 103 成功生成“2026-08-05 总结”和“2026-08-06 建议”；delivery 29 状态为 `sent`。通过当前 `gmail` MCP 在“已发送”中精确检索，主题“TrainLab｜每日训练简报｜回顾2026年8月5日｜安排2026年8月6日”仅有 1 封。
- 本次环境恢复后必须重新部署 Supervisor、完成健康基线并重新开始连续 14 天稳定性计时；不得沿用 2026-08-05 的旧起点。

## 2026-08-06：按用户要求结束本轮稳定性测试

- 用户暂停并结束当前 14 天稳定性测试；本机 `trainlab.local_supervisor` launcher 与 `trainlab supervisor run` worker 均已正常终止。
- 不再继续 30 分钟巡检或累计稳定时间。本次仅保留既有运行与补录证据，未重启服务、未修改业务数据，也未再次发送邮件。

## 2026-08-06：时长语义、心率候选、活动回顾与历史计划连续性

- 修正 Garmin Connect 与 FIT 的时长映射：总经过时间、活动计时时间和移动时间不再混用；邮件训练量改用活动计时时间。
- 质量门只让目标日期内的未解决问题影响当次分析，避免历史活动警告污染今日总结。
- 心率三方法候选改为每周自动追加；完全缺失时由日报立即初始化一次，候选仍须用户确认后才生效。
- 昨日运动按活动 ID 合并 FIT 与天气，固定展示配速与心率，并允许 AI 选择最多两项由程序绑定数值的步频、功率或爬升指标。
- 周计划新增最近 28/90 天训练历史特征；本机训练星期配置为周一、周二、周三、周五和周日。
- 周报新增 HRR、历史阈值代理和 Tanaka 三方法对比卡；未确认候选明确标注为不参与训练处方。
- 历史活动修复时发现 nested `summaryDTO` 离线重放曾使用未归一化外层对象；现已修正为归一化摘要，并让带日期的 activity repair 只处理日期范围内 revision。受影响的 505 条本地活动已从保留的 raw/FIT 恢复，未删除任何同步数据。
