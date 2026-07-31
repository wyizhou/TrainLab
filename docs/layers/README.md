# TrainLab 五层冻结契约

本目录只保留当前架构的冻结契约、迁移手册和验收证据。已经完成的开发清单、
Todo 和临时基线报告由 Git 历史保存，不再作为当前文档维护。冻结契约正文中的
“实现状态”是契约冻结时的历史快照；下表单独记录当前仓库的实现与验收现状。

| 层 | 冻结契约 | 当前仓库现状 | 运行边界 |
|---|---|---|---|
| 1. 数据基础层 | [v2.4](01-data-foundation.md) | 当前实现与离线回归已存在 | 一次性幂等 init；ready 后严格 no-op |
| 2. Garmin 采集层 | [v1](02-data-collection.md) | 当前实现、真实采集与回归证据已存在 | 全量、增量、快照、审计和修复；执行后退出 |
| 3. 数据分析层 | [v2](03-data-analysis.md) | 当前实现与受控验收证据已存在 | 被动调用；结果先落库，再投递邮件 |
| 4. 邮件 Agent 层 | [v2.3](04-mail-agent.md) | 当前实现与真实 Gmail 验收证据已存在 | 只处理收件和回复，不重复发送分析产物 |
| 5. 总调度与监控层 | [v1](05-orchestration-monitoring.md) | 本机实现与验收证据已存在；远程切换待完成 | 新架构唯一常驻服务，负责调度、恢复和告警 |

五份冻结契约由自动化测试校验 SHA-256。修改契约必须作为明确的版本升级，
不能在普通代码或文档整理中顺带改动。

## 跨层规则

1. 使用一个 SQLite 数据库作为结构化数据权威来源，原始 JSON/FIT 保存在
   文件系统，数据库只保存路径、哈希和来源。
2. 时间以 UTC 保存，以 `Asia/Singapore` 派生日历日期。
3. 每张可写表只能有一个运行时所有者；其他层通过稳定视图或明确接口读取。
4. 原始数据不可变，规范化表可以从原始数据和解析器版本重新生成。
5. 表结构和语义变化必须通过版本化迁移，不允许静默改变历史数据含义。
6. 后续需求切分必须从已冻结文档出发；若共享契约改变，应先升级文档版本，
   再重新评估受影响的工作单元。
7. 第二层只提供执行完即退出的采集工具；调用时间、重试唤醒和运行监控属于第五层。
8. AI 总结、训练计划和邮件回复是有版本、有输入血缘的派生数据；不得覆盖或
   伪装成 Garmin 事实、邮件事实或用户明确陈述。
9. 第三层只由第五层被动调用，每次完成一个分析请求并自行投递 accepted 结果后
   退出；分析 Codex 无 Gmail 工具，独立 delivery Codex 只有受限 self-send 能力。
10. 第三层和第四层可以复用 Shared Harness、Codex Exec 适配器与通用安全校验，
    但必须保持独立脚本、专项 Harness、请求/回执、表所有权和副作用边界。
11. 第四层只由第五层被动调用；Codex 不直接获得 Gmail 工具。它只处理收件与
    回复，不重复发送第三层日报、周报或计划修订。
12. 第五层是唯一常驻业务服务，只负责调度、编排、监控和运维告警；所有业务修复
    必须调用对应层接口，不能直接修改下层状态。
13. 主动分析邮件、交互回复邮件和运维告警分别由第三、第四、第五层独立记录与发送。

## 当前验收与运维文档

- [第一层最终验收](../runbooks/foundation-final-acceptance.md)
- [Garmin 采集](../runbooks/garmin-collection.md)
- [分析受控验收](../runbooks/analysis-controlled-acceptance.md)
- [邮件迁移](../runbooks/mail-agent-migration.md)
- [真实 Gmail 验收证据](evidence/mail/M4-15-real-gmail-acceptance-2026-07-27.md)
- [第五层本机 No-Go 历史证据](evidence/orchestration/S5-local-acceptance-2026-07-27.md)
- [第五层当前本机部署基线](evidence/orchestration/S5-local-deployment-baseline-2026-07-31.md)
- [Supervisor 受控验收](../runbooks/orchestration-controlled-acceptance.md)
- [Supervisor 部署](../runbooks/orchestration-deployment.md)
