# 第五层 Supervisor 的 systemd 部署、停止、升级与回滚

状态：模板和静态审查资产；不构成安装或生产切换授权。

本手册只部署第五层 Supervisor。它是唯一常驻的业务调度服务；第二至第四层只能由
它按固定接口启动并在完成后退出。不要创建或启用任何直接调用 Garmin、分析或邮件层的
`systemd` timer/service，也不要让旧调度与此服务同时运行。

## 前置门与边界

在任何主机操作前，操作者必须确认：

1. S5-16、G2 和对应静态测试已通过；S5-18 影子对账、S5-19 受控真实验收及 S5-20
   切换仍是独立的后续门。
2. P5-05 和 P5-06 已被明确满足：专用服务账号、owner-only 配置、受限 Gmail MCP
   环境、旧入口清单、备份和回滚窗口均已由授权人复核。
3. `trainlab supervisor run` 支持 systemd `Type=notify`：只在完成启动
   bootstrap、取得 lease 且可开始心跳后发出 READY；每个 `WatchdogSec` 周期内持续
   发出 watchdog 心跳。若该能力未通过受控验证，保持服务未启用。
4. 服务启动 bootstrap 只允许幂等调用 `trainlab foundation init`。不兼容、锁冲突超出
   有限退避、损坏或权限问题必须停止领取任务并留下 incident，绝不自动迁移、full sync、
   regenerate 或修复目录。

本模板不保存 OAuth token、密码、邮箱地址、收件人、模型名、任意命令或业务内容。
Gmail 仅使用当前 Codex 执行环境已注册的 `gmail` MCP；没有该精确绑定时，保持未启用
并按 incident/认证流程处理，不能安装、认证或替换 transport。

默认 Foundation 布局将数据库放在 `state/data.db`。因此部署配置中的
`state_lock_path` 必须使用
`state/runtime/locks/supervisor.lock`，使 Supervisor 的诊断锁位于数据库
可信根内。不得通过放宽 LeaseManager 的路径校验来兼容旧的 `state/locks` 路径。

## 模板与最小权限

使用 [trainlab-orchestrator-supervisor.service.template](../../deploy/systemd/trainlab-orchestrator-supervisor.service.template)
生成实际 unit，并使用
[trainlab-orchestrator-supervisor.env.example](../../deploy/systemd/trainlab-orchestrator-supervisor.env.example)
生成 environment file。替换下列固定占位符时，只接受已审计的绝对路径和已存在的专用
系统账号；不要以 shell 拼接或环境变量改变 `ExecStart`。

| 占位符 | 含义 | 权限要求 |
|---|---|---|
| `@SERVICE_USER@` / `@SERVICE_GROUP@` | 专用、不可登录的服务身份 | 仅拥有本服务所需目录；不得是 root 或个人账户。 |
| `@PROJECT_ROOT@` | 经审计的只读发布目录 | 由 root 管理；服务账号不可修改代码、Harness、schema 或 unit。 |
| `@ENV_FILE@` | 本模板对应的最小环境文件 | `0600`、服务账号所有；不得加入 secret 或可执行值。 |
| `@DATA_ROOT@` | 第一层数据库与原始数据根 | `0700`、服务账号所有；供第二至第四层的受控写入使用。 |
| `@STATE_ROOT@` / `@LOG_ROOT@` | 第五层状态与脱敏日志目录 | `0700`、服务账号所有；只允许这些运行目录可写。 |

实际 unit 的固定 argv 只能是 `trainlab supervisor run`。它不接受配置路径或其他可变
argv，也不是可配置 command。项目根在审计和安装时固定，配置位置由 Supervisor 的受限
加载规则在该根内确定。所有下层 argv 由 Supervisor 内部的冻结模板决定；unit、
environment file 和配置都不能提供自定义 shell、SQL、收件人、日期范围或模型选择。

模板的安全与生命周期约束如下：

- `Type=notify` + `WatchdogSec=90s` 让 systemd 负责进程级存活监控；Supervisor 不尝试
  重启自身。
- `TimeoutStartSec=120s` 为大数据库上的幂等 Foundation 自检保留明确上限；READY
  仍只能在自检完成并取得唯一 lease 后发送。若启动超过该上限，应调查数据库或存储，
  不得继续放宽超时掩盖故障。
- `Restart=on-failure`、15 秒退避及 `StartLimitBurst=3` 避免快速崩溃循环。达到启动限制时
  不绕过 systemd 限制，先调查 journal、incident 与 lease。
- `SIGTERM` 会先阻止领取新 workflow，通知活跃 executor 在 `TimeoutStopSec=90s` 内完成
  受控清理；超时后仅由 systemd 回收同一 control group。不得将 TERM 当作成功 receipt。
