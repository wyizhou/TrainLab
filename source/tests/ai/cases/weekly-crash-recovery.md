# AI case: 周日日报后崩溃恢复

| case | expected | actual | verdict | evidence |
|---|---|---|---|---|
| `weekly-crash-recovery` | 重入时复用已完成 daily receipt，只继续 weekly，不重复输出或外部动作 | 待按需运行 | REVIEW | workflow key 与 SQLite 修订 |
