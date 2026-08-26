# 执行计划：迁移工作区保护、状态可迁移性与 M11 r20 收口

- 状态：`completed`
- 负责人：主协调 Agent
- Roadmap ID：`ADHOC-0017`
- 阶段/子项目：`不适用 / M11 前置恢复`
- Batch ID：`serial-migration-r20`
- 返工来源：`docs/exec-plans/completed/ADHOC-0016-workspace-migration-audit.md`
- 开始日期：2026-08-26
- 完成日期：2026-08-26
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
| 1 | Migration/State Validator / ADHOC-0017 | VC-001 | 高：私人状态与跨机完整性 | high | high | 高风险只读终验 | available | 只读 | 固定 Validator 输出；状态批次 PASS 门 | INCONCLUSIVE：验证者主动报告隔离输入受历史材料污染；报告不可用于修复或放行 |
| 2 | Migration/State Validator / ADHOC-0017-r2 | VC-001 | 高：私人状态与跨机完整性 | high | high | 首轮独立性协议失效，按同一合同重新独立验证 | available | 只读 | 固定 Validator 输出；状态批次 PASS 门 | FAIL：仅 AC-001/GATE-001/TM-001，7 个公开状态批次结果尚未提交推送；其余适用标准 PASS |
| 3 | Migration/State Validator / ADHOC-0017-r3 | VC-001 | 高：私人状态与跨机完整性 | high | high | 修复单一交付缺口后重新独立验证 | available | 只读 | 固定 Validator 输出；状态批次 PASS 门 | PASS：914 tests、完整静态门、正式state/指纹/隐私、Git clean且HEAD=origin；无blocking finding |
| 4 | Failure Analyst / M11-v4-r20 | VC-010 | 高：新模型业务失败归因 | high | high | A-019 强制归因 | available | 只读 | 固定 Failure Analyst 输出；三条件门 | completed：`IMPLEMENTATION_DEFECT`、`safe_auto_fix=true`、`contract_change_required=false`、confidence=0.97 |
| 5 | M11 Code Validator / M11-v4-r20 | VC-010 | 高：Prompt/Schema/模型前门 | high | high | 高风险代码终验 | available | 只读 | 固定 Validator 输出；M11 PASS 门 | FAIL：AC-009/INV-006/TM-006，work root非Git边界未强制；其余适用标准PASS |
| 6 | M11 Code Validator / M11-v4-r20-r2 | VC-010 | 高：非Git工作目录前检与Prompt/Schema模型前门 | high | high | 单一有效FAIL修复后必须由全新Agent重新独立裁定 | available | 只读 | 固定 Validator 输出；M11 PASS 门 | FAIL：AC-005/015、TM-009、GATE-004；Candidate内proof与manifest可协同改写后进入私人调用 |
| 7 | M11 Code Validator / M11-v4-r20-r3 | VC-010 | 高：独立canary authority与全部模型前门 | high | high | 新失败特征定向修复后必须由另一全新Agent复验 | available | 只读 | 固定 Validator 输出；M11 PASS 门 | PASS：932 tests、全部静态门及AC/INV/TM闭合；无blocking finding |
| 8 | Integration Validator / ADHOC-0017+M11 | VC-001 + VC-010 | 高：迁移与M11组合结果 | high | high | 最终整体终验 | available | 只读 | 固定 Validator 输出；完整门与零外部动作 PASS | PASS：932 tests、正式state、r20对抗矩阵、Git/隐私与零调用闭合；无blocking/unknown |

## 工作分解

