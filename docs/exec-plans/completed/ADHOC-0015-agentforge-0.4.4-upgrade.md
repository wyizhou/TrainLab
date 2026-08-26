# 执行计划：升级 agentForge v0.4.4 并迁移 M11 诊断状态

- 状态：`completed`
- 负责人：主协调 Agent
- Roadmap ID：`ADHOC-0015`
- 阶段/子项目：`不适用`
- Batch ID：`serial-agentforge-v044`
- 返工来源：`docs/exec-plans/completed/ADHOC-0001-agentforge-0.4.2-upgrade.md`
- 开始日期：2026-08-24
- 最后更新：2026-08-24

## 目标与验收标准

将 TrainLab 根开发 Harness 从 agentForge `v0.4.2` 三方适配到正式 `v0.4.4`，引入冻结
验证合同、固定 Validator 输出、失败诊断门和 Failure Analyst，同时完整保留 TrainLab 的
`source/` 产品边界、既有 A-001～A-018、当前 M11 工作和私人数据边界。当前 M11 只迁移为
`DIAGNOSIS_PENDING`，不在本任务实施诊断或产品修复。

## 范围与非目标

- 允许写入：根 Harness 治理文档、exec-plan 说明/模板、第三方声明、本计划和当前 M11 active plan。
- 禁止写入：`source/` 全部产品代码/测试/配置/state/凭据、M11 实现、Git index/commit/branch/
  worktree/remote，以及 agentForge 上游 completed plans、示例 memory 和占位项目树。
- 不运行 Failure Analyst，不建立 M11 Candidate，不调用 Codex、Garmin、Gmail、Workout、Sites
  或 cron。

## 适用规则与参考资料

- 已批准规则：A-001～A-018；本任务经用户批准新增 A-019，只替代 A-003 的当前版本固定事实。
- 上游来源：agentForge `v0.4.4`，Tag 对象
  `34f548d4fbf31d7850388b40997edaa4eb33ebad`，Commit
  `00e03cfb6e25e35967e414bea9233dc7b33929d5`。
- 按需读取的 references：无。

## 冻结验证合同

- 合同版本：`VC-001`
- 合同状态：`frozen`
- 冻结依据：用户于 2026-08-24 明确批准《ADHOC-0015：agentForge v0.4.4 Harness
  升级与 M11 诊断迁移》并要求实施。
- 冻结时点：2026-08-24，早于任何仓库内 Harness 修改。

### 验收标准

| ID | 必须满足的结果 |
| --- | --- |
| `AC-001` | 当前 Harness 精确绑定 v0.4.4 Tag/Commit，六个上游变更文件的每项差异均有 adopted/adapted/not_applicable 结论。 |
| `AC-002` | 根治理完整采用冻结合同、固定 Validator 输出、FAIL/INCONCLUSIVE 边界、失败诊断门和五类 Failure Analyst 归因。 |
| `AC-003` | TrainLab 的 source 产品边界、A-001～A-018、Skills/隐私/Git/零外部动作规则不被覆盖或弱化。 |
| `AC-004` | 当前 M11 active plan 以透明 legacy transition 冻结面向未来工作的 VC-001，并保持 blocked/DIAGNOSIS_PENDING/pending。 |
| `AC-005` | 完整 MIT 文本、上游版本和“不重新许可 TrainLab 产品”范围声明闭合。 |
| `AC-006` | 全部 Harness 静态门、source 完整回归、正式 state 前后指纹和独立 Validator 均通过。 |

### 行为不变量

| ID | 必须始终成立的行为 |
| --- | --- |
| `INV-001` | 本任务不修改 source、正式 state、私人配置或任何 M11 实现。 |
| `INV-002` | 未绑定冻结标准的 blocker 必须为 INCONCLUSIVE；TM/EX 外发现只能 advisory/scope candidate。 |
| `INV-003` | Validator 只接收冻结合同、适用规则和当前结果；只有 Failure Analyst 可以读取失败历史。 |
| `INV-004` | 不复制上游历史计划、示例项目事实或静态 src/tests 占位，不提交、不推送。 |

### 威胁模型

| ID | 范围内风险 |
| --- | --- |
| `TM-001` | 当前 115 个未提交文件可能在三方适配中被覆盖、遗漏或错误纳入。 |
| `TM-002` | 机械覆盖上游模板可能删除 TrainLab 项目级 source、隐私、测试和外部动作边界。 |
| `TM-003` | Validator 可能新增未冻结要求、读取历史 verdict 或把 INCONCLUSIVE 当成实现 FAIL。 |
| `TM-004` | 当前 M11 历史先于 v0.4.4，迁移时可能被错误描述为事前已冻结合同。 |

### 明确排除项

| ID | 不属于当前交付的场景 |
| --- | --- |
| `EX-001` | M11 Failure Analyst、r10 修复、真实 Candidate、模型调用或邮件。 |
| `EX-002` | agentForge 发布、上游仓库修改、TrainLab commit/push/branch/worktree。 |
| `EX-003` | source 运行 Harness、业务 Schema、产品测试或私人数据迁移。 |

