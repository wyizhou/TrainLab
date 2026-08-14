# 第三层：手动分析

分析是显式的一次性命令，不依赖后台调度器、Supervisor 或历史 `run` 命令。

```sh
python3.12 source/index.py analysis daily --report-date YYYY-MM-DD
python3.12 source/index.py analysis weekly --week-ending YYYY-MM-DD
python3.12 source/index.py analysis revise-plan --plan-id ID
```

运行时 Harness 位于 `source/src/resources/harness/analysis/`，输入必须是带 schema、
来源和 lineage 的有界 JSON。分析默认只生成本地结果；邮件交付需要额外的显式授权，
本迁移验证期间不执行。

日报把昨日活动与非睡眠指标、昨夜唯一已结束的主睡眠、以及今日正式计划课程分开
处理。它只评估计划，不修改周计划；没有有效计划时只能生成保守的临时建议。

周报必须覆盖完整周一至周日，周日数据未完成时延后；每周输出
`advance`、`hold` 或 `deload`，且一次只改变容量或强度中的一个维度。
