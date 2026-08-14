# 执行计划：升级并严格适配 agentForge 0.4.2

- 状态：`completed`
- 负责人：主协调 Agent
- Roadmap ID：`ADHOC-0001`
- 阶段/子项目：不适用
- Batch ID：不适用——单任务串行执行
- 返工来源：无
- 开始日期：2026-08-12
- 最后更新：2026-08-12

## 目标与验收标准

- 以上游 `v0.4.2` 标签提交
  `ccc934ece6b7b64368c08bc3ce431678511ecfa3` 为固定基线。
- 根开发 Harness 完整覆盖 0.4.2 的 Git、Roadmap、exec plan、Skill、references、
  Agent 选档、lint/test、独立 Validator、技术债、记忆和发布协议。
- 保留 TrainLab 已批准的 A-001/A-002，并将 `product/` 作为 0.4.2 默认
  `src/`/`tests/` 布局的项目级已批准适配。
- 更新过期的模板、README、版本来源和活动/归档目录说明；不复制 agentForge
  的示例历史计划。
- 适用静态检查、产品门禁和全新只读 Validator 均通过。

## 范围与非目标

- 允许写入：根 Harness 治理文档、`docs/exec-plans/`、`memory.md`、
  `CHANGELOG.md`、`THIRD_PARTY_NOTICES.md`，以及为验证 Harness 契约直接需要的
  测试或质量脚本。
- 禁止写入：产品业务行为、私有运行数据、凭据、FIT/raw/数据库、生产配置、
  邮箱、Garmin、supervisor、远端 Git 和正式发布。
- 不创建 `.orchestration`、Dashboard、Graph、hash-bound handoff 或连续审批版本。
- 不加载、调用或修改全局 `orchestrate-parallel-work` skill。

## 适用规则与参考资料

- 已批准规则：`rules.md` 中 A-001、A-002。
- 按需读取的 references：无。
- 上游权威来源：agentForge `v0.4.2` 标签及其 `README.md`、`AGENTS.md`、
  `PLANS.md`、`rules.md`、`memory.md`、exec-plan 文档和 `CHANGELOG.md`。

## 依赖与隔离

- 显式依赖：Git 门禁通过；工作区在提交 `96118de` 后干净。
- 共享接口和冻结依据：agentForge `v0.4.2` 标签提交已通过 Git 标签核验。
- 任务分支：不适用——用户未授权创建或切换分支。
- Worktree：不适用——单一串行治理任务。
- 集成分支：不适用。
- 允许写入范围：见“范围与非目标”。
- 禁止写入范围：见“范围与非目标”。

## 功能与测试映射

`不适用——治理与脚手架适配任务；不引入产品功能行为。`

## 工具采用情况

- 可执行技术栈：Markdown 治理文档、Python 产品质量脚本。
- Linter 配置和命令：`git diff --check`；产品 README/CI 声明的 7 文件
  Ruff/format-check 和 5 文件 mypy 命令。
- 测试框架、定向命令和完整命令：Harness 结构/链接检查；
  `product/.venv/bin/python product/scripts/verify_repository_quality.py all`；
  `product/.venv/bin/python -m pytest -q product/tests/test_repository_quality.py
  product/tests/product_packaging/test_build_product.py`。完整产品 pytest 不适用：本任务只修改
  根治理 Markdown，不修改产品代码、配置、schema、依赖、构建器或测试行为；以质量和
  构建边界定向测试覆盖直接风险。

## Subagent 派发

| Attempt | Agent 角色/任务 ID | 风险与复杂度 | 模型档位 | 推理档位 | 选档理由 | 平台支持 | 写入边界 | 产物与门禁 | 结果 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 独立 Validator / `ADHOC-0001-validator` | 跨治理文件适配与规则保全 | `high` | `high` | 必须逐项核对上游协议、项目例外和无弱化 | 支持；全新独立 Agent | 只读 | 中性验收报告 | `FAIL`——发现 memory 旧测试路径与派发记录未同步 |
| 2 | 独立 Validator / `ADHOC-0001-validator-r02` | 修正后的完整治理复验 | `high` | `high` | 第一次验证发现状态一致性缺陷，需全新 Agent 重新检查全部验收项 | 支持；全新独立 Agent | 只读 | 中性验收报告 | `FAIL`——MIT permission notice 被缩写 |
| 3 | 独立 Validator / `ADHOC-0001-validator-r03` | 许可修正后的完整复验 | `high` | `high` | 第二次验证发现许可文本不精确，需全新 Agent 核对全部合同 | 支持；全新独立 Agent | 只读 | 中性验收报告 | `PASS` |

## 工作分解

