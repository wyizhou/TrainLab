# M4 迁移验收摘要

当前工程采用四个严格串行任务：source 工程与历史运行层清理、Foundation v4 离线
Garmin 重建、运行时教练 Harness v2、私人数据原子切换与独立验证。

验收必须证明：根目录没有第二份产品源码；`source/index.py` 从任意工作目录导入
`source/src`；新库只含 Garmin 离线事实；日报/周报严格遵循睡眠和课程合同；完整
pytest、静态门、schema、隐私和只读 Validator 均通过。

本计划不调用 Garmin/Gmail，不发送报告，不提交或推送。