### Lint/Test 与静态门禁

| ID | 命令或检查 | 预期结果 |
| --- | --- | --- |
| `GATE-001` | v0.4.4 Tag/Commit、上游 clean checkout、六文件差异映射 | 精确匹配且无遗漏 |
| `GATE-002` | 仓库外快照、SHA 清单和恢复演练 | 115 项闭合、owner-only、restore_verified=true |
| `GATE-003` | Markdown 链接、Mermaid 围栏、术语/版本/许可证一致性 | 全部通过 |
| `GATE-004` | `pytest tests/code`、Ruff、format、mypy、只读 AST/JSON/metadata/隐私 | 全部通过 |
| `GATE-005` | Git 范围、ignore、权限、`git diff --check` | 无 source 新改动、无私人内容、无空白错误 |
| `GATE-006` | 正式 state before/after 指纹 | 完全一致 |
| `GATE-007` | 全新只读 high/high Validator | 固定结构 `PASS` |

### 合同修订记录

| 版本 | 状态 | 变更、理由与受影响标准 | 人工批准依据 |
| --- | --- | --- | --- |
| `VC-001` | `frozen` | 初始升级与 M11 诊断迁移合同 | 用户于 2026-08-24 明确批准并要求实施 |

## 依赖与隔离

- 显式依赖：Git 可用；TrainLab HEAD `b172f95b9c6d1c01b71f3c00e447facffa55540b`；
  agentForge 本机 clean checkout 与 GitHub 均解析到固定 v0.4.4。
- 保护快照：`/private/tmp/trainlab-agentforge-v044-preupdate.neh11qs8`，115 项、恢复演练
  通过；正式 state before SHA
  `7cc9f67d5e31c4aa16d5fa2eaacdf3b20b7f2f5515a093d9623db32f35030f43`。
- 任务分支/Worktree/集成分支：不适用——用户明确禁止。
- 允许写入范围：见“范围与非目标”；所有修改严格串行。

## 功能与测试映射

`不适用——纯治理 Harness 升级，不引入产品功能行为。`

## 工具采用情况

- 可执行技术栈：Markdown/JSON 治理文档；现有 Python source 回归门。
- Linter/测试：source 既有 pytest、Ruff、format、mypy、AST/Schema/metadata/隐私门；
  根 Markdown/链接/Mermaid/术语/许可/Git 范围静态检查。

## Subagent 派发

| Attempt | Agent 角色/任务 ID | 合同版本 | 风险与复杂度 | 模型档位 | 推理档位 | 写入边界 | 产物与门禁 | 结果 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Validator / ADHOC-0015 | VC-001 | 高：跨治理适配与当前脏工作区保护 | high | high | 只读 | 固定输出、全部 AC/INV/TM/EX/GATE | PASS |

## 工作分解

| 步骤 | 状态 | 证据 |
| --- | --- | --- |
| 固定上游与保护当前工作区 | `done` | v0.4.4 Tag/Commit 双重核对；115 项快照和恢复演练通过 |
| 三方适配六个上游核心文件 | `done` | 六项均为 adapted；TrainLab 项目边界保留 |
| 新增 A-019、许可和稳定版本事实 | `done` | A-019 仅替代 A-003 当前版本事实；MIT 全文恢复 |
| 迁移 M11 为 DIAGNOSIS_PENDING | `done` | legacy VC-001、blocked/pending；未运行 Failure Analyst、未改产品 |
| 完整静态与 source 回归 | `done` | 664 tests；Ruff/format/mypy；97 AST；Schema/metadata/privacy；静态门和正式 state 指纹全部PASS |
| 全新 Validator 与归档 | `done` | 全新只读 high/high Validator 固定结构 PASS |

## 当前检查点

- 当前 Loop：1
- 最近完成：唯一全新只读 high/high Validator 按 VC-001 返回固定结构 PASS，无 blocker/unknown。
- 当前焦点：任务完成并归档；M11 继续等待下一阶段 Failure Analyst。
- 下一动作：由用户决定是否启动独立 M11 诊断；本任务不自动续跑。
- 阻塞项：无。
- blocker_type：`none`
- 诊断状态：`not_triggered`
- 已变更文件：根 Harness 六文件、A-019、第三方声明、M11/PLANS/memory/本计划；`source/` 未新增本任务改动。
- 待验证项：无。

## Validator 结论处理

| Loop | Validator 身份 | 合同版本 | 结论 | 绑定标准与证据 | 主协调 Agent处理 | 是否触发诊断 | 下一 Validator |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 全新只读 ADHOC-0015 Validator | VC-001 | PASS | AC-001～006、INV-001～004、GATE-001～007 全部通过 | 完成并归档 | 否 | 无 |

## 失败尝试与诊断

