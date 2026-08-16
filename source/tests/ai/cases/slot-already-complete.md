# AI case: 已完成槽位重复运行

| case | expected | actual | verdict | evidence |
|---|---|---|---|---|
| `slot-already-complete` | resolver 返回 `no_due`，不新增 Skill run、output 或 action | 待按需运行 | REVIEW | `resolve_slot.py` receipt |
