# TrainLab 运行 Skills

`source/AGENTS.md` 是运行入口；本文件是索引。每次无状态运行先读这里，再只读本次任务
所需的 `SKILL.md`。根目录 `skills/` 是开发 Harness，不能混用；`_shared/` 没有 `SKILL.md`，
不是可触发 Skill。

| Skill | 作用 | 触发 | 读取 | 写入/外部副作用 |
| --- | --- | --- | --- | --- |
| `garmin-sync` | 昨日健康/活动与今晨主睡眠的有界 raw 同步 | 自动运行、获批补数或冻结的单次在线范围 | SQLite、raw、Garmin MCP | raw + SQLite；每次在线调用需精确批准 |
| `training-coach` | 日总结，或周总结与跑攀课表 | 用户或定时 AI 输入 | goal、SQLite 输出、脚本有界证据 | SQLite；不调用外部服务 |
| `weekly-fitness-summary` | 周训练与恢复趋势复盘 | 周教练按需调用 | 7 日总结、4 周总结 | SQLite 输出；不调用外部服务 |
| `garmin-training-sender` | 管理已拥有的 `-GTS` My Workouts 与日历 | 已批准课表 | 课表输出、批准、动作状态、Garmin MCP | SQLite + Garmin 写入（默认关闭；仅精确批准范围启用） |
| `training-report-publisher` | 生成人类可读 HTML/text 与私有 CID 图表 | 教练完成后 | 已验证 Skill 输出、显式 ViewModel | SQLite；Sites 本阶段关闭 |
| `gmail-sender` | 有界查询、收件和自投递 | 报告发布后 | 精确邮件输出、批准、动作状态、Gmail REST | SQLite + Gmail 写入（默认关闭；仅精确批准范围启用） |

所有 Skill 必须：

- 使用稳定错误码记录 `pending/running/succeeded/failed/blocked/interrupted/cancelled`；
- `unknown` 只表示 `external_actions` 的外部结果，不能写入 Skill run 状态；
- 通过共享脚本写入 `state/trainlab.db`，输出不可覆盖；
- 不把 raw 正文、FIT 样本、token、收件地址或隐藏推理写入上下文；
- 外部动作执行前记录 `prepared → external_barrier`，结果不确定时保持 `unknown`。

本阶段只保留一个供无状态运行读取的自动 Prompt，不安装或启用 cron：

- `source/skills/_shared/prompts/auto.txt`：不接受日期、模式或 request-id；槽位由确定性
  resolver 按 `Asia/Hong_Kong` 计算。

公开运行形式：

```text
codex exec -C /absolute/path/to/source --ephemeral - < /absolute/path/to/source/skills/_shared/prompts/auto.txt
```

`--output-schema` 只用于测试或外部程序读取最终回执，SQLite 中的
`workflow_receipt_v1` 才是下一次运行的事实源。

M9 的一次性恢复入口另有版本化证据链：公开合成 Schema canary 通过后，才允许唯一的私人
attempt 4；它不是普通自动运行接口，不改变 `auto.txt`，也不授权 Garmin 或其他外部动作。

M10 的滚动七日验收使用 `garmin-sync/scripts/rolling_week_sync.py` 在仓库外 Candidate 中补齐
固定窗口；`training-coach/scripts/run_rolling_week.py` 生成 7 份日报、1 份周报和邮件/GTS
prepared 合同。`_shared/scripts/m10_external_actions.py` 只建立精确确认清单与 SQLite 动作账本；
真实 Gmail/Garmin 写入仍需当前 exec plan 的用户确认门。Provider host 只允许执行
`operation=mcp_tool_call` 且带 `m10_external_mcp_call_v1` 完整信封的 run；普通 `send_email`、
`apply_weekly_plan` 或其他离线输出 run 永远不构成 MCP 调用授权。

M10 r06 的一次性 Gmail 续跑改用 `gmail-sender/scripts/gmail_rest_delivery.py`：通过官方 Gmail
REST API、稳定 RFC822 Message-ID 和 RAW 读回在新 Candidate 中串行投递。它禁止 Gmail MCP、
SMTP 与 Connector 回退；第一封 canary 必须经 API 与用户双重确认后才能继续余下 7 封。
M10 r07 使用 `gmail-sender/scripts/gmail_rest_continuation.py`保留已收到的旧标题
canary，以 Gmail ID + RAW 实际 Message-ID 做零 Provider 追加对账；只为其余6份日报
和1份周报建立新标题动作，累计始终为8封，不允许第9封。
M10 r08 复用同一参数化 continuation 状态机：保留r07旧8封，新增8个更正标题请求；第一封
更正邮件为canary，用户确认前其余7封不可领取，完成后累计恰好16封。

M11 新增 `daily_email_view_v1`/`weekly_email_view_v1` 与 email render v2：仅显式映射获批字段，
只从真实数组生成确定性 PNG 并以内联 CID 附件绑定 MIME。owner-only Candidate 预览和 Fake
REST 已通过；A-014 另以 `recent_health_metrics_v1` 为 VO₂ Max/体重选择30/14天内最近有效值
并显示测量日期。`gmail_readable_live.py` 只承载用户精确批准的历史日报、修正版日报和周报，
修正版日报获得网页和手机人工确认前不得发送周报，也不得接入普通运行入口。

M11 v4 按 A-018 建立 content-first 路径：每日完整观察证据与读者可见日报分离；日报仅展示
昨日事实、健康/恢复分析和周计划中的固定课程，不再输出有效调整。周报从连续七份完整观察证据
分析全部计划内外活动、健康与有界 FIT 技术指标，再生成唯一固定七日计划。v4 只生成 Markdown、
低保真 HTML 和 OpenDesign 交接材料；当前不切换 `auto.txt`、不生成 MIME 或调用外部动作。
VC-002 进一步固定每日六类健康事实的 `available/missing/insufficient_data` 三状态，以及技术指标
对 activity ID、raw ID、raw SHA 和 metric code 的逐活动闭包；周证据必须连续七日共 42 项。
VC-006 将私有 `goal.md` 在 Host 边界按公开模板的1个标题、5个章节和19个有序字段确定性解析为
`training_goal_v1`，v4 模型只接收 Context v2 中的结构化业务值；强度说明、Markdown 正文、
文件名以及相对/绝对项目路径均不得进入 Prompt。Prompt模板、目标模板和Schema均独立绑定权威SHA。
