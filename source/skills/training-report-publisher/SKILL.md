---
name: training-report-publisher
description: Prepare the current Markdown and PDF output contract from one validated FIT-only weekly result. High-fidelity HTML email, daily reports and Sites publishing are retired.
---

# 周报 Markdown / PDF

遵守[产品边界](../../AGENTS.md)。内部输出与修订接口见 [R4 周报](../../docs/weekly-reports.md)。完整运行命令和真实发布尚未交付；不得用旧 HTML/CID 渲染器或旧 Candidate 作为默认回退。

- 只接收同一已验证结构化周报及固定七日计划；不改变AI结论、事实、证据或安全判断。
- 同一结果生成Markdown、PDF和后续邮件/Garmin合同；PDF检查全部页面的中文、必要图表与课程可读性。
- 使用 `report_revisions.edit` 明确基础修订、SHA、编辑目标及新身份；只发生在发布前，形成新修订并重新校验、渲染及绑定SHA。不覆盖原AI结果或已发送内容，不因此重新调用模型。
- 无真实数组不画数据图；历史设备心率只作事实，不生成BPM/分区处方。
- 私人报告仅保存到owner-only实例；不公开到Sites、Git或其他网站。
- 后续发布必须先 `report_artifacts.seal` 固定唯一版本，再由所有渠道读取 `read_sealed`；封存不可重置，不用 latest，不因编辑或 unknown 重获外部动作授权。
- 本Skill不发送邮件、不创建Workout、不读健康API，也不要求七份日报或高保真设计模板。