| 步骤 | 状态 | 证据 |
| --- | --- | --- |
| 1. 建立恢复分支、冻结计划、隐私审计、恢复快照并推送 | done | 本地提交 `fb8d291` 与阻塞记录 `e40072f` 已推送；远端分支精确指向 `e40072f`。 |
| 2. 恢复 Python 3.12 隔离环境并运行修改前基线 | done | 依赖合同准确红灯后转绿；910 tests、Ruff/format/mypy/compile、90 JSON/87 Schema、6 YAML、81 Markdown、本地链接、隐私边界全部 PASS；state 唯一错误为已知 `raw_unregistered_file`。 |
| 3. 测试先行统一 Finder 元数据和内容指纹合同 | done | 4 个新行为节点红→绿；3 个 Finder 文件按原 SHA 移入 owner-only Git ignored 隔离归档；正式 state PASS，内容指纹 `673f01dc…f5c50d`。 |
| 4. Migration/State Validator 与批次提交推送 | done | 全新r3 Validator PASS；914 tests、完整静态门、正式state/指纹/隐私、Git clean与远端同步闭合。 |
| 5. M11 新失败 Failure Analyst | done | 固定三条件全部满足；VC-010保持冻结，无需合同升级。 |
| 6. 测试先行实施 r20 通用约束派生 | done | 旧实现6项红灯后转绿；266项M11、926项完整测试及全部静态/Schema/Markdown/隐私/state门PASS。 |
| 7. M11 Code Validator、集成 Validator、回写与推送 | done | Code Validator r3与最终Integration Validator均PASS；收口提交`55289c1`已推送，HEAD与upstream精确一致。 |

## 当前检查点

- 当前 Loop：完成。
- 最近完成：收口提交`55289c1`已推送`origin/codex/m11-r20-migration-recovery`，HEAD与upstream精确一致。
- 当前焦点：无；迁移恢复与r20代码收口完成。
- 下一动作：M11仅允许申请一次全新公开canary人工授权并升级合同；批准前不建立Candidate或调用模型。
- 阻塞项：无。
- blocker_type：`none`
- 诊断状态：`not_triggered`
- 已变更文件：r20 Prompt/Schema/parity、Candidate Builder/Runner、合同/集成测试及治理文件；全部为已验证公开普通文件，私人路径命中0。
- 待验证项：无。

## Validator 结论处理

| Loop | Validator 身份 | 合同版本 | 结论 | 绑定标准与证据 | 主协调 Agent 处理 | 是否触发诊断 | 下一 Validator |
| --- | --- | --- | --- | --- | --- | --- | --- |
| migration-state-r1 | fresh high/high read-only | VC-001 | INCONCLUSIVE | 独立性协议失效；报告不得产生可执行 FAIL 或 PASS | 不修改实现、不采用报告观察；以同一冻结合同交全新 Validator | 否 | Migration/State Validator r2 |
| migration-state-r2 | fresh high/high read-only | VC-001 | FAIL | AC-001/GATE-001/TM-001：5 tracked + 2 untracked、0 staged；其余适用标准和全部门 PASS | 精确隐私复核后按明确清单提交并推送，不修改实现 | 否 | Migration/State Validator r3 |
| migration-state-r3 | fresh high/high read-only | VC-001 | PASS | AC-001～004/007、INV、TM、GATE-001～005全部适用项闭合；无blocking finding | 状态批次完成，进入M11归因 | 否 | M11 Failure Analyst |
| m11-r20 | fresh high/high read-only r3 | VC-010 | PASS | 932 tests、全部AC/INV/TM与模型前门闭合；无blocking finding | 转validated并进入整体终验 | 否 | Integration Validator |
| integration | fresh high/high read-only | VC-001+VC-010 | PASS | 迁移快照、正式state、r20对抗矩阵、Git/隐私与零调用全部闭合；无blocking/unknown | 回写并停在canary授权门前 | 否 | 无 |

## 失败尝试与诊断

