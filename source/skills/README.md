# TrainLab 运行 Skills

本目录是未来 `source/AGENTS.md` 使用的运行 Skill 索引。根目录 `skills/` 属于 agentForge
开发 Harness；两者不得混用。

| Skill | 状态 | 触发场景 | 读取范围 | 写入范围 | 外部副作用 |
| --- | --- | --- | --- | --- | --- |
| `garmin-sync` | 规划中 | 每日有界同步、人工补数 | SQLite 采集状态、Garmin MCP | raw 与 SQLite 状态 | 经授权读取 Garmin |
| `training-coach` | 规划中 | 日总结、周总结和课表 | goal、当前 raw 摘要、历史总结 | SQLite 输出 | 无 |
| `weekly-fitness-summary` | 规划中 | 周训练复盘 | 本周日报、既有周总结、定向证据 | SQLite 输出 | 无 |
| `garmin-training-sender` | 规划中 | 已批准课表写入 Garmin | 已批准课程合同、SQLite 幂等状态 | SQLite 外部动作状态 | 经授权修改 Garmin |
| `gmail-sender` | 规划中 | 查询、接收或发送邮件 | 已批准邮件内容、Gmail MCP | SQLite 外部动作状态 | 经授权读取或修改 Gmail |
| [`training-report-publisher`](training-report-publisher/SKILL.md) | 已建立 | 日报、周报和课表展示 | 已验证、哈希绑定的 Skill 输出 | SQLite 报告与邮件渲染输出 | Sites 仅另行授权后可写 |

“规划中”表示仅已确认需求，当前目录尚未提供可执行 Skill，不得假装调用成功。

未来可建立 `_shared/` 保存单一、受测的 SQLite、canonical JSON、权限和摘要帮助代码；它没有
`SKILL.md`，不是可调用 Skill，也不得包含任何训练或 Provider 业务判断。

`training-report-publisher` 只通过名称调用已安装的 `$data-analytics:build-report`，并在另有
授权时调用 `$data-analytics:publish-artifact-to-sites`；项目不复制或修改插件 Skill 原件。
