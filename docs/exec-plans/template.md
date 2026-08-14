# 执行计划：<目标结果>

- 状态：`ready`
- 负责人：主协调 Agent
- Roadmap ID：`<stage-sequence>` 或 `ADHOC-<sequence>`
- 阶段/子项目：`<stage>/<initiative>` 或 `不适用`
- Batch ID：`<batch-id>` 或 `不适用`
- 返工来源：`无` 或 `<completed-plan>`
- 开始日期：YYYY-MM-DD
- 最后更新：YYYY-MM-DD

## 目标与验收标准

## 范围与非目标

## 适用规则与参考资料

- 已批准规则：
- 按需读取的 references：

## 依赖与隔离

- 显式依赖：
- 共享接口和冻结依据：
- 任务分支：`work/<task-id>-<feature-slug>` 或 `不适用`
- Worktree：`../<repo-name>-worktrees/<task-id>/` 或 `不适用`
- 集成分支：`integration/<stage-id>` 或 `不适用`
- 允许写入范围：
- 禁止写入范围：

## 功能与测试映射

| 功能 | Feature slug | 测试目录 | 必须满足的行为 |
| --- | --- | --- | --- |

未引入功能行为时填写“`不适用——治理或只读任务`”。TrainLab 新产品功能的测试目录为
`tests/<feature-slug>/`；既有测试保留当前布局。

## 工具采用情况

- 可执行技术栈：
- Linter 配置和命令：
- 测试框架、定向命令和完整命令：

## Subagent 派发

| Attempt | Agent 角色/任务 ID | 风险与复杂度 | 模型档位 | 推理档位 | 选档理由 | 平台支持 | 写入边界 | 产物与门禁 | 结果 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

档位只使用 `low`、`medium`、`high` 或 `platform-default`，不得在仓库文档中记录具体模型名。
升级 attempt 必须使用全新 Agent，并记录旧档位不足的事实证据。

## 工作分解

| 步骤 | 状态（`pending`、`in_progress`、`blocked`、`done`） | 证据 |
| --- | --- | --- |

## 当前检查点

- 当前 Loop：
- 最近完成：
- 当前焦点：
- 下一动作：
- 阻塞项：
- 已变更文件：
- 待验证项：

## 决策与发现

## 任务级独立验证

- 中性交接：
- Validator 身份/上下文：
- 模型/推理档位：
- 命令与观察：
- 结果：`pending`
- 未满足项与剩余风险：

## 集成级独立验证

- 集成范围：
- 中性交接：
- Validator 身份/上下文：
- 模型/推理档位：
- 完整 lint/test 与回归观察：
- 结果：`pending` 或 `不适用——无并行集成`
- 未满足项与剩余风险：

## PLANS 回写清单

- [ ] Exec plan 已归档到 `completed/`
- [ ] Roadmap 叶子任务已更新为 `[x] completed`
- [ ] 子项目和阶段状态已重新计算
- [ ] `memory.md` 中的活动计划指针已删除

非 Roadmap 的 ADHOC 任务将 Roadmap 相关项目标记为“不适用”。

## 迭代日志

| 日期/上下文 | 已完成事项与证据 | 发现 | 下一动作 |
| --- | --- | --- | --- |
