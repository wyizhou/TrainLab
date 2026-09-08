---
name: weekly-fitness-summary
description: Inspect all-sport weekly FIT evidence, full successful M12 report history and bounded technical details for a running-focused weekly review. Never depend on daily health reports.
---

# 每周运动证据与技术总结

使用[周证据](../../docs/fit-weekly-evidence.md)、[两阶段周输入](../../docs/weekly-stages.md)和[受限细读](../../docs/fit-detail.md)。先plan规划成功，才进入独立summary阶段；本Skill不另外领取第三次调用或重新调用Provider。

- 本周全部实际运动都要保留，包括计划外运动；最多四份新库中可验证的完整成功M12周报，不从旧M11报告充数。
- 周期按香港前后两次周日15:00半开窗口、活动结束时间归属；活动清单、统计和下周日期由Host提供。
- 跑步Easy/未知2分钟摘要，明确SOS保留work/recovery圈段、连续主训练1分钟，其他运动5分钟。暂停、缺口、覆盖率不能藏在均值里。
- 需要细节时，仅请求已冻结活动及允许视图；与规划共享每周20次、单次20分钟，相同获准请求缓存。规划只能读跑步session，总结可读全部运动；不获得原FIT字节、任意路径或SQL。
- 最多三项重点跑步技术复盘必须说明证据、方法及局限；无法证明间歇结构、因果关系或攀岩强度时明确未知。
- GPS、路线、地点和活动名称允许在真实来源闭合时进入选定AI，仍为私人资料；不从GPS推断天气或把两端点当完整路线。
- 周报告保留全部运动、其他运动说明、不确定性、简短计划实际对比及已验证固定下周跑步计划，不修改/替代计划、不按其他运动负荷改课。总结独立running_analysis字段由R3业务校验，历史只取可验证独立跑步分析和原计划。无健康API、每日AI、日报前置或原始目录回退。

输入/解析基础已实现；完整教练结果合同仍按当前M12计划交付，不能把证据冻结成功宣称为周报已完成。