- 写入仅限 data/state/log 根；代码、配置、系统目录和设备均受 systemd sandbox 限制。服务账号
  的 home 只读，以保留受限运行环境所需的只读绑定；不得在其中写入状态。资源上限为 1 GiB
  内存、64 tasks、256 文件描述符和一个 CPU；容量不足先走变更审批，不在现场放宽限制。

## 安装前静态审查（不启用服务）

在隔离的发布副本中完成占位符替换后：

1. 确认发布目录、配置、environment file、state 和 log 目录均不含符号链接，且其所有父
   目录不可被其他用户写入。
2. 确认实际 unit 不含 timer、`OnCalendar`、下层 CLI、shell 解释器、`sudo`、凭据、邮箱
   或模型名；`ExecStart` 必须仍是唯一的固定 Supervisor argv。
3. 用目标主机的 systemd 做 unit 语法验证，并检查 `User`、`Group`、`ReadWritePaths`、
   `NoNewPrivileges`、`ProtectSystem`、TERM、watchdog、restart 和资源限制仍存在。
4. 在未启用状态运行第五层 doctor/只读检查；基础 schema、配置 hash、Gmail MCP binding、
   state/log 权限或旧调度任何一项失败，均保持未启用并记录原因。
5. 在变更记录中固定 release 标识、unit hash、配置 hash（不记录内容）、数据库/状态备份
   的位置和 hash、当前 lease 状态及旧入口状态。

本仓库的 `tests/test_orchestration_s5_17.py` 是模板静态门，不执行 systemd、不连接主机，
也不会发送邮件。

## 受控启动与验收

只有获得 S5-19/S5-20 所需的逐项授权后，才能由指定运维人员执行下列受控动作：安装
审查过的 unit、重新加载 systemd manager、启用这个**唯一**的 Supervisor service，并观察
其 READY/Watchdog、lease 和 journal。禁止在本步骤启用旧 scheduler 或任何下层 timer。

启动后必须逐项证实：

1. 服务账号持有唯一的 `scheduler_leases/supervisor` lease，第二个实例保持被动且没有
   调用下层。
2. READY 只在 foundation bootstrap 与配置/schema 检查成功后出现；失败时没有 workflow
   被领取。
3. TERM 测试停止新工作领取，executor 在截止时间内退出或由 control group 回收；重启后
   只根据原 workflow/invocation/delivery ID 对账或恢复，不产生新业务身份。
4. watchdog 或连续崩溃达到启动限制时，服务保持停止并产生可追溯 incident；恢复操作
   先修复根因再由授权人清除启动限制和启动服务。
5. shadow/受控验收的每一项外部副作用均有精确 receipt 与 delivery ID；未通过即停止，
   不继续生产切换。

## 停止、升级与回滚

### 计划停止

1. 先冻结新部署和人工恢复动作，记录当前 release、唯一 lease、活跃 workflow/step、
   deferred retry 和 open incident 的只读快照。
2. 请求 Supervisor 正常停止；它必须停止领取任务并等待 executor 受控退出。达到停止时限
   后，按 systemd 的 control-group 策略回收残留子进程。
3. 验证 lease 已释放或已过期，且没有运行中的第五层 executor；保存 journal 和 receipt
   摘要。未知的下层结果一律留待 reconcile，不能认定失败或重发。

### 升级

1. 在停止前制作并校验数据库、第五层 state、配置和当前 unit 的独立备份；备份不包含
   凭据内容，且恢复路径已演练。
2. 按“计划停止”完成静止点，再部署只读发布目录和新模板，重新做静态审查及全量离线
   测试。不得在服务运行时覆盖代码、Harness、schema 或配置。
3. 将旧 release、unit hash 和配置 hash 写入变更记录。仅在 shadow/受控门批准后启动新
   Supervisor，首先验证唯一 lease、bootstrap、READY、watchdog 与一条无副作用路径。
4. 若任一检查失败，不启动新版本；保留证据并进入回滚。

### 回滚

1. 停止新 Supervisor，确认它不再持有 lease，且其 control group 不含 executor。
2. 恢复经过校验的旧发布目录、unit、owner-only 配置引用和 state/database 备份；不删除
   新版本的 journal、receipt 或 incident 证据。
3. 重新进行旧版本的静态审查和只读 doctor，确认旧入口或旧 Supervisor 中**只有一个**
   调度者能获得 lease。不得同时重新启用两者。
4. 在授权窗口内启动已验证的回退目标，核对 workflow/invocation/delivery ID 连续性；所有
   unknown send 或下层运行先 reconcile，再决定是否恢复。
5. 记录回滚原因、时刻、备份 hash、lease 证据、未完成 workflow 和后续修复责任。未完成
   的 S5-18 至 S5-20 门仍保持未完成。