| 步骤 | 状态（`pending`、`in_progress`、`blocked`、`done`） | 证据 |
| --- | --- | --- |
| 固定并完整读取 agentForge 0.4.2 | `done` | 标签 `v0.4.2` → `ccc934e`；已读取核心协议文件 |
| 建立当前版本差异清单 | `done` | 12 个核心文件均缺失或与 0.4.2 不一致 |
| 更新根 Harness 与项目适配 | `done` | 0.4.2 全协议已适配；A-001/A-002 未修改 |
| 执行静态、链接、产品回归门禁 | `done` | 根链接 66；quality/Ruff/format/mypy 通过；定向 19 passed |
| 取得全新只读 Validator PASS | `done` | Attempt 3 完整复验 `PASS` |
| 归档计划并清除活动指针 | `done` | 计划移入 `completed/`；memory 恢复无活动计划 |

## 当前检查点

- 当前 Loop：完成
- 最近完成：第三位全新只读 Validator 完整复验并返回 `PASS`。
- 当前焦点：无。
- 下一动作：无；等待用户决定是否暂存或提交。
- 阻塞项：无。
- 已变更文件：根 Harness 11 个既有文件、active/completed 目录 README、本计划。
- 待验证项：无。

## 决策与发现

- 当前 Harness 源于旧默认分支提交 `a76901f...`，不是正式 0.4.2 标签。
- 0.4.2 空模板默认根 `src/` 与 `tests/`；A-002 是已经人工批准的项目级布局规则，
  因此严格适配必须保留 `product/src` 与 `product/tests`，不能机械复制空模板布局。
- 上游示例 completed plans 是 agentForge 自身历史，不属于 TrainLab，不复制。
- 第一次定向 pytest 使用了过期路径 `tests/test_product_packaging.py`，pytest 在收集前
  exit 4；同一计划内按仓库事实修正为 `tests/product_packaging/test_build_product.py`，
  随后 19 项通过。该诊断不产生新计划版本。
- 产品完整 pytest 未运行，因为本次差异只包含开发治理 Markdown，未触及任何产品行为；
  已运行全部直接适用的 repository-quality、静态与构建边界测试。
- 第一次独立 Validator 返回 `FAIL`：`memory.md` 的打包测试路径过期，且计划派发表和
  验证区仍写“待派发”。已在当前计划修正，并要求另一个全新独立 Validator 完整复验。
- 第二次独立 Validator 返回 `FAIL`：第三方声明把上游 MIT permission notice 缩写，
  未逐字保留包含条件与完整免责声明。现已按上游 `v0.4.2/LICENSE` 逐字恢复，并保留
  “只覆盖改编 Harness、不重新许可 TrainLab 产品”的范围说明。

## 任务级独立验证

- 中性交接：仅提供 0.4.2 上游基线、验收标准、适用规则、当前仓库结果和只读边界；
  不提供实施推理、辩护或预期结论。
- Validator 身份/上下文：Attempt 1 和 2 均为全新只读 Agent，分别因状态一致性和许可
  文本精确性返回 `FAIL`；Attempt 3 使用另一个全新只读 Agent 完整复验。
- 模型/推理档位：`high/high`。
- 命令与观察：Attempt 1 独立核验 tag、上游核心文件、diff、66 条根链接、产品
  quality、Ruff/format/mypy 和 19 项定向测试均通过；发现 memory 旧测试路径与计划
  派发状态不一致；Attempt 2 确认这些修复有效，但发现 MIT 文本被缩写。现已按上游
  LICENSE 逐字恢复；Attempt 3 复核上游 tag/LICENSE、全部协议覆盖、规则保全、目录边界、
  许可、链接、quality、Ruff/format/mypy、19 项定向测试和私有索引边界，返回 `PASS`。
- 结果：`PASS`
- 未满足项与剩余风险：无未满足项；因变更仅限根治理 Markdown，未运行完整产品 pytest，
  Validator 判定该跳过合理，残余风险低。

## 集成级独立验证

- 集成范围：不适用——单一串行任务，无并行集成。
- 结果：`不适用——无并行集成`

## PLANS 回写清单

- [x] Exec plan 已归档到 `completed/`
- [x] Roadmap 叶子任务已更新为 `[x] completed`——不适用，ADHOC 不写 Roadmap
- [x] 子项目和阶段状态已重新计算——不适用，ADHOC
- [x] `memory.md` 中的活动计划指针已删除

## 迭代日志

| 日期/上下文 | 已完成事项与证据 | 发现 | 下一动作 |
| --- | --- | --- | --- |
| 2026-08-12 / Loop 1 | Git 门禁、0.4.2 标签与核心文档完整读取、差异审计；完成适配和自检 | 当前为早期精简版且来源提交过期；一条计划测试路径过期并已依据仓库事实修正 | 独立只读验证 |
| 2026-08-12 / Loop 1 续 | 三轮全新只读验证：前两轮分别发现 memory/派发状态与 MIT 文本问题，修正后第三轮完整 PASS | 全部验收项满足 | 归档并交付 |
