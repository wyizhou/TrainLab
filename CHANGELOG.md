# 变更日志

本文件记录 TrainLab 的重要变更。普通工作归入 `Unreleased`；只有用户明确要求发布并批准
版本号后，才能整理为正式版本。

## Unreleased

- 为 M9 日报恢复增加 Structured Outputs wire v2、递归兼容检查、公开合成 Schema canary，
  并将下游证据链版本化为 attempt 2/3 失败后唯一 attempt 4；旧 wire 与失败证据保持不变。
- 完成 M9 单日 Garmin MCP 有界只读采集与离线日报闭环：固定日期、工具、依赖和预算，使用
  cached-token-only 的离线启动器，把 MCP Capture、FIT、调用收据和离线 AI 日报仅写入
  仓库外 Candidate；Gmail、Workout、Sites、cron 与正式 state 保持关闭。
- 引入 agentForge `v0.4.2` 开发 Harness，并将 TrainLab 收敛为根 `src/`、根 `tests/`
  的唯一项目布局；移除临时 `product/`、旧开发编排控制面和无消费者的 legacy 文档。
- 将产品 Harness、Schema、策略和公开默认值迁入 wheel 的不可变
  `trainlab.resources`，以外置 `TRAINLAB_INSTANCE_ROOT` 保存私有配置、state 与 logs。
- 新增完整哈希依赖锁、可复现 wheel/runtime bundle、安全解包验证器、离线安装器和
  Linux/macOS CI 真安装链；bundle 不再包含源码 checkout、开发 Harness 或私有数据。
- 用可重复、无个人信息的代码生成 FIT 夹具替代私人测试样本，并移除项目内的
  `test_data/` 依赖与历史样本展示。
- 完成 M4 `source/` 工程、Foundation v4 离线重建与教练 Harness v2；源码 `mypy src`
  清零，补齐分析输入、SQLite、Garmin mixin 和交付工厂的显式类型边界，并保留
  tests/tools 类型债为后续候选。
