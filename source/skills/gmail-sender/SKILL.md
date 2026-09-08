---
name: gmail-sender
description: Inspect existing Gmail REST authentication and the current simple-mail delivery contract. Send only through the delivered M12 publisher with exact authorization, never through old test batches.
---

# Gmail 基础能力

遵守[产品边界](../../AGENTS.md)及A-010/A-011。当前保留官方REST/OAuth公共基础；M12同步邮件及附PDF周报发布器尚未交付，不得启动旧M10/M11发送或continuation命令。

- 收件地址只从owner-only私有email.json读取，不猜测、不写入Git或公开日志。OAuth Client和Token不进入Candidate、数据库或模型。
- 只用Gmail官方REST，不回退MCP、SMTP或Connector；已有专用Token可正常原子刷新，失败保留旧Token，不自动重新认证。
- 新发布器必须先保存意图，每份邮件最多发送一次。只读查询/RAW恢复沿用有界重试，send绝不自动重发。
- 本地Message-ID是意图标识；成功以唯一Gmail ID、RAW实际Message-ID、收件人、标题、正文和解码PDF SHA闭合为准。Gmail改写头不等于发送失败。
- 持久send capture有合法Gmail ID时使用它恢复RAW；不确定、认证错误、多条匹配或内容不符保持unknown/停止。
- 邮件与Garmin动作分开记账；重启、版本或实例搬迁不能重获发送预算。
- 编辑在本地、发送前形成新修订，不创建云端草稿，不修改已发邮件。
- 历史8/16封、日报canary、CID/高保真批次的批准与回执只作历史证据，不提供当前发送授权。

独立认证维护工具仍在scripts/gmail_rest_auth.py；仅用户明确要求认证且前检通过才运行。已有认证无需重做。新周期、数量和发布动作必须经过当前前置验收及精确授权。