| Failure ID | 合同版本 | 标准 ID | 失败特征 | Loop | 修法或验证尝试 | 是否实质不同 | 证据 | 结果 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| M11-V4-R20-F01 | VC-010 | AC-013/GATE-004 | wire 删除 `minItems`，Prompt 机器语义未表达，公开 rest 输出空 `technique_notes` 后业务拒绝 | r19 canary | 尚未实施 r20；先归因 | 不适用 | active plan 记录与当前 Schema/Prompt/parity | pending Failure Analyst |
| ADHOC-0017-F01 | VC-001 | AC-001/GATE-001 | 恢复分支 push 被 GitHub workflow scope 门拒绝 | migration snapshot | HTTPS token scope 与 SSH 身份只读核对 | 不适用 | GitHub remote rejection、`gh auth status`、SSH publickey rejection | blocked：等待新认证权限 |
| ADHOC-0017-F02 | VC-001 | AC-002/GATE-002 | fixed requirements 在 macOS x86_64 解析到无 wheel 的 cryptography 50.0.1 | baseline environment | exact install、no-build wheel probe、现有 conda Python 3.12 探测、47.0.0 full-requirements import probe | 不适用 | uv resolver/build 输出；Rust 缺失；47.0.0 52 packages 导入成功 | resolved：用户批准精确 pin；合同测试红→绿，完整基线通过 |
| ADHOC-0017-F03 | VC-001 | AC-001/GATE-001/TM-001 | 状态批次 5 tracked + 2 untracked，尚未暂存、提交和推送 | migration-state-r2 | 全部实现与验证门已 PASS；只执行明确清单交付 | 不适用 | Validator 固定报告、提交 `58815ff`、HEAD=origin | resolved：精确提交推送完成，等待全新 Validator 复核 |

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
- `overall_verdict`：`PASS`

## 集成级独立验证

- 集成范围：迁移/状态批次与 M11 r20 串行组合结果。
- 逐字冻结合同版本：`VC-001 + VC-010`。
- 中性交接：仅冻结合同、适用规则和当前仓库结果。
- `overall_verdict`：`PASS`

## PLANS 回写清单

- [x] Exec plan 已归档到 `completed/`
- Roadmap：不适用——ADHOC；M11 状态由其 active plan 单独回写。
- [x] `memory.md` 中 ADHOC-0017 活动指针已删除。

## 迭代日志