当前没有本任务失败特征或诊断触发。第一次快照恢复演练因本机 Python 不支持
`tarfile.extractall(filter=...)` 在仓库外失败；未修改仓库，随后使用同等路径逃逸检查的兼容
方式完成恢复演练，不属于产品或合同失败。未完成目录已标记为
`/private/tmp/trainlab-agentforge-v044-preupdate.invalid.rapavuhv`，不得作为恢复依据。

## 决策与发现

- 上游 v0.4.2→v0.4.4 只修改六个核心模板文件并新增上游自身历史计划；后者不复制。
- 当前六文件三方预演：template 无冲突；AGENTS 2 处、README/CHANGELOG/memory 各 1 处、
  exec-plan README 3 处需要人工适配。
- v0.4.4 不改变 src/tests 布局，A-003 的历史布局决定保留；A-019 只更新当前治理版本。

### v0.4.2 → v0.4.4 差异映射

| 上游项目 | 处理结论 | TrainLab 适配 |
| --- | --- | --- |
| `AGENTS.md` | `adapted` | 采用冻结合同、固定 Validator 输出、诊断门与 Failure Analyst；保留 source、隐私、Skills、Git 和外部动作规则。 |
| `README.md` | `adapted` | 更新为 v0.4.4 和开发—验证—诊断流程；保留 TrainLab 产品目录与运行说明。 |
| `CHANGELOG.md` | `adapted` | 仅在 TrainLab `Unreleased` 记录本次适配，不复制上游发布历史。 |
| `memory.md` | `adapted` | 更新稳定版本事实、合同/诊断规则和活动指针，不复制上游静态模板事实。 |
| `docs/exec-plans/README.md` | `adapted` | 采用完整合同/诊断/隔离协议；保留 TrainLab 串行与禁用 orchestrate 规则。 |
| `docs/exec-plans/template.md` | `adapted` | 采用 v0.4.4 全部字段；测试映射改为 A-009 的 `source/tests` 双层结构。 |
| 上游 completed plans | `not_applicable` | 属于 agentForge 自身发布历史，不复制到 TrainLab。 |
| 上游示例 memory 与 `src/tests` 占位 | `not_applicable` | 不属于 TrainLab 当前事实或产品布局。 |
| 上游 MIT `LICENSE` | `adapted` | 完整文本保存于 `docs/legal/third-party-notices.md`，仅覆盖所采用脚手架，不重新许可产品。 |

## Validator 固定输出

必须原样包含 `contract_version`、`overall_verdict`、`criterion_results`、
`blocking_findings`、`advisories`、`scope_change_candidates`、`unknowns` 和
`commands_and_evidence`。未绑定冻结标准的 blocker 使报告为 `INCONCLUSIVE`。

## 任务级独立验证

- 逐字冻结合同版本：`VC-001`
- 中性交接：`仅冻结合同、适用规则和当前仓库结果`
- Validator 身份/上下文：全新只读 high/high `adhoc0015_validator`；未参与实施。
- `criterion_results`：AC-001～006、INV-001～004、GATE-001～007 全部 `PASS`。
- `blocking_findings`：`[]`
- `advisories`：默认 Python 环境未装 pytest，使用与 `requirements.txt` 精确版本一致的既有只读缓存环境完成门禁；不影响裁决。
- `scope_change_candidates`：`[]`
- `unknowns`：`[]`
- `commands_and_evidence`：Tag/Commit、六文件映射、115项快照与restore、MIT逐字比较、664 tests、Ruff/format/mypy、97 AST、78 JSON、隐私/权限/diff、正式state完整对象相等。
- `overall_verdict`：`PASS`

## 集成级独立验证

- `overall_verdict`：`不适用——严格串行、无并行集成`

## PLANS 回写清单

`不适用——ADHOC 治理任务；已归档计划并删除 memory 活动指针，M11 Roadmap 保持 blocked/DIAGNOSIS_PENDING。`

## 迭代日志

| 日期/上下文 | 已完成事项与证据 | 发现 | 下一动作 |
| --- | --- | --- | --- |
| 2026-08-24 / upgrade-start | Git 与 v0.4.4 来源核对；115 项 owner-only 快照和仓库外恢复演练通过 | 当前工作区很脏但已闭合保护；正式 state before 指纹已保存 | 冻结 VC-001 后三方适配根 Harness |
| 2026-08-24 / gates-pass | 六核心文件适配、A-019、MIT、M11迁移和静态门完成；664 tests、Ruff/format/mypy、97 AST及隐私门PASS；state SHA仍为`7cc9f67...30f43` | 本任务未改变107个既有source文件字节/权限，Provider与外部动作0 | 交唯一全新只读Validator |
| 2026-08-24 / validator-pass | 全新只读high/high Validator按VC-001复跑并返回固定结构PASS | 无blocking finding、scope candidate或unknown；正式state完整对象相等 | 归档ADHOC-0015；M11保持等待诊断 |
