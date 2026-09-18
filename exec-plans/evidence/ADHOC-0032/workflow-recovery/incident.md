# ADHOC-0032-INFRA-001 工作流结果传递失败

- 日期：2026-09-18。
- 精确错误：`emit.outputPathMapping must be a JSON value; received undefined.`，发生在工作流脚本第 4 行。主 Agent 将不存在的可选字段直接放入 emit 对象，违反 JSON 输出要求；不是产品测试失败。
- 工作流：`c78e2e35-10d1-42a6-9f9e-fb0affa08773`，status 已核对为 `failed`；唯一子任务 `0032-restart-developer` / `d5e3c164-1798-4642-9d3e-aa4c1abdfd6f` 已 `completed`。Validator 未启动；无活动子任务。
- 仓库、cwd、worktree：项目根 `.`，现有共享功能工作区；没有创建隔离 worktree。分支 `work/adhoc-0031-local-web-system`，HEAD `a5893ac6eb8295cd8a60d8f2537bc213d1412885`。
- 现场：工作区原本有未提交改动，不回退、不清理。主 Agent 核对 76 个公开源文件，与恢复前快照完全一致。`source-snapshot.json` 保存 SHA256；`source-working.diff` 保存当前受跟踪产品差异；`untracked-source.zip` 保存 4 个未跟踪产品文件；`worktree-status.txt` 保存工作区状态。上述证据不含私人 states。
- 已完成结果：主 Agent 已读取 Developer 报告、mypy/pytest 原始脱敏日志和保全核对；非 editable 检查 54 文件、199 项测试通过，无产品修改。完整报告保存在 `../restart-developer-report.md`。独立验证和主验收仍未完成。
- 同协议恢复：删除不必要的中间 emit，只通过已支持的 `runs.run` 返回完整 JSON 子结果；先静态 validate，再在同一原生异步工作流协议中仅派发全新 Validator，使用原客观任务材料。不续聊、不重跑 Developer、不切换前台或外部执行模式。
- 累计失败：本类工作流基础设施失败 1；不计为产品修复失败。若恢复再次发生基础设施失败，先停止并保存具体证据，不循环重试。
