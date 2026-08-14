# 执行计划：M5 自适应教练画像与本地报告校准

- 状态：`completed`
- 负责人：主协调 Agent
- Roadmap ID：`M5`
- 阶段/子项目：`M5/自适应教练画像与本地报告校准`
- Batch ID：`serial`
- 返工来源：无
- 开始日期：2026-08-14
- 最后更新：2026-08-14

## 目标与验收标准

在 M4 已验证的 `bab3649` 基线之上，建立可审计的 AI 教练画像提案/确认流程、动态周容量
评估和隔离报告预览。画像应用必须保留无关配置、原子写入并保留 owner-only 备份；容量
评估只能使用完整且可追溯的本地窗口；周报和日报预览必须在仓库外隔离实例中生成，且
正式数据库摘要、delivery 状态、Garmin/Gmail transport 均不改变。

完成条件：画像、容量、排课和预览聚焦测试通过；完整 pytest、`mypy src`、Ruff、
format-check、compile、Schema、repository quality、布局、隐私和 diff 门通过；全新的
只读 Validator `PASS`。Validator 通过前不归档计划、不提交 M5 代码、不发送报告。

## 范围与非目标

范围：

- `source/src` 内 coaching profile、容量评估、课程约束、预览渲染及其唯一 CLI 路由；
- `source/src/resources/harness` 的 M5 schema/policy 资源；
- `source/tests/<feature-slug>/` 下的画像、容量、排课、预览回归测试；
- 仓库外 owner-only 隔离实例、临时报告和验证日志（不纳入 Git）。

非目标：

- 不调用 Garmin/Gmail，不刷新凭据，不补数，不生成正式分析，不发送邮件；
- 不修改正式 `source/state`、正式配置中的非画像字段或生产数据；
- 不恢复 Orchestration、Supervisor、Graph/Dashboard、handoff hash 或旧 bundle 流程；
- 不清零 `tests/tools` 类型债 TD-0001；
- 不在 M5 期间自动提交、推送、发布或部署。

## 适用规则与参考资料

- 已批准规则：A-001、A-002、A-004、A-007；本计划的外部影响和隐私边界优先。
- 产品运行 Harness：`source/src/resources/harness/shared/HARNESS.md`、
  `source/src/resources/harness/analysis/HARNESS.md`。
- M4 验证基线：提交 `bab3649`；最近完成计划：
  `docs/exec-plans/completed/M4-source-root-0001-product-consolidation.md`。
- 用户已确认的 M5 画像默认值只限本计划中列出的保守默认；不从 PersonalHealth 或聊天
  自动预填长期容量、频率、长跑上限或比赛目标。

## 依赖与隔离

- 显式依赖：M4 完成并已提交；任务按 M5-0001 → M5-0002 → M5-0003 → M5-0004 串行。
- 共享接口和冻结依据：`coaching_profile_contract_v1`、新增
  `weekly_capacity_assessment_v1`、现有 `course_contract_v2`、当前 `analysis_result`。
- 任务分支：`不适用——用户要求单一本地 main 基线，后续不自动创建分支`。
- Worktree：`不适用——单一主工作树串行执行`。
- 集成分支：`不适用`。
- 允许写入范围：上述源代码、schema、测试、治理计划，以及仓库外隔离临时目录；画像
  apply 仅在用户已批准的 M5 本地流程中允许写 `source/config/trainlab.json` 和
  `source/state/coaching-profile/`，不写其他正式数据。
- 禁止写入范围：Garmin/Gmail 网络、凭据、`source/state/data.db`（正式库）、正式报告
  交付状态、远端 Git、用户级 Skill、`data-backup`。

## 功能与测试映射

| 功能 | Feature slug | 测试目录 | 必须满足的行为 |
| --- | --- | --- | --- |
| 画像提案与应用 | `coaching-profile` | `source/tests/coaching-profile/` | schema、非法字段、确认前不变、备份、原子写入、权限、无关字段保全 |
| 动态容量与排课 | `adaptive-capacity` | `source/tests/adaptive-capacity/` | 完整周中位数、进阶区间、长跑/频率/硬负荷门、无比赛配速、单维度进阶 |
| 本地报告预览 | `report-preview` | `source/tests/report-preview/` | 隔离库、周→日报顺序、HTML/JSON、0600、无 delivery/Garmin/Gmail 副作用 |

## 工具采用情况

- 可执行技术栈：Python 3.12、SQLite、JSON Schema Draft 2020-12、HTML 模板。
- Linter 配置和命令：从 `source/` 执行 Ruff check/format-check、`mypy src`、compile、
  schema、repository quality、source-layout 和隐私扫描。
- 测试框架、定向命令和完整命令：`python -m pytest <feature tests>`；全部完成后仅
  启动一次 `python -m pytest`，保留隔离日志和原子退出标记。

## Subagent 派发

| Attempt | Agent 角色/任务 ID | 风险与复杂度 | 模型档位 | 推理档位 | 选档理由 | 平台支持 | 写入边界 | 产物与门禁 | 结果 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| — | 不适用 | 严格串行且由主协调 Agent 实施 | platform-default | platform-default | 用户明确要求串行 | 本地工作树 | 仅本计划范围 | 独立 Validator 最终 PASS | PASS |

## 工作分解

