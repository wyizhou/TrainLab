# TrainLab

TrainLab 是一个本地优先的 Garmin 训练分析系统。它采集健康与运动数据，
生成跑步训练总结和计划，通过 Gmail 发送结果并处理回复；所有长期运行、
定时调度、失败恢复和服务监控统一由 Supervisor 管理。

## 当前架构

1. **数据基础层**：一次性初始化 SQLite、原始数据目录和共享 Schema。
2. **Garmin 采集层**：提供全量、增量、当天快照、审计和修复工具；执行完即退出。
3. **分析层**：通过生产 Harness 调用 Codex，生成每日总结、周总结和
   Hansons Marathon Method 跑步计划，并保存输入血缘和版本。
4. **邮件层**：读取带 `TrainLab` 标签的邮件、保存会话并生成回复。
5. **Supervisor**：唯一常驻业务服务，负责调度以上一次性工具、重试恢复、
   质量门禁和运维告警。

第三层只通过 `trainlab run` 进入生产分析。分析结果和邮件发送均具备幂等记录，
失败后不会盲目重复发送。

当前已确认的 60 项执行清单、验收门和实施顺序见
[`docs/60-item-execution-plan.md`](docs/60-item-execution-plan.md)。

### 时间、采集和日报边界

- 数据库时间戳统一保存为 UTC；业务日期使用 `Asia/Hong_Kong`。
- 日报每天香港时间 09:00 发送：报告日 D 包含 D 白天、D→D+1 主睡眠和
  D+1 早晨恢复白名单信号；睡眠仍未完成也会发送并披露缺失/进行中状态。已最终
  确认且时长自洽的主睡眠会在邮件中显示深睡、浅睡、REM 与清醒阶段图表。
- 周报每周一 09:00 发送，回顾刚结束的周一至周日并规划当前周。
- 日报主题明确写出“回顾 D｜安排 D+1”，正文先给出数据窗口和完整性，再给出
  运动/健康事实、分析结论与下一日建议；部分或未完成的睡眠不会被当作正常缺失。
- 周报同时展示回顾区间、计划区间、比赛目标/参赛日期，以及有边界的运动—天气
  关联摘要；如果历史活动天气尚未进入周报结构，会明确标注待补录而不臆造天气。
- 心率区间确认邮件以 HRR 为主，并同列历史阈值代理和 Tanaka 低置信度对比；只有
  用户明确回复“确认 HRR”后才新增生效 revision，未确认前不会影响训练分析。
- 运动保留所有类型，但原始运动主来源是增量同步的 ORIGINAL FIT；天气按每个
  活动 ID 请求一次并与活动关联，天气缺失不阻止活动入库。健康默认只采集睡眠、
  全天/静息心率、HRV、脉搏血氧、跑步 VO₂ Max 和体重。
- FIT 原文件和健康 JSON 在本地永久保留；SQLite 只保存可重建的规范化投影和有界
  特征。默认分析不会把完整 FIT 或每秒 sample stream 交给 AI，只有用户明确指定
  活动 ID 时才会解码指定 FIT，并受 1.1 MiB 上限和默认脱敏规则约束；未明确绑定
  的活动不会被展开。

### 跑步心率区间（需用户确认）

TrainLab 被动计算一份追加式候选：HRR 为主方法，历史阈值心率代理仅作一致性
校验，Tanaka 年龄公式仅作低置信度备用。计算不会自动改写 Garmin 数据或自动生效，
结果会通过邮件请求二次确认；确认后新增 revision，AI 只使用最新确认 revision。

HRR 公式：

`心率储备 = 最大心率 − 静息心率`

`目标心率 = 静息心率 + 强度百分比 × 心率储备`

默认证据窗口为静息心率最近 28 个有效健康日、最大心率最近 180 天跑步、阈值
代理最近 90 天跑步；天气、暂停、传感器异常和明显失真会被质量过滤。最大心率
候选必须来自至少两次独立跑步的持续高心率证据，不能由单点尖峰或 Conconi 断言
产生。Tanaka 公式为 `208 − 0.7 × 年龄`，仅是群体预测，不能自动解锁高强度精确
处方。

