# 执行计划：迁移后工作区熟悉与可用性审计

- 状态：`completed`
- 负责人：主协调 Agent
- Roadmap ID：`ADHOC-0016`
- 阶段/子项目：`不适用`
- Batch ID：`不适用——严格串行只读审计`
- 返工来源：`无`
- 开始日期：2026-08-26
- 最后更新：2026-08-26

## 目标与验收标准

在不改变现有 M11 工作、正式 state、私人数据或任何外部系统的前提下，恢复仓库治理上下文，
核对迁移后 Git、目录、依赖和验证入口，并向用户交付当前阶段、主要组件、工作区风险和建议下一步。

## 范围与非目标

- 范围：根与 `source/` 治理文件、Git 元数据、活动计划、目录结构、工具链可用性、公开合成测试门。
- 非目标：修改产品实现、继续 M11、读取私人 raw/FIT/健康内容、模型调用、Garmin/Gmail/Sites、
  正式 state 写入、提交、分支、推送、发布或部署。

## 适用规则与参考资料

- 已批准规则：A-001、A-002、A-004、A-008、A-009、A-010、A-013～A-019。
- 按需读取的 references：无；根 `references/` 仅含 `.gitkeep`。

## 冻结验证合同

- 合同版本：`VC-001`
- 合同状态：`frozen`
- 冻结依据：用户于 2026-08-26 明确要求迁移后首先熟悉当前项目情况。
- 冻结时点：2026-08-26，任何仓库写入前；本计划只允许协调记录写入。

### 验收标准

| ID | 必须满足的结果 |
| --- | --- |
| `AC-001` | 完整恢复根治理、Roadmap、memory、活动 M11 计划和 `source/` 运行边界。 |
| `AC-002` | 核对 Git 根、分支、远端差异、已跟踪/未跟踪改动，并明确保护既有工作。 |
| `AC-003` | 核对当前电脑上的 Python、依赖与现有公开合成质量门可否执行。 |
| `AC-004` | 交付可复核的项目现状摘要、阻塞点、风险和下一步选项。 |

### 行为不变量

| ID | 必须始终成立的行为 |
| --- | --- |
| `INV-001` | 不修改产品代码、测试、正式 state、私人文件或 M11 Candidate。 |
| `INV-002` | 不调用模型、Garmin、Gmail、Workout、Sites、cron 或其他外部动作。 |
| `INV-003` | 不暂存、提交、切换分支、推送、发布或部署。 |

### 威胁模型

| ID | 范围内风险 |
| --- | --- |
| `TM-001` | 迁移造成工具链缺失、路径变化或文件权限异常，使既有验证入口不可复现。 |
| `TM-002` | 大量既有未提交内容被误认为本次改动、被覆盖或被纳入后续操作。 |
| `TM-003` | 只读检查意外读取、输出或修改私人 state/raw/凭据。 |

### 明确排除项

| ID | 不属于当前交付的场景 |
| --- | --- |
| `EX-001` | 修复 M11 r19 的 `technique_notes` 业务校验失败。 |
| `EX-002` | 对现有改动做清理、提交、拆分、回滚或合并。 |
| `EX-003` | 运行真实 AI 或任何 Provider/外部动作。 |

### Lint/Test 与静态门禁

| ID | 命令或检查 | 预期结果 |
| --- | --- | --- |
| `GATE-001` | Git/worktree/status 与目录检查 | 仓库根、分支和改动范围可复核。 |
| `GATE-002` | Python/依赖导入检查 | 当前电脑可解析项目固定依赖。 |
| `GATE-003` | `cd source && PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/code -q` | 公开合成代码测试通过；不读取正式 state/raw。 |
| `GATE-004` | Ruff check/format、mypy、compile、JSON/metadata、`git diff --check` | 全部适用静态门通过，或准确记录迁移环境阻塞。 |

### 合同修订记录

| 版本 | 状态 | 变更、理由与受影响标准 | 人工批准依据 |
| --- | --- | --- | --- |
| `VC-001` | `frozen` | 初始只读迁移审计合同 | 用户 2026-08-26 请求 |

## 依赖与隔离

- 显式依赖：当前 M11 active plan 只读恢复，不改变其状态。
- 任务分支/Worktree/集成分支：不适用——只读、严格串行且未获 Git 操作授权。
- 允许写入范围：本 exec plan 的状态与证据。
- 禁止写入范围：除本计划外的整个仓库、Git index/refs/remote、正式 state 和仓库外 Candidate。

## 功能与测试映射

`不适用——只读仓库熟悉与迁移后环境审计。`

## 工具采用情况

- 可执行技术栈：Git、Python 3、pytest、Ruff、mypy、JSON Schema。
- 使用现有 `memory.md` 与 CI 记录的验证入口，不安装工具、不建立仓库 `.venv`。

