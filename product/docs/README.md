# TrainLab 文档索引

本目录按“当前运行所需”“冻结契约与证据”“旧链路/回滚材料”划分。当前生产路径
以根目录 [README](../README.md) 和五层架构为准；不要把 legacy 文档当作新功能的
配置或行为规范。

第三层 Harness 已确认的 60 项决策、实施顺序和验收门见
[60 项执行计划](60-item-execution-plan.md)。

## 当前运行手册

- [数据基础层最终验收](runbooks/foundation-final-acceptance.md)
- [Garmin 采集](runbooks/garmin-collection.md)
- [Gmail 生产配置](runbooks/gmail-production.md)
- [邮件 Agent 迁移与回滚](runbooks/mail-agent-migration.md)
- [Linux Supervisor systemd 部署](runbooks/orchestration-deployment.md)
- [macOS 本机单 Supervisor 部署](runbooks/macos-local-supervisor.md)
- [Supervisor 受控验收](runbooks/orchestration-controlled-acceptance.md)

## 冻结契约与验收证据

[layers/README.md](layers/README.md) 是五层冻结契约、跨层边界和验收证据的唯一
索引。五份契约由自动化校验内容哈希；普通文档维护不得修改它们。

## 旧链路与回滚

[legacy/README.md](legacy/README.md) 收录旧 Google Drive、Apple Health、rclone 和
训练策略材料。这些文件只支持未完成的生产切换、历史排查或受控回滚，不是当前
Garmin 五层架构的 canonical 规范。
