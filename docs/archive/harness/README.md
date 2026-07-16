# 旧三角色 harness 归档

本目录保存 TrainLab 在 Claude Code 三角色实验阶段产生的历史材料，包括旧 contract 协商提案和已完成需求记录。

这些文件只用于追溯，不再是 Codex 的工作指令，也不参与任务调度。当前规则见根 `AGENTS.md`，当前状态见 `docs/project-state.json`。

2026-07-16 前端工程迁入 `frontend/`。本归档为保留历史事实不机械改写旧路径；历史记录中的根 `src/`、`tests/`、`package.json` 和前端配置，在当前结构中分别对应 `frontend/src/`、`frontend/tests/`、`frontend/package.json` 和 `frontend/` 下同名配置。

旧记录中的 `design/...` 和 `src/design/...` 同样只表示当时的历史事实。仓库后来不再保存原型导出包，前端样式迁至 `frontend/src/styles/`；旧设计文件如需追溯应从 Git 历史读取，不得把归档路径当作当前设计输入。

- `contract-pending/`：design_rev 1～4 的 Planner / Validator 协商历史。
- `requirements/`：旧 Executor / Validator 流程产生的 40 份 verified 需求记录。
