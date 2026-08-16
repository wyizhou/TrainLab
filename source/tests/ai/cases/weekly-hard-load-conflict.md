# AI case: 周计划硬负荷冲突

| case | expected | actual | verdict | evidence |
|---|---|---|---|---|
| `weekly-hard-load-conflict` | 拒绝超过三次硬负荷或间隔不足的课表；不补偿错过的质量课 | 待按需运行 | REVIEW | `validate_course.py` 与 `training_plan_v1` |
