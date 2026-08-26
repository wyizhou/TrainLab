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

## 冻结验证合同

- 合同版本：`VC-001`
- 合同状态：`draft`、`frozen` 或 `superseded`
- 冻结依据：`<用户明确请求或已批准计划及日期>`
- 冻结时点：`<必须早于 Worker 开始修改>`

用户明确提出任务或批准计划时，同时批准初始合同。开始实现前将状态改为 `frozen`；冻结后不得静默修改。

### 验收标准

| ID | 必须满足的结果 |
| --- | --- |
| `AC-001` | `<可验证结果>` |

### 行为不变量

| ID | 必须始终成立的行为 |
| --- | --- |
| `INV-001` | `<跨测试用例仍需成立的语义>` |

### 威胁模型

| ID | 范围内的参与者、输入、故障或攻击能力 |
| --- | --- |
| `TM-001` | `<范围内风险；不适用时写明理由>` |

### 明确排除项

| ID | 不属于当前交付的场景 |
| --- | --- |
| `EX-001` | `<排除场景及理由>` |

### Lint/Test 与静态门禁

| ID | 命令或检查 | 预期结果 |
| --- | --- | --- |
| `GATE-001` | `<command/check>` | `<expected>` |

### 合同修订记录

| 版本 | 状态 | 变更、理由与受影响标准 | 人工批准依据 |
| --- | --- | --- | --- |
| `VC-001` | `frozen` | 初始冻结合同 | `<approval>` |

合同升级时不得删除或覆盖旧修订记录。新版本生效后，旧版本 Validator 结果失效；新增或修改的标准必须记录人工明确批准依据。

## 依赖与隔离

- 显式依赖：
- 共享接口和冻结依据：
- 任务分支：`work/<task-id>-<feature-slug>` 或 `不适用`
- Worktree：`../<repo-name>-worktrees/<task-id>/` 或 `不适用`
- 集成分支：`integration/<stage-id>` 或 `不适用`
- 允许写入范围：
- 禁止写入范围：

## 功能与测试映射

| 功能 | Feature slug | 测试目录 | 合同标准 | 必须满足的行为 |
| --- | --- | --- | --- | --- |

未引入功能行为时填写“`不适用——治理或只读任务`”。TrainLab 新运行功能测试使用
`source/tests/code/{unit,contract,integration,fixtures}/` 和 `source/tests/ai/`；既有测试保留当前布局。

## 工具采用情况

- 可执行技术栈：
- Linter 配置和命令：
- 测试框架、定向命令和完整命令：

## Subagent 派发

| Attempt | Agent 角色/任务 ID | 合同版本 | 风险与复杂度 | 模型档位 | 推理档位 | 选档理由 | 平台支持 | 写入边界 | 产物与门禁 | 结果 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

档位只使用 `low`、`medium`、`high` 或 `platform-default`，不得记录具体模型名称。升级 attempt 必须使用全新 Agent，并记录旧档位不足的事实证据。

Failure Analyst 固定使用 `high/high`，必须是全新、只读且未参与实施的 Agent。它可以接收相关尝试历史用于归因，但不得替代 Validator 或裁决 `PASS`。

## 工作分解

| 步骤 | 状态（`pending`、`in_progress`、`blocked`、`done`） | 证据 |
| --- | --- | --- |

## 当前检查点

- 当前 Loop：
- 最近完成：
- 当前焦点：
- 下一动作：
- 阻塞项：
- blocker_type：`none`、`DIAGNOSIS_PENDING` 或失败归因类别
- 诊断状态：`not_triggered`、`pending`、`in_progress` 或 `completed`
- 已变更文件：
- 待验证项：

## Validator 结论处理

| Loop | Validator 身份 | 合同版本 | 结论 | 绑定标准与证据 | 主协调 Agent 处理 | 是否触发诊断 | 下一 Validator |
| --- | --- | --- | --- | --- | --- | --- | --- |

