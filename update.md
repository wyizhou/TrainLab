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
