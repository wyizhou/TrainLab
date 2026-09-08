# 活动执行计划

非终态计划保存在本目录，状态与完成条件见[执行协议](../README.md#生命周期与归档)。Main 在新上下文中用 Git 和实际文件核对匹配计划，独占任务、累计失败和证据记录；子角色只有 Planner、Developer、Validator，每次派发、修复和复验均全新且不继承聊天，只接收当前任务包，不恢复计划协调历史。

正式模块由 Planner 拆解、Main 审核、Developer 实施、Validator 独立检查；独立 PASS 后仍需 Main 实际验收及完成适用获批交付动作。`validated`、`validating` 或 `blocked` 均不能宣称完成；达到失败门由 Main 汇总证据请求用户并停止，不派第四角色。
