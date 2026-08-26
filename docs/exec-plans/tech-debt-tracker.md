# 技术债跟踪表

主协调 Agent 可以记录有仓库证据、但不阻塞当前正确性、安全和交付的问题，不得自行安排
实施或借此扩大当前任务范围。

只有人工可以把候选设为 `accepted`、`deferred`、`rejected`，或提升为 `promoted`。
提升为长期目标时关联 `PLANS.md` 任务；批准立即处理时关联独立 exec plan。

状态使用 `candidate`、`accepted`、`deferred`、`rejected`、`promoted` 和 `resolved`。

| ID | 来源任务 | 发现与证据 | 影响与范围 | 建议行动 | 状态 | 人工决定 | Roadmap/Exec plan |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TD-0001 | M4-0004 / M4 运行源码类型门禁修复 | `cd source && python -m mypy src` 已为 0；同一范围外的 tests/tools 类型检查仍有约 522 项历史诊断，未通过忽略或排除隐藏 | 不阻塞当前源码运行门；测试/工具类型审计价值较低，后续修改这些目录时仍可能漏报边界错误 | 单独评估 tests/tools 的类型债；先按功能风险分批修复并保留完整 pytest、Ruff 和编译门 | candidate | 待人工决定是否提升为独立任务 | M4 / 后续独立 exec plan |
| TD-0002 | M10-0004 / Gmail REST canary 人工收件复核 | `training-report-publisher/scripts/render_report.py` 的通用 `body_html` 会将 `bounded_metrics`、`evidence_ref` 等严格 JSON 字段直接展示 | 不影响 AI 结果、证据、邮件传输或账本正确性，但日报/周报邮件不适合日常阅读 | 以版本化中文 ViewModel、显式字段映射、单位转换和低视觉权重审计区重建展示；底层 JSON 继续作为事实与审计证据 | promoted | M11 v3离线实现和三类Validator已PASS；只有未来真实 canary 通过后才能由用户决定是否改为resolved | M11 / `docs/exec-plans/completed/M11-email-presentation-0001-readable-cid.md` |