相关研究：[HRR 与 VO₂ reserve](https://pubmed.ncbi.nlm.nih.gov/9139182/)、
[持续运动下的关系](https://pubmed.ncbi.nlm.nih.gov/22034854/)、
[Conconi 跑步有效性](https://www.tandfonline.com/doi/abs/10.1080/026404197367173)、
[阈值复现](https://pubmed.ncbi.nlm.nih.gov/10190774/)和
[Tanaka 最大心率](https://pubmed.ncbi.nlm.nih.gov/11153730/)。

## 本地数据与存储位置

新五层架构的唯一权威存储根目录是 `state/`：

| 路径 | 用途 | 清理规则 |
|---|---|---|
| `state/data.db` | 当前 SQLite 结构化数据 | 不提交；服务运行时不得手动删除 |
| `state/raw/` | Garmin 原始 JSON 与 FIT | 不提交、不可变 |
| `state/runtime/` | 同步游标、锁、运行记录和认证状态 | 不提交；只由受控运行流程写入 |
| `state/backups/` | 具名备份及其校验信息 | 按回滚窗口和授权清理 |

旧根目录数据库、旧 `state/foundation/` 布局、`source/` 输入和退役的私有配置在迁移
验收结束前保留于本机回滚目录，并附带 SHA-256 搬迁清单。它们不是当前架构的
canonical 数据源，只供历史排查或单独授权的回滚；不得覆盖 `state/` 当前数据。

`test_data/` 是本地私有测试样本。`config/trainlab.json`、
`config/foundation.yaml` 和 `config/garmin.yaml` 是本地用户配置。这些路径都已
排除在 Git 之外，不得提交或在常规清理中删除。

原始数据不可变；规范化表可以从原始文件和解析器版本重新生成。

## 安装与检查

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install -e .
.venv/bin/pytest
```

仓库质量门使用 `requirements.lock` 中固定版本的 Ruff 与 mypy。当前采用增量静态
检查，只覆盖新拆出的高类型完整度模块和质量脚本，避免把历史全仓格式化混入功能
变更：

```sh
.venv/bin/python scripts/verify_repository_quality.py all
.venv/bin/ruff check src/trainlab/foundation/readiness.py \
  src/trainlab/local_supervisor.py \
  src/trainlab/orchestration/workflow_incidents.py \
  src/trainlab/process_liveness.py \
  scripts/verify_repository_quality.py \
  tests/test_local_supervisor.py tests/test_repository_quality.py
.venv/bin/ruff format --check src/trainlab/foundation/readiness.py \
  src/trainlab/local_supervisor.py \
  src/trainlab/orchestration/workflow_incidents.py \
  src/trainlab/process_liveness.py \
  scripts/verify_repository_quality.py \
  tests/test_local_supervisor.py tests/test_repository_quality.py
.venv/bin/mypy src/trainlab/foundation/readiness.py \
  src/trainlab/local_supervisor.py \
  src/trainlab/orchestration/workflow_incidents.py \
  src/trainlab/process_liveness.py \
  scripts/verify_repository_quality.py
```

质量脚本离线校验冻结契约哈希、本地 Markdown 链接和三组设计稿/运行时邮件模板
字节同步。GitHub Actions 在 Linux 运行质量门和除 macOS 专属文件外的完整测试，
在 macOS 单独运行 `plutil`/LaunchAgent 静态验收；配置见
[`.github/workflows/ci.yml`](.github/workflows/ci.yml)。

常用的一次性检查：

```sh
.venv/bin/trainlab foundation status
.venv/bin/trainlab foundation verify
.venv/bin/trainlab garmin status
.venv/bin/trainlab supervisor doctor
.venv/bin/trainlab orchestrate status --json
# 只读浏览事实：active/pending/future/expired/revoked
.venv/bin/trainlab facts --subject-id 1 --status active
```

`foundation status` 是日常快速就绪检查，只读取发布后的 ready marker、受支持
Schema 版本以及固定路径/权限摘要，不打开 SQLite。`foundation verify` 才执行完整
Schema、迁移收据、SQLite integrity 和外键检查，因此可能扫描整个数据库，适合显式
维护或验收，不应放进每分钟调用路径。Supervisor 每次健康周期只做轻量 SQLite
readiness；完整 SQLite 深检只在首次或距离上次至少 24 小时时运行。

首次使用 Garmin：

```sh
.venv/bin/trainlab foundation init
.venv/bin/trainlab garmin auth
.venv/bin/trainlab garmin sync full --health-from 2022-01-01
```

后续采集由 Supervisor 调用增量、快照、审计和修复接口。下层工具自身不包含
daemon、cron 或持续轮询。

## 配置

项目通用用户配置说明见 [`config/README.md`](config/README.md)。训练难度、
马拉松目标时间和半马目标时间是权威用户变量，每次分析都会明确传给 AI。

Gmail 必须使用当前 Codex 环境中名为 `gmail` 的 MCP 服务，支持的实现为
`@artymclabin/gmail-mcp`。项目不复制或绑定特定机器的 Gmail token。

## 运行与部署

手工触发工作流：

```sh
.venv/bin/trainlab orchestrate run morning --date YYYY-MM-DD
.venv/bin/trainlab orchestrate run weekly --as-of YYYY-MM-DD
.venv/bin/trainlab orchestrate run mail
.venv/bin/trainlab orchestrate retry WORKFLOW_RUN_ID
```

新五层架构的唯一常驻入口为：

```sh
.venv/bin/trainlab supervisor run
```

开发机或 SSH 容器中可用受控的本地 launcher 进行短期观察。它持有独立的 owner-only
文件锁，每次只启动一个固定的 `trainlab supervisor run` 子进程；子进程异常退出时按
15、30、60 秒最多重启三次，收到 `SIGTERM`/`SIGINT` 后停止且不再重启：

```sh
install -d -m 700 logs
install -m 600 /dev/null logs/supervisor.local.out.log
install -m 600 /dev/null logs/supervisor.local.err.log
nohup .venv/bin/python -m trainlab.local_supervisor \
  >>logs/supervisor.local.out.log \
  2>>logs/supervisor.local.err.log </dev/null &
```

launcher 只负责当前容器内的短期测试，不能跨容器替换，也不替代宿主服务管理器。
连续三次重启仍失败时会停止并留下 data-free 收据，必须人工调查。
独立文件锁只串行化 launcher；数据库 lease 仍是唯一 active Supervisor 的权威边界，
手工误启的第二个 Supervisor 最多进入 passive 后退出，不能获得调度权。

启动前必须确认没有第二个 Supervisor；启动后只验证一次唯一进程、唯一 lease 和
`orchestrate status`，不要并行启动旧 scheduler。长期 Linux 服务器部署使用
[`deploy/systemd/trainlab-orchestrator-supervisor.service.template`](deploy/systemd/trainlab-orchestrator-supervisor.service.template)，
步骤见 [`docs/runbooks/orchestration-deployment.md`](docs/runbooks/orchestration-deployment.md)。
macOS 本机使用当前的单 Supervisor LaunchAgent，步骤见
[`docs/runbooks/macos-local-supervisor.md`](docs/runbooks/macos-local-supervisor.md)。

仓库只保留当前五层工具以及单 Supervisor 的 systemd/launchd 部署资产。旧 Google
Drive、旧 scheduler/watchdog、下层独立 launchd 和多服务 systemd 实现已经退役；
历史数据并不会因此被删除。

workflow 执行失败会生成去重 incident。mail/health-check 的后续成功轮询会关闭严格
匹配的更早失败。morning/weekly 的终态失败不会被定时器自动重做；操作员通过已审计
的 `orchestrate retry` 显式重试时，系统保留原失败 run，并创建一个带父 run 引用的
新 manual run。只有这个新 run 成功后，才关闭同一 subject、同一逻辑日期且仍为
`open` 的旧 workflow 失败。已确认、已抑制、安全/数据质量或其他人工保留事件不会
自动关闭；恢复告警使用独立幂等记录。

## 文档入口

完整的当前文档索引、验收证据和 legacy/rollback 材料见
[docs/README.md](docs/README.md)。
