---
name: weekly-fitness-summary
description: Inspect all-sport weekly FIT evidence, full successful M12 report history and bounded technical details for a running-focused weekly review. Never depend on daily health reports.
---

# 每周运动证据与技术总结

使用[周证据](../../docs/fit-weekly-evidence.md)、[周输入](../../docs/weekly-context.md)和[受限细读](../../docs/fit-detail.md)。本Skill不建立第二个模型任务或重新调用Provider。

- 本周全部实际运动都要保留，包括计划外运动；最多四份新库中可验证的完整成功M12周报，不从旧M11报告充数。
- 周期按香港前后两次周日15:00半开窗口、活动结束时间归属；活动清单、统计和下周日期由Host提供。
- 跑步Easy/未知2分钟摘要，明确SOS保留work/recovery圈段、连续主训练1分钟，其他运动5分钟。暂停、缺口、覆盖率不能藏在均值里。
- 需要细节时，仅请求已冻结活动及允许视图；每周20次、单次20分钟，相同请求缓存，不获得原FIT字节、任意路径或SQL。
- 最多三项重点跑步技术复盘必须说明证据、方法及局限；无法证明间歇结构、因果关系或攀岩强度时明确未知。
- GPS、路线、地点和活动名称允许在真实来源闭合时进入选定AI，仍为私人资料；不从GPS推断天气或把两端点当完整路线。
- 周报告保留全部运动、其他运动影响、简短计划实际对比及固定下周跑步计划。无健康API、每日AI、日报前置或原始目录回退。

输入/解析基础已实现；完整教练结果合同仍按当前M12计划交付，不能把证据冻结成功宣称为周报已完成。
