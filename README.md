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

## 本地数据

以下路径属于本地运行状态，已从 Git 排除，不得提交或在清理时删除：

- `data.db*`：结构化数据
- `raw/`：Garmin 原始 JSON 和 FIT
- `state/`：同步游标、运行状态、锁和认证文件
- `source/`、`test_data/`：本地迁移资料和私有测试样本
- `config/trainlab.json`、`config/foundation.yaml`、`config/garmin.yaml`：
  用户配置

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

- [五层冻结契约与状态](docs/layers/README.md)
- [Garmin 采集手册](docs/runbooks/garmin-collection.md)
- [分析受控验收](docs/runbooks/analysis-controlled-acceptance.md)
- [Gmail 生产配置](docs/runbooks/gmail-production.md)
- [Supervisor 部署](docs/runbooks/orchestration-deployment.md)
- [Supervisor 受控验收](docs/runbooks/orchestration-controlled-acceptance.md)
