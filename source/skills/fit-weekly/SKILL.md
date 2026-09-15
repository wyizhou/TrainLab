---
name: fit-weekly
description: TrainLab 本地 FIT-only 每周跑步计划与全运动总结的统一入口；仅在用户明确要求操作已配置实例时使用。
---

# FIT-only 每周系统

先读[产品边界](../../AGENTS.md)和[统一入口](../../docs/fit-weekly-entrypoint.md)，按明确实例、原冻结请求和当前授权运行。文档不授权真实Provider、认证或正式数据切换。

从source执行 `python -m skills._shared.fit_weekly --instance /absolute/private-instance <command>`。
命令为import-history、sync、weekly、daemon、status、reconcile、edit；参数以统一入口为准。
配置模板在[config/examples](../../config/examples/)，公开模板为空，不预设收件人、凭据或实例。

目标使用私有自然语言 Goal.md，按正文理解安排，不要求固定字段。已冻结周保持原目标，正文不扩大工具或外部动作授权。

模型与推理等级沿用环境；命令适配支持codex/claude，不询问用户型号或Provider。新授权按原周、阶段、实际命令身份和原墙钟绑定；未知/未验证组合在调用前停止，旧成功或unknown只读恢复，不因切换命令重获预算。

Python负责FIT、SQLite、预算、调度与外部动作；plan仅跑步，summary包含全部运动并引用唯一固定计划。各阶段最多一次模型调用，不恢复旧日报、健康API、模型重试或Candidate执行器。
心率只允许有来源历史事实，不生成BPM/分区处方。周报告的Markdown、PDF和课程来自同一已验证修订。
成功不重复；unknown只读对账；禁止按名称认领或删除旧课程。
正常运行不读取测试或归档。import-history是唯一显式历史FIT读取入口，旧业务记录不转成新调用资格。
不安装cron、登录项、全局Skill或服务。