| 日期/上下文 | 已完成事项与证据 | 发现 | 下一动作 |
| --- | --- | --- | --- |
| 2026-08-26 / start | 用户批准完整串行方案；恢复分支已建立；owner-only 证据根完成；149 个计划内文件经 staged path、高置信凭据、synthetic email 和 diff 检查 | 无私人路径或真实凭据进入 index；r19 临时证据仍缺失，raw 有 Finder 元数据 | 建立并推送 WIP 恢复快照 |
| 2026-08-26 / snapshot-push-blocked | 建立本地提交 `fb8d291`；HTTPS 与 SSH 两条 GitHub 路径均只读核对 | HTTPS token 缺少 `workflow` scope，SSH 无可用 public key；本地分支安全但尚未远端保护 | 请求用户批准刷新 GitHub OAuth workflow scope，成功前停止后续实现 |
| 2026-08-26 / snapshot-pushed | 用户明确授权刷新 `workflow` scope；GitHub device flow 成功；恢复分支推送并核对远端 SHA `e40072f` | 推送授权阻塞已消除；未创建 PR、未触碰 main | 恢复 Python 3.12 隔离质量门并记录修改前基线 |
| 2026-08-26 / baseline-env-blocked | bundled Python 3.12.13 + exact requirements 在测试前复现；无源码构建和现有 Conda 环境均核对；47.0.0 wheel 与全依赖导入成功 | requirements 未固定传递依赖，解析到不支持 macOS x86_64 wheel 的 cryptography 50.0.1；不是项目测试失败 | 请求人工批准增加 `cryptography==47.0.0`，不改业务代码或降低测试 |
| 2026-08-26 / dependency-pin-authorized | 用户明确回复“授权开始” | 允许只增加 `cryptography==47.0.0` 和对应合同回归；不授权 Rust/system 安装或其他依赖变更 | 先红后绿并恢复完整基线 |
| 2026-08-26 / migrated-baseline-pass | 依赖合同旧文件红灯、精确 pin 后转绿；910 tests、Ruff/format、mypy 108 files、compile、90 JSON/87 Schema、6 YAML、81 Markdown/链接和隐私门 PASS | state integrity/FK/六表正确，唯一错误为预期 `raw_unregistered_file`；未发现其他迁移回归 | 提交依赖修复，进入 Finder 元数据和 portable fingerprint 测试先行 |
| 2026-08-26 / state-gates-pass | Finder/Candidate、verify output、跨 inode/mtime 稳定和登记字节变化节点红→绿；3 文件按 SHA 可恢复隔离；98 定向与 914 完整 tests、静态门、正式 state PASS | 新 portable fingerprint 为 `673f01dc3a60d8d36316d3fbc58d75b144012fd0cca200c7086d900f98f5c50d`，entry 9337/raw 9336；旧主机身份指纹不作相等声明 | 状态转 validating，交全新只读 high/high Migration/State Validator |
| 2026-08-26 / migration-validator-r1-inconclusive | 首轮 Validator 完成 914 tests 与适用静态门，但主动报告其隔离输入受到历史材料污染并返回 INCONCLUSIVE | 报告不具备独立裁决效力，不能用于修改或放行；不向后续 Validator 传播其观察 | 保持 validating，以逐字 VC-001 和当前仓库交第二个全新只读 high/high Validator |
| 2026-08-26 / migration-validator-r2-fail | 第二轮全新 Validator 独立完成 914 tests、完整静态门、正式 state/指纹/隐私检查；除交付状态外全部适用标准 PASS | 唯一阻塞绑定 AC-001/GATE-001/TM-001：7 个公开状态批次结果尚未暂存、提交、推送 | 不改实现；按明确清单隐私复核、提交推送，再交第三个全新 Validator |
| 2026-08-26 / migration-delivery-fixed | 7 个公开文件经精确清单、凭据/私人路径与 cached diff 检查后提交为 `58815ff` 并推送；HEAD 与远端分支 SHA 一致 | 单一交付缺口已消除；实现和正式 state 未改变 | 交第三个全新只读 high/high Validator 按同一 VC-001 复核 |
| 2026-08-26 / migration-state-pass | 第三轮全新Validator按VC-001返回PASS；914 tests、静态门、正式state、portable fingerprint、隐私与Git同步全部闭合 | 原28项历史计数无法从现存对象严格还原，仅列advisory，不影响当前可达性与隐私结论 | 进入M11状态统一与全新Failure Analyst归因门 |
| 2026-08-26 / m11-r20-diagnosis-pass | 全新只读high/high Failure Analyst按VC-010完成固定归因 | `IMPLEMENTATION_DEFECT`、`safe_auto_fix=true`、`contract_change_required=false`；可在原合同内一次定向修复 | 测试先行实施通用business-only constraints；模型和外部调用保持0 |
| 2026-08-26 / m11-r20-gates-pass | 旧实现6项准确红灯后完成Prompt v5/语义v2、通用约束派生、Builder/Runner共享parity和公共fixture | 266项M11、926项完整测试、静态/Schema/Markdown/隐私/state/diff门PASS；旧Prompt SHA不变 | 交全新只读high/high M11 Code Validator；PASS后进入组合终验 |
| 2026-08-26 / m11-r20-validator-fail | 全新Code Validator完成926 tests与完整门并返回FAIL | business-only闭包PASS；唯一阻塞绑定AC-009/INV-006/TM-006，非Gitwork root未被强制证明 | 一次针对性测试先行修复后交另一全新Code Validator |
| 2026-08-26 / m11-r20-code-pass | 非Git前检与Candidate外canary authority两轮定向修复闭合；全新Code Validator r3返回PASS | 932 tests与全部静态门PASS，53条业务限制、Git隔离、proof authority和零调用均闭合 | 转validated并交最终Integration Validator |
| 2026-08-26 / integration-pass | 全新Integration Validator按VC-001+VC-010独立返回PASS | 迁移快照、正式state内容指纹、r20对抗矩阵、Git/隐私和零模型/外部调用无blocking或unknown | 明确清单提交推送，随后归档ADHOC；M11停在新canary授权门前 |
| 2026-08-26 / delivery-complete | 16个公开文件经明确清单暂存、隐私和cached diff门提交为`55289c1`并推送 | HEAD与upstream精确一致；未创建PR、未合并main、未调用模型或外部服务 | 归档本计划；M11保持validated并等待新canary人工授权/合同升级 |
