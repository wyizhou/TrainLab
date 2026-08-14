# 技术债跟踪表

主协调 Agent 可以记录有仓库证据、但不阻塞当前正确性、安全和交付的问题，不得自行安排
实施或借此扩大当前任务范围。

只有人工可以把候选设为 `accepted`、`deferred`、`rejected`，或提升为 `promoted`。
提升为长期目标时关联 `PLANS.md` 任务；批准立即处理时关联独立 exec plan。

状态使用 `candidate`、`accepted`、`deferred`、`rejected`、`promoted` 和 `resolved`。

| ID | 来源任务 | 发现与证据 | 影响与范围 | 建议行动 | 状态 | 人工决定 | Roadmap/Exec plan |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TD-0001 | M4-0004 / M4 运行源码类型门禁修复 | `cd source && python -m mypy src` 已为 0；同一范围外的 tests/tools 类型检查仍有约 522 项历史诊断，未通过忽略或排除隐藏 | 不阻塞当前源码运行门；测试/工具类型审计价值较低，后续修改这些目录时仍可能漏报边界错误 | 单独评估 tests/tools 的类型债；先按功能风险分批修复并保留完整 pytest、Ruff 和编译门 | candidate | 待人工决定是否提升为独立任务 | M4 / 后续独立 exec plan |