| 步骤 | 状态（`pending`、`in_progress`、`blocked`、`done`） | 证据 |
| --- | --- | --- |
| M5-0001 保存 M4 单一本地基线 | `done` | `bab3649`, `git status` clean（忽略项除外） |
| M5-0002 画像 schema、提案、确认应用和回归测试 | `done` | 画像 CLI、私有备份/审计和画像聚焦测试通过；默认画像已在正式配置中应用，非画像字段保全 |
| M5-0003 动态周容量、硬负荷和排课接入 | `done` | `weekly_capacity_assessment_v1`、主机容量门、分析结果容量校验和容量测试通过 |
| M5-0004 隔离周报/日报及 HTML/JSON 预览 | `done` | 预览读取/写出模块、隔离 SQLite 备份和预览测试已实现；真实隔离数据因 activity_stage_incomplete/安全候选拒绝按合同延期，未伪造 delivery |
| 独立 Validator 与归档 | `done` | 全新只读 Validator PASS；完整测试 exit 0，静态/隐私/正式数据保全门通过 |

## 当前检查点

- 当前 Loop：M5-0004 / 已完成
- 最近完成：画像提案/确认应用、动态容量评估和结果容量门已实现并通过聚焦测试。
- 当前焦点：在仓库外隔离实例生成周报/日报并写出只读 HTML/JSON 预览。
- 下一动作：计划已归档，等待用户审核；不自动提交 M5 代码、不发送报告。
- 阻塞项：无。真实 clone 的目标周活动阶段存在 `activity_stage_incomplete`，日报候选在安全门被拒绝；按合同延期且未伪造 delivery/报告。
- 已变更文件：M5 画像、容量、预览和运行时边界代码及对应测试。
- 待验证项：无；报告预览需在数据覆盖完整且安全候选可接受时另行运行。

## 决策与发现

- M4 基线提交不包含任何私有 state/config/logs、凭据、缓存、数据库、FIT 或 `data-backup`。
- 长期画像中的容量、频率、长跑上限和比赛目标初始为空；默认训练星期和硬负荷边界来自用户批准的 M5 合同。
- 周容量由主机从完整周证据计算，AI 只在安全区间内选择课程；越界结果由主机拒绝。
- 预览使用仓库外临时实例和 SQLite 一致性备份，正式库前后摘要必须一致。

## 任务级独立验证

- 中性交接：在所有 M5 代码完成、完整门禁通过后提供当前工作树、测试日志、配置/正式库摘要和隔离预览路径类别；不提供健康正文、凭据或邮件内容。
- Validator 身份/上下文：`m5_final_validator` 与 `m5_final_validator_followup`，均未参与实现。
- 模型/推理档位：至少 medium/medium；高风险数据与隐私边界使用 high/high。
- 命令与观察：待执行。
- 结果：`PASS`
- 未满足项与剩余风险：真实数据质量仍会使预览延期；不构造替代报告。

## 集成级独立验证

- 集成范围：M5-0002 至 M5-0004 全部串行变更。
- 中性交接：同任务级交接，额外核对正式 `source/state` 字节摘要、delivery 状态和 transport 调用计数。
- Validator 身份/上下文：`m5_final_validator_followup`，未参与实现。
- 模型/推理档位：high/high。
- 完整 lint/test 与回归观察：完整 pytest exit 0；`mypy src`、Ruff、format、compile、Schema、quality、layout、diff/privacy 全部通过。
- 结果：`PASS`（严格串行，无并行集成）
- 未满足项与剩余风险：真实隔离数据覆盖不足导致 weekly 延期、daily 安全拒绝；这是合同要求的 fail-closed 终态。

## PLANS 回写清单

- [x] Exec plan 已归档到 `completed/`
- [x] Roadmap 叶子任务已更新为 `[x] completed`
- [x] 子项目和阶段状态已重新计算
- [x] `memory.md` 中的活动计划指针已删除

## 迭代日志

| 日期/上下文 | 已完成事项与证据 | 发现 | 下一动作 |
| --- | --- | --- | --- |
| 2026-08-14 / initial | M4 基线 `bab3649` 已提交；M5 计划已创建 | M5 代码尚未开始 | 实现 M5-0002 |
| 2026-08-14 / profile-capacity | 画像默认值已原子应用；容量 schema/主机评估/结果校验完成，聚焦测试通过 | 完整历史库的可选活动明细超过 bounded snapshot；预览需显式收窄可选明细 | 完成只读预览入口与隔离实例验收 |
| 2026-08-14 / final-validation | `mypy src`、Ruff、format、Schema、quality、layout、compile 与聚焦回归通过；唯一主协调完整 pytest 发现 2 个与新增 `coaching`/容量预览模块冲突的旧断言，已按批准接口更新并通过对应回归 | 主协调完整套件不再重跑；由全新 Validator 在修复后的快照上独立复核 | Validator 读取当前快照并给出 PASS/FAIL |
| 2026-08-14 / validator-followup | 补充容量 `hold` 独立回归并通过；不改变生产源码或正式数据 | 真实隔离库仍按覆盖不足合同延期，未产生可预览 delivery | 新 Validator 判定 fail-closed 延期是否满足 M5-0004 |
| 2026-08-14 / completed | 全新只读 Validator PASS；45 项 M5/边界聚焦、`mypy src` 0、完整 pytest exit 0、Ruff/format/Schema/quality/layout/compile/diff/privacy 全通过；正式 DB/config 摘要不变 | 真实 clone 的 weekly/daily 分别延期/安全拒绝，故无真实 delivery；fake-delivery 预览已验证 HTML/JSON/0600/无副作用 | 归档计划，等待用户审核与后续明确授权 |