## Subagent 派发

不派发——本次为单一只读恢复工作流；并行不会改善结论，且不需要独立 Validator。

## 工作分解

| 步骤 | 状态 | 证据 |
| --- | --- | --- |
| 1. Git 门禁与治理上下文恢复 | done | Git 2.50.1；仓库根、`main`、status、规则、memory、Roadmap 已核对。 |
| 2. 活动计划、运行结构与迁移环境核对 | done | M11 VC-010/r19、`source/` Harness、私有边界、正式 state 与临时证据位置已核对。 |
| 3. 执行公开合成质量门并形成现状摘要 | done | AST/JSON/Markdown/layout/diff 通过；pytest/Ruff/mypy 因当前电脑缺少固定依赖而无法启动，已形成精确环境证据。 |

## 当前检查点

- 当前 Loop：迁移后工作区审计完成。
- 最近完成：Git、治理、运行树、正式 state、临时证据、Python/Codex 与公开静态门全部核对。
- 当前焦点：向用户交付现状，不继续 M11 或修复迁移差异。
- 下一动作：由用户决定后续优先恢复验证环境、补齐旧临时证据，或为新电脑建立明确的 M11 迁移/再基线计划。
- 阻塞项：无。
- blocker_type：`none`
- 诊断状态：`not_triggered`
- 已变更文件：仅本计划并已归档。
- 待验证项：无——完整 pytest/Ruff/mypy 未通过不是未知项，而是已确认的当前环境缺失；其恢复不在本审计范围。

## 决策与发现

- 当前分支为 `main`，领先 `origin/main` 54 个提交；工作区已有大量 M11 相关修改和未跟踪文件，
  全部按既有工作保护。
- M11 当前终态不是迁移环境失败：r19 唯一公开 canary 的 wire 校验通过，但两个 rest 课程的
  `technique_notes=[]` 违反业务 Schema `minItems:1`；按冻结计划禁止重试，私人模型调用为 0。
- 当前 `main` 为 `b172f95`，领先 `origin/main` 54 个提交；M11 与 agentForge v0.4.4 的主体仍是
  28 个既有修改和 120 个既有未跟踪文件，未获提交保护。本机另登记 13 个 prunable 旧 worktree。
- 当前电脑为 macOS 15.7.9 x86_64；默认 Python 3.13.5、`python3` 3.14.6，`python3.12` 命令缺失；
  现有 Conda 环境均不具备固定依赖。Codex CLI 为 0.146.0，而 M11 VC-009 记录环境为 0.147.0，
  所需命令参数仍可见，但版本尚未复验为等价。
- 私有文件、数据库与 OAuth 文件均为 owner-only `0600` 且被 Git 忽略；SQLite 完整性、外键、
  六表/触发器和登记 raw 哈希闭包通过。当前 state 条目数仍为 9,347，但迁移后元数据指纹为
  `068373278a29414628e15fbef202c1484ee3c599108a9da4b6ad7f7a4e12584d`，不再等于冻结的 `7cc9f67d…`。
- `state/` 有 3 个 Finder `.DS_Store`，其中 2 个位于 raw 树并造成 `verify_state.py` 唯一错误
  `raw_unregistered_file`；未删除。r19 canary、agentForge 快照和节点基线等 `/private/tmp` 目录均未迁移。
- 无依赖静态检查：106 个 Python AST、101 个公开 JSON、80 个 Markdown、本地链接、目录与
  metadata、AI case 结构和 `git diff --check` 全部通过。精确 pytest/Ruff/mypy 命令均以
  `No module named ...` 在启动前失败；未安装依赖、未创建仓库 `.venv`。

## 任务级独立验证

- 不适用——只读分析按 `AGENTS.md` 不强制独立 Validator；Git、SQLite、指纹、AST/JSON/Markdown、
  环境导入和精确质量门的命令证据均由主协调 Agent 直接记录。本结论不认证 M11 产品交付。

## 集成级独立验证

- 不适用——无并行集成。

## PLANS 回写清单

- [x] Exec plan 已归档到 `completed/`
- Roadmap：不适用——ADHOC 只读审计不改变 Roadmap。
- `memory.md`：不新增长期活动指针；本计划预计在同一上下文完成并归档。

## 迭代日志

| 日期/上下文 | 已完成事项与证据 | 发现 | 下一动作 |
| --- | --- | --- | --- |
| 2026-08-26 / migration-audit | Git/治理/M11/source/state/临时证据和工具链已核对；AST/JSON/Markdown/layout/diff通过 | 固定Python依赖、旧`/private/tmp`证据未迁移；state元数据指纹改变且raw有2个未登记`.DS_Store`；既有M11工作未提交 | 向用户交付现状，后续动作另行授权 |
