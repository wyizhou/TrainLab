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

## 本地数据与存储位置

新五层架构的唯一权威存储根目录是 `state/foundation/`：

| 路径 | 用途 | 清理规则 |
|---|---|---|
| `state/foundation/data.db` | 当前 SQLite 结构化数据 | 不提交、不手动删除 |
| `state/foundation/raw/` | Garmin 原始 JSON 与 FIT | 不提交、不可变、不手动删除 |
| `state/foundation/state/` | 同步游标、锁、运行记录和认证状态 | 不提交、不手动删除 |
| `state/foundation/backups/` | 具名备份及其校验信息 | 不自动合并或删除 |

根目录的 `data.db`、`raw/`、`source/` 以及 `state/` 下不属于
`state/foundation/` 的旧运行资料，均是旧 Drive/迁移链路的兼容或回滚资产，
不是当前架构的 canonical 数据源。它们在生产切换和回滚验证完成前保留；任何
迁移或删除必须是带校验清单的独立任务。

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

常用的一次性检查：

```sh
.venv/bin/trainlab foundation status
.venv/bin/trainlab garmin status
.venv/bin/trainlab supervisor doctor
.venv/bin/trainlab orchestrate status --json
```

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
```

新五层架构的唯一常驻入口为：

```sh
.venv/bin/trainlab supervisor run
```

Linux 部署使用
[`deploy/systemd/trainlab-orchestrator-supervisor.service.template`](deploy/systemd/trainlab-orchestrator-supervisor.service.template)，
步骤见 [`docs/runbooks/orchestration-deployment.md`](docs/runbooks/orchestration-deployment.md)。

仓库中仍保留旧 Google Drive、scheduler、watchdog、launchd 和多服务 systemd
兼容入口，供尚未完成的生产切换与回滚使用；它们不属于新五层架构。远程切换和
回滚验证通过后，再用独立任务淘汰这些兼容文件。

## 文档入口

完整的当前文档索引、验收证据和 legacy/rollback 材料见
[docs/README.md](docs/README.md)。
