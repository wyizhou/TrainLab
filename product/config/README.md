# TrainLab 配置

`config/trainlab.json` 是项目范围的本地用户配置文件。每次分析启动时都会重新读取，
不会使用跨任务缓存；后续层级如需增加用户可控
变量，应在该文件中增加顶级字段；请从
[`trainlab.example.json`](trainlab.example.json) 复制结构。

它被 Git 排除，因为可能包含个人设置。`mail.recipient_email` 是唯一获授权接收
TrainLab 邮件的固定地址。`training_difficulty_level` 为 1–5 的整数，缺省为 2。
`marathon_target_finish_time` 与 `half_marathon_target_finish_time` 接受
`HH:MM` 或 `null`：小时必须两位、分钟为 `00`–`59`、`00:00` 无效；`null` 表示
该距离没有完赛目标。

训练难度与两个完赛目标是权威用户设置。每次分析都会把明确值和配置来源放进受限
上下文，而不是只作为静态说明。`mail.recipient_email` 等运行设置仅用于宿主授权，
不会进入 AI prompt。凭据和 OAuth token 不得写入任何配置文件。

## 配置职责矩阵

| 类别 | 文件或位置 | 版本控制 | 用途 |
|---|---|---|---|
| 当前用户设置 | `config/trainlab.json`（本地） | 忽略 | 收件地址、训练难度、两个比赛目标/日期、可训练星期 |
| 当前用户设置模板 | `config/trainlab.example.json` | 跟踪 | 新机器初始化时复制的安全模板 |
| 当前数据基础与 Garmin 设置 | `config/foundation.yaml`、`config/garmin.yaml`（本地） | 忽略 | Foundation 存储根、Garmin 区域和认证运行参数 |
| 当前服务编排模板 | `config/orchestration.example.yaml` | 跟踪 | Supervisor 的示例调度与运维配置 |
| 当前分析策略 | `config/analysis.yaml` | 跟踪 | 分析层的版本化质量与训练策略 |
| Gmail MCP 模板 | `config/gmail_mcp.example.yaml` | 跟踪 | 当前环境 `gmail` MCP 的配置说明；不保存 token |

本目录不保存密码、OAuth client secret、refresh/access token 或任何认证文件。
