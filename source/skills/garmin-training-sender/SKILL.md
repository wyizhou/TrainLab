---
name: garmin-training-sender
description: Inspect the current fixed running-plan publication contract for Garmin Connect Workouts and calendar entries. Only exact IDs recorded by the new M12 ledger establish ownership.
---

# Garmin 跑步课程与日历

遵守[产品边界](../../AGENTS.md)。M12实际课程发布器尚未交付，不得用旧prepare_gts或固定演练批次代替；历史批准不授权新写入。

- 来源必须是与周报/PDF相同的已验证固定七日计划，保留真实课程步骤和重复组。
- 创建后读回核对课程，再排期并读回日期；每天最多一个主课，休息日不创建Workout。
- 课程强度使用RPE、体感与获准历史参考，不生成目标BPM、自定义分区或阈值。
- 只管理新库精确记录的自有课程ID；名称或-GTS后缀本身不是所有权，不自动收养、删除或清理旧课程。
- 每项创建/排期动作独立持久化意图与结果；成功项不因邮件或另一项失败重做。
- unknown只能只读对账，不能自动再次创建、排期或删除。未确认失败不得写成功。
- 补发不排过去课程、不整体平移计划。首次真实发布每日最多一项、最多七项，实际范围另按当前批准预算。
- 不触碰已完成运动、非自有课程或其他服务。用户另行明确批准才可删除精确自有ID。
