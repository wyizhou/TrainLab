# AI 语义验收

这里的案例只使用合成输入，不读取正式 `goal.md`、`state`、raw 或凭据，也不调用 Garmin、Gmail
或 Sites。确定性字段、Schema、状态机、哈希、权限和副作用由 `tests/code` 判断；AI 只评价解释
是否引用证据、训练安排是否合理、是否编造或越权。

结果统一为 `case | expected | actual | verdict | evidence` 表格；`PASS`、`FAIL`、`REVIEW` 三态
中，`REVIEW` 不算通过。`results/` 默认忽略，只有脱敏模板和纯合成 golden 可以跟踪。

当前语义材料只面向FIT-only双阶段计划/全运动总结、修订/发布与恢复；旧日报、健康合同、强制SOS和高保真邮件材料退出。AI语义验收未在R6-5调用真实模型；REVIEW始终不算通过。