- `PASS`：全部适用标准和门禁通过，进入集成、归档或下一任务。
- `FAIL`：记录绑定标准、证据和失败特征；未达到诊断条件时修复明确实施错误，达到条件时停止修改并启动 Failure Analyst。
- `INCONCLUSIVE`：不得直接修改实现；记录未知项，补证据、等待环境变化或请求人工澄清。直接发现合同冲突时启动 Failure Analyst。
- 新 Validator 不接收本表中的历史 verdict、推理或结论；本表只供主协调 Agent 恢复状态和判断诊断条件。

## 失败尝试与诊断

失败次数按“任务 + 合同版本 + 失败特征”累计。失败特征由关联标准 ID 和可观察的不符合结果构成；只有该特征消除或合同升级后才重置。

| Failure ID | 合同版本 | 标准 ID | 失败特征 | Loop | 修法或验证尝试 | 是否实质不同 | 证据 | 结果 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

满足“两种实质不同修法仍失败”“三轮没有收敛”或“直接发现冲突”任一条件时，立即停止修改、将任务设为 `blocked` 并启动 Failure Analyst。实质不同必须体现不同根因假设或行为路径。

### Failure Analyst 固定输出

```text
failure_id
failure_class
criterion_ids
failure_signature
trigger
attempts_compared
evidence
minimal_conflict_set
contract_change_required
safe_auto_fix
recommended_actions
confidence
```

- `failure_class` 只允许 `IMPLEMENTATION_DEFECT`、`PLAN_CONTRACT_CONFLICT`、`VALIDATION_DEFECT`、`ENVIRONMENT_FAILURE` 或 `UNDETERMINED`。
- Failure Analyst 可以读取相关实施尝试和历史失败证据，但不得修改文件、改变合同或测试、替代 Validator 或返回 `PASS`。
- 只有 `IMPLEMENTATION_DEFECT` 且 `safe_auto_fix=true` 时，才允许在原合同和范围内进行一次诊断后修复；相同失败特征仍存在时改为 `UNDETERMINED`。
- `PLAN_CONTRACT_CONFLICT` 必须提供最小冲突集合与互斥方案，人工批准后才能升级合同。
- `VALIDATION_DEFECT` 不触发实现修改；`ENVIRONMENT_FAILURE` 只有外部状态变化后才能重试一次；`UNDETERMINED` 保持 `blocked`。

## 决策与发现

## Validator 固定输出

Validator 必须原样声明以下字段：

```text
contract_version
overall_verdict
criterion_results
blocking_findings
advisories
scope_change_candidates
unknowns
commands_and_evidence
```

- `blocking_findings` 每一项必须绑定适用的 `AC-*`、`INV-*`、`TM-*`、`RULE-*` 或 `GATE-*`。
- 命中 `EX-*` 或超出冻结范围的发现只能进入 `advisories` 或 `scope_change_candidates`。
- 标准含糊、证据不足、必要检查无法运行或阻塞项未绑定标准时，`overall_verdict` 必须为 `INCONCLUSIVE`。

## 任务级独立验证

- 逐字冻结合同版本：
- 中性交接：`仅冻结合同、适用规则和当前仓库结果`
- Validator 身份/上下文：
- 模型/推理档位：
- `criterion_results`：
- `blocking_findings`：
- `advisories`：
- `scope_change_candidates`：
- `unknowns`：
- `commands_and_evidence`：
- `overall_verdict`：`pending`
- 未满足项与剩余风险：

## 集成级独立验证

- 集成范围：
- 逐字冻结合同版本：
- 中性交接：`仅冻结合同、适用规则和当前仓库结果`
- Validator 身份/上下文：
- 模型/推理档位：
- `criterion_results`：
- `blocking_findings`：
- `advisories`：
- `scope_change_candidates`：
- `unknowns`：
- `commands_and_evidence`：
- `overall_verdict`：`pending` 或 `不适用——无并行集成`
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
