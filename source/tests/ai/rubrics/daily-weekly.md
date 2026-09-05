# AI 评测量规

| case | expected | actual | verdict | evidence |
| --- | --- | --- | --- | --- |
| daily-normal | 日期/睡眠边界正确，引用有界证据 | 待运行 | REVIEW | 待运行 |
| weekly-running-climbing | 课程安全、证据一致、无编造 | 待运行 | REVIEW | 待运行 |
| daily-v2-normal | 昨日训练和恢复解释清楚；原课与今日调整并列；只维持/降级；RPE可执行；无心率区间或编造 | 待运行 | REVIEW | 待运行 |
| daily-v2-caution | caution 只影响当日调整，不擅自取消整周SOS；降级理由和证据闭合 | 待运行 | REVIEW | 待运行 |
| weekly-v2-running-climbing | 健康和运动负荷总结完整；3–5条观察→意义→行动；七天详细课；正常hold恰好1节条件性SOS；硬课间隔≥3天 | 待运行 | REVIEW | 待运行 |
| weekly-v2-deload | 红旗或有证据明显恢复不足时可0节SOS，必须说明；不以caution单独取消 | 待运行 | REVIEW | 待运行 |

`REVIEW` 永远不算通过。确定性 Schema、安全、数量、日期差、哈希和 Provider=0 由 Code 测试判断；
AI Validator 只判断解释是否真正有帮助、是否忠于证据、课程是否能照着执行及是否编造。
