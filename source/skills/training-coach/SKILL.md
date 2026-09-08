---
name: training-coach
description: Review the current FIT-only weekly coaching contract and fixed running plan from source-bound activity evidence. Daily analysis and course adjustment are retired.
---

# 每周跑步教练

先按[产品边界](../../AGENTS.md)核对当前交付状态。[周输入](../../docs/weekly-context.md)与[模型适配](../../docs/codex-adapter.md)是现有基础；内部周报业务接口见[业务合同](../../docs/weekly-coaching.md)，发布尚未交付，不调用旧 M11 Runner 代替。

- 先按[两阶段接线](../../docs/weekly-stages.md)独立规划，再总结。规划仅本期跑步session、最多四份历史中可验证独立跑步分析/计划和目标快照；不读非跑步运动、混合全文或旧健康日报。
- Python提供统计、周期、下周一至周日日期和证据身份。AI负责解释和课程选择；只使用已冻结输入及受限FIT细读工具，不读取任意文件或数据库。
- 技术结论要与对应活动及指标证据绑定，最多详述三项跑步；其余运动列入完整清单，披露适用条件、缺失与不确定性。
- 计划仅为固定跑步/休息安排；逐课写清目的、剂量、步骤、重复组、RPE、技术备注和停止条件。只依据跑步与目标，不因攀岩/力量负荷调整跑课，不生成虚假的休息Workout。
- 硬负荷最多三次、日期差至少三天；不同时增加距离和强度、不补课或每日动态改课，没有依据不强行安排SOS。
- 设备记录的历史心率/分区可展示，不推算区间、阈值或目标BPM，也不作训练处方。运动表现不能证明没有健康风险。
- 业务Schema是结构来源；派生wire并检查Prompt一致性。每周plan、summary各最多一次独立无状态调用，共享20次/每次20分钟细读；规划仅跑步权限。失败/unknown不重试，无resume或聊天依赖。业务Schema和确定性校验见[业务合同](../../docs/weekly-coaching.md)；自由文字合理性不由结构检查证明。
- 不修改私人目标，不自行调用Garmin、Gmail或其他服务。目录/版本变化不重置旧任务预算或改写历史结果。
