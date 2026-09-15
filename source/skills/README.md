# 产品本地能力

当前业务入口是 `python -m skills._shared.fit_weekly`，从 `source/` 运行，使用显式0700实例根和0600私有配置。
[fit-weekly](fit-weekly/SKILL.md)说明入口职责；完整命令与授权见[统一入口](../docs/fit-weekly-entrypoint.md)。

`_shared/fit_weekly/` 是当前FIT同步、分段、两阶段模型、Markdown/PDF、发布和香港调度实现；
`_shared/scripts/` 仅保留 Schema 与严格 wire 公共工具。目标正文由 `fit_weekly/weekly_context.py` 冻结校验；旧结构化目标仅保留历史 Schema。
`garmin-sync/scripts/mcp_server_guard.py`和`garmin-sync/references/live-overrides.txt`是现行Garmin会话的缓存认证保护，禁止自动登录或下载其他数据类型。
`gmail-sender/scripts/gmail_rest_auth.py`及`gmail_rest_common.py`只作显式独立OAuth维护，不负责邮件发布，也不自动运行。

旧日报、Candidate、复杂HTML/CID、固定批次和auto入口已退出；必要历史读取仅由显式import-history加载。
所有产品Skill仅在本仓库使用，不复制或安装到全局。大功能总览见[PLAN.md](../../PLAN.md)，整体独立验收、暂停与真实调用的批准证据见[M12 执行计划](../../exec-plans/active/M12-fit-weekly.md)；稳定要求见[现行产品合同](../../docs/product-contract.md)，读取文档不产生真实调用授权。
