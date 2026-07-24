# TrainLab

TrainLab 是一个本地优先、双阶段 Agent Harness：开发阶段负责同步、
导入、回归与生产验收；运行阶段只接收经过 Schema 限界的七天上下文，并通过
Gmail 向已认证账号本人发送带内联样式的中文训练邮件。

当前生产运行器仅为 Codex，使用不指定模型名称的 `codex exec --ephemeral`，并在
临时目录中进行无状态运行。失败后系统先按 run-id 查询 Gmail：若已经发送则补记
回执，若没有发送则记录失败，不调用其他模型。

## 固定数据路径

- 健康表：`source/Health.xlsx`
- 运动文件：`source/HealthFit/*.fit`
- SQLite：`data.db`

Excel 指标和 FIT 传感器均采用通用键值模型。文件内容 SHA-256、FIT session UUID/
后备指纹和 Excel 自然键共同保证增量导入与重命名去重；原始证据不会被覆盖。

## 本地开发与诊断

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install -e .
.venv/bin/trainlab ingest
.venv/bin/trainlab prepare --slot morning
.venv/bin/trainlab run --slot morning
.venv/bin/pytest
```

默认 `mail.mode: fake`，测试邮件保存在忽略提交的 `state/fake_gmail.json`。即使没有
新数据也会生成邮件；命令行只输出内部 JSON 回执，不输出报告正文。

公共命令为 `trainlab doctor|sync|ingest|prepare|run|watchdog`；`scheduler`、
`deploy` 和 `finalize-production` 用于运维及生产切换。

## 生产状态与部署门

生产调度默认关闭。必须先完成以下项目，`trainlab doctor` 才会通过：

1. 按 `references/rclone_setup.md` 安装锁定版本 rclone 并填写远端目录。
2. 按实际情况填写 `config/profile.yaml`；其中没有固定训练时间，系统不会指定几点训练。
   心率 Zone 与进阶门槛不属于个人参数，统一保存在 `config/running_policy.yaml`，详见
   `references/heart_rate_zone_policy.zh-CN.md`。全部跑步编排、恢复、攀岩、力量和
   反馈默认策略汇总见 `references/default_strategy_summary.zh-CN.md`。力量建议采用
   不依赖历史的动作模式，只给有益于跑步和攀岩的动作及已检查链接，不输出组次或公斤数。
3. 按 `references/gmail_mcp_setup.md` 为 Codex 和确定性 watchdog 客户端绑定
   TrainLab 受限 Gmail MCP 五项能力；运行代理不暴露通用 Gmail 工具。
4. 将 `mail.mode` 改为 `mcp`，将 `production.enabled` 改为 `true`。
5. 完成 Codex 真实 self-send/搜索/标签测试和 watchdog 故障—恢复测试，
   将证据写入 `state/production_acceptance.json`。
6. 执行 `trainlab finalize-production`。只有此命令会把开发 Harness 标为过期并移入
   `archive/`；随后 `trainlab deploy --enable` 才允许启用 launchd/systemd 定时器。

当前生产验收已在 Ubuntu Linux 环境完成，开发 Harness 已标记过期并归档。运行入口
只加载共享 Harness 与运行 Harness；`archive/` 不会进入定时分析上下文。生产运行器
当前仅启用 Codex，其他运行器以后需要按自身行为单独验收。

Google Drive OAuth 首次配置、候选验证和回滚流程见
`docs/runbooks/google-drive-bootstrap.md`；Gmail 生产绑定及验收流程见
`docs/runbooks/gmail-production.md`。Linux 实测兼容经验见
`docs/runbooks/linux-production-observations.md`；该文档只记录特定版本的观察结果，
不是未来模型或运行器的强制配置。所有手册均禁止记录任何凭据值。

## 目标分层架构

新一代 Garmin 数据基础、采集、分析、邮件监控和服务监控采用分层文档逐层冻结。
当前生产实现继续按上述入口运行，只有完成开发、迁移和验收后才切换。文档状态和
入口见 [`docs/layers/README.md`](docs/layers/README.md)；第一层数据基础契约
v2.4、第二层数据采集契约 v1、第三层数据分析契约 v2、第四层邮件 Agent 契约 v2
与第五层总调度和服务监控契约 v1 已冻结。第一层以一次性幂等 init 存在；第五层
Supervisor 启动时可以调用，环境 ready 后只返回 `already_initialized` 且严格 no-op；
显式迁移属于独立维护操作。
第二层是执行完即退出的 Garmin 全量、增量、当天快照、修复和补漏工具。第三层同样
由第五层被动调用，负责日总结、周总结/未来七天计划和正式计划修订；结果先落库，
再通过受限 Gmail MCP 主动发送。第四层只负责检查 TrainLab thread/标签邮件、保存
会话与用户事实并生成和发送回复，不重复投递第三层产物。第五层是唯一常驻业务服务，
负责每天 07:00、星期日、邮件检查、跨层恢复、健康监控和独立运维告警。目标分层
实现已进入开发，但尚未完成跨层集成、受控真实验收和生产切换；当前生产入口保持不变。
