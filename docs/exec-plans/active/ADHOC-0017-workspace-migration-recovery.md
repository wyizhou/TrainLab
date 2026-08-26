# 执行计划：迁移工作区保护、状态可迁移性与 M11 r20 收口

- 状态：`active`
- 负责人：主协调 Agent
- Roadmap ID：`ADHOC-0017`
- 阶段/子项目：`不适用 / M11 前置恢复`
- Batch ID：`serial-migration-r20`
- 返工来源：`docs/exec-plans/completed/ADHOC-0016-workspace-migration-audit.md`
- 开始日期：2026-08-26
- 最后更新：2026-08-26

## 目标与验收标准

保护迁移到当前电脑但尚未提交的 agentForge/M11 工作；建立可复现的 Python 3.12 质量门、
一致的 Finder 元数据边界和跨主机内容指纹；在 VC-010 不变的前提下，经独立归因后完成
M11 v4-r20 的 business-only Prompt 语义闭包。最终停在新公开 canary 授权门前。

## 范围与非目标

- 范围：恢复分支与远端保护、治理回写、仓库外验证环境、状态验证/指纹、M11 Prompt parity、
  定向与完整测试、Failure Analyst、任务级和集成级独立 Validator。
- 非目标：公开或私人模型调用、Garmin/Gmail/Workout/Sites/cron、PR、main 合并、部署、
  清理 13 个 prunable worktree、TD-0001 修复、放宽业务 Schema 或改变训练/日期/隐私规则。

## 适用规则与参考资料

- 已批准规则：A-001、A-002、A-004、A-008～A-010、A-013～A-019，以及 M11 VC-010。
- 按需读取的 references：无；只读取当前 M11 active plan、状态脚本和触发的本地 Skill。

## 冻结验证合同

- 合同版本：`VC-001`
- 合同状态：`frozen`
- 冻结依据：用户于 2026-08-26 明确批准“TrainLab 迁移收口与 M11 v4-r20 执行方案”并要求实施。
- 冻结时点：2026-08-26，产品/状态实现修改前。

### 验收标准

| ID | 必须满足的结果 |
| --- | --- |
| `AC-001` | 当前 28 个已跟踪改动和全部可归属未跟踪结果经隐私审计后保存到 `codex/m11-r20-migration-recovery` 并推送 `origin`；未知或私人文件不进入 Git。 |
| `AC-002` | 使用仓库外 Python 3.12 隔离环境复现全部既有 pytest、Ruff、format、mypy、compile、Schema、Markdown 与隐私门。 |
| `AC-003` | `.DS_Store` 在 raw 中始终视为非法未注册文件；验证器、Candidate 指纹和实际状态一致，不再存在特殊放行。 |
| `AC-004` | `formal_state_content_fingerprint_v1` 只绑定正式 DB 与登记 raw 的路径、大小和 SHA，跨 inode/mtime 复制稳定，任一内容改变都会改变指纹。 |
| `AC-005` | r19 新失败由全新 high/high Failure Analyst 归因；仅在实现缺陷、安全自动修复且无需升级合同时实施 r20。 |
| `AC-006` | r20 从业务 Schema 自动派生全部 wire 删除的业务约束，并由 Prompt/business/wire/Host 同一 parity 入口在 Candidate/pending/模型前校验。 |
| `AC-007` | Prompt v3/v4 原字节与 SHA 不变；休息日 `technique_notes`、`stop_conditions` 继续非空；模型/Host/Reader 公共业务接口不变。 |
| `AC-008` | 两级独立 Validator 均 PASS；本轮模型、Provider 和外部动作调用均为 0，最终停在公开 canary 授权门前。 |

### 行为不变量

| ID | 必须始终成立的行为 |
| --- | --- |
| `INV-001` | 私人 state、raw/FIT、数据库、凭据、日志、Candidate 和证据内容不得进入 Git 或可见输出。 |
| `INV-002` | 不修改日期、真实数据、训练规则、正确预期、VC-010 隐私边界或外部动作授权。 |
| `INV-003` | 不删除测试、不降低断言、不 skip/xfail、不为绿灯弱化 Schema；Failure Analyst/Validator 只读且相互独立。 |
| `INV-004` | 旧主机 `7cc9…` 只保留为历史身份指纹，不声称迁移后相等；新内容基线只记录 SHA 和计数。 |

### 威胁模型

| ID | 范围内的参与者、输入、故障或攻击能力 |
| --- | --- |
| `TM-001` | 未提交迁移结果因误暂存、漏传或设备故障丢失，或私人文件被推送。 |
| `TM-002` | wire 删除业务限制后 Prompt 只同步结构，模型产生 wire 合法但业务非法输出。 |
| `TM-003` | Finder 元数据被错误当作正式 state，或跨设备 inode/时间元数据破坏迁移完整性判断。 |
| `TM-004` | 新主机依赖或 Codex 能力不匹配，使旧验证结论无法复现。 |

