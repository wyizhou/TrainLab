# TrainLab 运行 Harness

本文件只描述 `source/` 的产品运行方式，必须服从仓库根目录的 agentForge 开发 Harness、
`rules.md`、`PLANS.md` 和当前 exec plan。它不授权修改代码、修改长期目标、调用外部服务或
绕过 SQLite 状态合同。

## 每次无状态运行的读取顺序

1. 读取本文件和 `config.json`。
2. 读取私有 `goal.md`；文件缺失、权限不是 `0600` 或结构无效时立即 `blocked`。
   Gmail 自投递还必须读取私有 `email.json`；首次配置时从可跟踪的空模板
   `email.module.json` 复制并填写。`email.json` 只能包含当前认证邮箱地址，必须为 `0600`
   且被 Git 忽略，缺失、占位、权限错误或地址无效时不得调用 Gmail。
3. 读取 `skills/README.md`，再只读取本次任务需要的 `SKILL.md` 和其脚本说明。
4. 读取 `state/trainlab.db` 的最近运行、输出、批准和外部动作；数据库缺失或锁不可用时停止。
5. 由脚本生成有界证据后再交给 AI。不得把完整 raw、FIT、凭据或邮件历史直接放入上下文。

测试只用于开发和验收，不是正常运行输入。确定性测试在 `tests/code/`，AI 语义验收在
`tests/ai/`；运行时不得读取这两个目录。

## 硬性训练规则

- Hansons 只作为跑步课程的缩放参考，不覆盖恢复和安全证据。
- Easy 是低负荷有氧；SOS 是有明确质量目标的高负荷课，两者不得混写。
- 跑步 SOS 与高负荷攀岩统一计入硬负荷；硬负荷最多 3 次，任意两次至少间隔 2 个日历日。
- 每天最多一个主课；不补偿错过的质量课；不在同一周同时增加距离和强度。
- 日报、周报和课表只能引用已验证输入，不能把 AI 偏好写回 `goal.md`。
- 疼痛、胸痛、晕眩、异常呼吸或明显恢复不足时，降低训练或停止训练，并记录稳定错误码。

## 数据和外部边界

- 健康与活动只作为 `state/raw/` 下的原始文件保存；SQLite 不承载健康、睡眠或活动业务事实表。
- 所有 Skill 的输入摘要、输出、批准、成功/失败/待处理状态都追加写入 `state/trainlab.db`。
- 日常 Garmin 同步只处理昨日完整数据和今日早晨结束的主睡眠，不自动回读最近 14 天。
- 补数、Garmin Workout 写入、Gmail 查询/发送和 Sites 发布必须有明确范围、批准、幂等键和对账。
- 本阶段 cron 只生成配置，不安装或启用；没有授权时不得调用 Garmin、Gmail 或 Sites。
- Garmin MCP 凭据或认证状态缺失、过期或格式不明时，Skill 必须安全停止并写入脱敏错误；
  不得猜测密码、MFA 或 token 内容。Gmail 按 A-010 使用 owner-only
  `gcp-oauth.keys.json` 与 `gmail-api-token.json`：首次授权只能由用户在系统浏览器完成，运行时
  只允许正常刷新该专用 token，并以 `0600` 临时文件、fsync 和原子改名更新；旧
  `credentials.json` 只作为 Gmail MCP 历史保留且不得读取或覆盖。
- `email.json` 不是凭据，只保存 Gmail 自投递地址；地址可以进入私有 Candidate 的精确动作
  请求以便审计，但不得进入 Git、报告正文或公开日志。

## 输入和输出

`training-coach` 可以接收用户输入，也可以接收定时 AI 的有界输入；它输出结构化总结和课表。
`training-report-publisher` 负责 HTML/邮件表现层，`gmail-sender` 负责邮件外部动作，
`garmin-training-sender` 负责已批准的 Garmin Connect My Workouts `-GTS` 模板。

任何脚本失败都必须使用稳定错误码写入 SQLite，而不是只打印一段不可恢复的文本。Skill run
状态只能使用 `pending/running/succeeded/failed/blocked/interrupted/cancelled`；`unknown`
只表示外部动作结果。脚本应优先
完成可重复的哈希、窗口、Schema、权限、幂等和报告渲染工作，AI 只负责解释和受约束的决策。
