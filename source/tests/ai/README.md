# AI 语义验收

这里的案例只使用合成输入，不读取正式 `goal.md`、`state`、raw 或凭据，也不调用 Garmin、Gmail
或 Sites。确定性字段、Schema、状态机、哈希、权限和副作用由 `tests/code` 判断；AI 只评价解释
是否引用证据、训练安排是否合理、是否编造或越权。

结果统一为 `case | expected | actual | verdict | evidence` 表格；`PASS`、`FAIL`、`REVIEW` 三态
中，`REVIEW` 不算通过。`results/` 默认忽略，只有脱敏模板和纯合成 golden 可以跟踪。