### 明确排除项

| ID | 不属于当前交付的场景 |
| --- | --- |
| `EX-001` | 新公开 canary、私人周报模型调用、任何自动重试或外部 Provider 调用。 |
| `EX-002` | 改变 `weekly_model_decision_v1`、`weekly_ai_result_v4`、Host/Reader 字段或休息日非空业务预期。 |
| `EX-003` | 清理旧 worktree、PR、main 合并、发布、部署或技术债扩展。 |

### Lint/Test 与静态门禁

| ID | 命令或检查 | 预期结果 |
| --- | --- | --- |
| `GATE-001` | 明确清单暂存、known-secret/私人路径扫描、`git diff --cached --check` | 仅计划内公开文件；无私人内容。 |
| `GATE-002` | `uv run --isolated --no-project --python <bundled-3.12> --with-requirements source/requirements.txt` 下完整 pytest | 全部 PASS，无 skip/xfail 弱化。 |
| `GATE-003` | Ruff check/format、mypy、compileall | 全部 PASS。 |
| `GATE-004` | 全部公开 JSON/Schema、Skill metadata、Markdown/链接、隐私/Git ignore、`git diff --check` | 全部 PASS。 |
| `GATE-005` | `verify_state.py`、SQLite integrity/FK、raw 哈希/权限与内容指纹 | 全部 PASS；只输出非敏感计数和 SHA。 |
| `GATE-006` | r20 定向测试 | 所有删除关键词、空数组、漂移、旧 SHA、零模型前副作用均闭合。 |

### 合同修订记录

| 版本 | 状态 | 变更、理由与受影响标准 | 人工批准依据 |
| --- | --- | --- | --- |
| `VC-001` | `frozen` | 初始迁移恢复与 r20 串行合同 | 用户 2026-08-26 明确批准并要求实施 |

## 依赖与隔离

- 显式依赖：ADHOC-0016 审计事实；M11 active plan 的 VC-010、A-018/A-019。
- 共享接口和冻结依据：业务 Schema 是唯一业务结构来源；M11 v3/v4 Prompt SHA 冻结。
- 任务分支：`codex/m11-r20-migration-recovery`（用户明确批准）。
- Worktree/集成分支：不适用——严格串行。
- 允许写入范围：本计划、治理文件、明确归属的迁移快照；状态验证/指纹脚本与测试；M11 Prompt/Schema/parity/manifest/Builder/Runner 与测试；owner-only 证据根和 Finder 元数据隔离归档。
- 禁止写入范围：正式 DB/raw 证据（除精确移动 3 个 `.DS_Store`）、私人配置/凭据、旧 r19 证据内容、main、远端其他分支和外部系统。

## 功能与测试映射

| 功能 | Feature slug | 测试目录 | 合同标准 | 必须满足的行为 |
| --- | --- | --- | --- | --- |
| 可迁移状态指纹 | `state-content-fingerprint` | `source/tests/code/unit/` | AC-003/004 | Finder 元数据严格拒绝；内容指纹跨元数据稳定、随字节变化。 |
| Prompt 业务约束闭包 | `m11-r20-business-constraints` | `source/tests/code/contract/`、`integration/` | AC-005～008 | 自动提取全部业务限制，漂移在模型前阻断。 |

## 工具采用情况

- 可执行技术栈：Git、uv、bundled Python 3.12、pytest、Ruff、mypy、JSON Schema、Codex CLI 能力只读检查。
- 不建立仓库 `.venv` 或 lockfile；依赖严格来自 `source/requirements.txt`。

## Subagent 派发

| Attempt | Agent 角色/任务 ID | 合同版本 | 风险与复杂度 | 模型档位 | 推理档位 | 选档理由 | 平台支持 | 写入边界 | 产物与门禁 | 结果 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Migration/State Validator / ADHOC-0017 | VC-001 | 高：私人状态与跨机完整性 | high | high | 高风险只读终验 | available | 只读 | 固定 Validator 输出；状态批次 PASS 门 | pending |
| 2 | Failure Analyst / M11-v4-r20 | VC-010 | 高：新模型业务失败归因 | high | high | A-019 强制归因 | available | 只读 | 固定 Failure Analyst 输出；三条件门 | pending |
| 3 | M11 Code Validator / M11-v4-r20 | VC-010 | 高：Prompt/Schema/模型前门 | high | high | 高风险代码终验 | available | 只读 | 固定 Validator 输出；M11 PASS 门 | pending |
| 4 | Integration Validator / ADHOC-0017+M11 | VC-001 + VC-010 | 高：迁移与M11组合结果 | high | high | 最终整体终验 | available | 只读 | 完整门与零外部动作 PASS | pending |

