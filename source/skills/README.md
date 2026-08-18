# TrainLab 运行 Skills

`source/AGENTS.md` 是运行入口；本文件是索引。每次无状态运行先读这里，再只读本次任务
所需的 `SKILL.md`。根目录 `skills/` 是开发 Harness，不能混用；`_shared/` 没有 `SKILL.md`，
不是可触发 Skill。

| Skill | 作用 | 触发 | 读取 | 写入/外部副作用 |
| --- | --- | --- | --- | --- |
| `garmin-sync` | 昨日健康/活动与今晨主睡眠的有界 raw 同步 | 自动运行、获批补数或冻结的单次在线范围 | SQLite、raw、Garmin MCP | raw + SQLite；每次在线调用需精确批准 |
| `training-coach` | 日总结，或周总结与跑攀课表 | 用户或定时 AI 输入 | goal、SQLite 输出、脚本有界证据 | SQLite；不调用外部服务 |
| `weekly-fitness-summary` | 周训练与恢复趋势复盘 | 周教练按需调用 | 7 日总结、4 周总结 | SQLite 输出；不调用外部服务 |
| `garmin-training-sender` | 管理已拥有的 `-GTS` My Workouts 与日历 | 已批准课表 | 课表输出、批准、动作状态、Garmin MCP | SQLite + Garmin 写入（本阶段关闭） |
| `training-report-publisher` | 生成 open_report/fixed_email HTML | 教练完成后 | 已验证 Skill 输出、模板 | SQLite；Sites 本阶段关闭 |
| `gmail-sender` | 有界查询、收件和自投递 | 报告发布后 | 精确邮件输出、批准、动作状态、Gmail MCP | SQLite + Gmail 写入（本阶段关闭） |

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