## 工作分解

| 步骤 | 状态 | 证据 |
| --- | --- | --- |
| 1. 建立恢复分支、冻结计划、隐私审计、恢复快照并推送 | in_progress | 分支已从 `main@b172f95` 建立；149 个计划内公开文件已按明确路径清单暂存，敏感路径/高置信凭据扫描与 staged diff check 均无命中。 |
| 2. 恢复 Python 3.12 隔离环境并运行修改前基线 | pending | 待步骤1。 |
| 3. 测试先行统一 Finder 元数据和内容指纹合同 | pending | 待基线。 |
| 4. Migration/State Validator 与批次提交推送 | pending | 待实现。 |
| 5. M11 新失败 Failure Analyst | pending | 待迁移批次 PASS。 |
| 6. 测试先行实施 r20 通用约束派生 | pending | 仅诊断三条件满足时。 |
| 7. M11 Code Validator、集成 Validator、回写与推送 | pending | 待完整门。 |

## 当前检查点

- 当前 Loop：迁移恢复快照。
- 最近完成：从 `main@b172f95` 创建恢复分支；owner-only 证据根为 0700；149 个文件完成明确清单暂存和隐私审计。
- 当前焦点：建立并推送 WIP 恢复快照。
- 下一动作：提交当前 staged snapshot 并仅推送恢复分支，然后恢复 Python 3.12 基线。
- 阻塞项：无。
- blocker_type：`none`
- 诊断状态：`not_triggered`
- 已变更文件：本计划；分支引用。
- 待验证项：迁移快照隐私、基线环境、状态合同、r20 与两级 Validator。

## Validator 结论处理

| Loop | Validator 身份 | 合同版本 | 结论 | 绑定标准与证据 | 主协调 Agent 处理 | 是否触发诊断 | 下一 Validator |
| --- | --- | --- | --- | --- | --- | --- | --- |
| migration-state | pending | VC-001 | pending | pending | PASS 后进入 M11 归因 | 否 | M11 Failure Analyst |
| m11-r20 | pending | VC-010 | pending | pending | PASS 后进入整体终验 | 按 A-019 | Integration Validator |
| integration | pending | VC-001+VC-010 | pending | pending | PASS 后回写并停在 canary 门前 | 否 | 无 |

## 失败尝试与诊断

| Failure ID | 合同版本 | 标准 ID | 失败特征 | Loop | 修法或验证尝试 | 是否实质不同 | 证据 | 结果 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| M11-V4-R20-F01 | VC-010 | AC-013/GATE-004 | wire 删除 `minItems`，Prompt 机器语义未表达，公开 rest 输出空 `technique_notes` 后业务拒绝 | r19 canary | 尚未实施 r20；先归因 | 不适用 | active plan 记录与当前 Schema/Prompt/parity | pending Failure Analyst |

## 决策与发现

- 用户选择分支提交并推送、休息日技术备注继续非空、本轮验证后停止不调用模型。
- 当前 Git 状态为 28 个已跟踪改动和 114 个未跟踪状态项；Prompt v3/v4 SHA 已复核匹配历史记录。
- r19 私人临时 Candidate 在本机不存在；只记录不可用和既有 receipt SHA，不伪造历史证据。

## Validator 固定输出

Validator 必须返回 `contract_version`、`overall_verdict`、`criterion_results`、
`blocking_findings`、`advisories`、`scope_change_candidates`、`unknowns` 和
`commands_and_evidence`；未绑定标准的阻塞项按 `INCONCLUSIVE` 处理。

## 任务级独立验证

- 逐字冻结合同版本：`VC-001`；M11 子批次使用 `VC-010`。
- 中性交接：仅冻结合同、适用规则和当前仓库结果。
- `overall_verdict`：`pending`

## 集成级独立验证

- 集成范围：迁移/状态批次与 M11 r20 串行组合结果。
- 逐字冻结合同版本：`VC-001 + VC-010`。
- 中性交接：仅冻结合同、适用规则和当前仓库结果。
- `overall_verdict`：`pending`

## PLANS 回写清单

- [ ] Exec plan 已归档到 `completed/`
- Roadmap：不适用——ADHOC；M11 状态由其 active plan 单独回写。
- [ ] `memory.md` 中 ADHOC-0017 活动指针已删除。

## 迭代日志

| 日期/上下文 | 已完成事项与证据 | 发现 | 下一动作 |
| --- | --- | --- | --- |
| 2026-08-26 / start | 用户批准完整串行方案；恢复分支已建立；owner-only 证据根完成；149 个计划内文件经 staged path、高置信凭据、synthetic email 和 diff 检查 | 无私人路径或真实凭据进入 index；r19 临时证据仍缺失，raw 有 Finder 元数据 | 建立并推送 WIP 恢复快照 |
