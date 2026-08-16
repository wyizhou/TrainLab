# 执行计划：M7 AI + Skills 执行闭环与双层测试体系

- 状态：`completed`
- 负责人：主协调 Agent
- Roadmap ID：`M7`
- 阶段/子项目：`M7/AI + Skills runtime`
- Batch ID：`serial-m7`
- 返工来源：`无`
- 开始日期：2026-08-16
- 最后更新：2026-08-16

## 目标与验收标准

在 ADHOC-0011 已保存的本地基线上，完成离线、无外部副作用的 AI + Skills 日报/周报闭环：

1. 受管 SQLite 连接启用并确认 `recursive_triggers=ON`，append-only、幂等、重试、锁和
   workflow receipt 可由确定性测试证明；正式 `source/state` 不变。
2. 只保留一个无业务参数的自动 Prompt；HKT 槽位由脚本确定性解析，AI 不猜日期、不接受
   `daily`、`weekly` 或 `request-id` 参数。
3. candidate 中可用合成 raw 与模型输出完成 daily、Sunday weekly、report、未发送 Gmail
   信封和未执行 GTS 合同，全部写入 candidate SQLite；任何质量不足结构化 `blocked`。
4. `source/tests/code` 成为唯一确定性测试根，`source/tests/ai` 提供按需 AI 语义验收材料，
   不读取正式个人数据、不调用 Garmin/Gmail/Sites。
5. 全新只读集成 Validator `PASS` 后，建立第二个本地提交
   `feat: complete AI skills workflow and test harness`；不推送。

## 范围与非目标

范围：`source/skills` 的状态、resolver、受限解析器、输出合同、candidate-only workflow、
测试布局、质量门和两个本地提交。

非目标：不安装或启用 cron；不调用真实 Garmin/Gmail/Sites；不发送邮件、不创建或排期 Garmin
Workout；不修改正式 `source/state`、goal、凭据或 data-backup；不恢复旧集中式源码或统一 CLI；
不开展在线补数、正式状态切换、备份恢复实盘演练或外部动作授权。

## 适用规则与参考资料

- 已批准规则：A-001、A-002、A-004、A-008、A-009，以及根/运行 `AGENTS.md`。
- 参考资料：ADHOC-0011 completed plan、ADHOC-0012/0013 completed audits、Codex `exec`
  官方命令文档（仅用于 CLI 参数语义）。

## 依赖与隔离

- 显式依赖：本地基线提交 `2e63250 chore: checkpoint AI skills runtime migration`。
- 共享接口和冻结依据：六表 SQLite、raw-first、HKT 12:00 槽位、六个 Skills 的现有 SKILL.md。
- 任务分支：`不适用——用户批准在当前 main 串行本地执行`。
- Worktree：`不适用——不建立并行 worktree`。
- 集成分支：`不适用`。
- 允许写入范围：根治理/计划文件；`source/skills`；`source/tests/code`、`source/tests/ai`；
  CI/README/ignore；仓库外临时 candidate；两个本地 Git 提交。
- 禁止写入范围：`source/state/**`（除已跟踪 `.gitkeep` 骨架）；`source/goal.md`；凭据；
  `data-backup/**`；Garmin/Gmail/Sites；远端 Git。

## 功能与测试映射

| 功能 | Feature slug | 测试目录 | 必须满足的行为 |
| --- | --- | --- | --- |
| SQLite 状态与幂等 | `state-contract` | `tests/code/contract` | 受管连接、append-only、revision、lease、receipt、无 REPLACE 绕过 |
| HKT 自动槽位 | `auto-slot` | `tests/code/unit`、`tests/ai/cases` | 四个边界、Sunday dependency、过期/时钟回退安全停止 |
| raw 有界证据 | `bounded-evidence` | `tests/code/unit`、`tests/code/fixtures` | health/FIT/GPX/TCX/weather 只输出有限可追溯指标 |
| 日报/周报闭环 | `offline-workflow` | `tests/code/integration`、`tests/ai/cases` | daily→weekly 顺序、输出落库、blocked、不联网 |
| 报告/信封安全 | `report-envelope` | `tests/code/contract` | HTML、Gmail envelope、GTS contract 无外部副作用 |

## 工具采用情况

- 可执行技术栈：Python 3.12、SQLite、JSON Schema、pytest、Ruff、mypy、Codex `exec`（仅隔离
  AI evaluator）。
- Linter 配置和命令：现有 `skills/_shared/ruff.toml`、mypy 配置；新增 tests/code 后同步范围，
  使用 `ruff check`、`ruff format --check`、`mypy`、AST/compile 检查。
- 测试框架、定向命令和完整命令：`pytest tests/code -q`；AI 评测按需单独运行；最终执行全部
  JSON Schema、Markdown/Skill metadata、privacy/layout、`git diff --check` 和 clean checkout。

## Subagent 派发

| Attempt | Agent 角色/任务 ID | 风险与复杂度 | 模型档位 | 推理档位 | 选档理由 | 平台支持 | 写入边界 | 产物与门禁 | 结果 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 集成 Validator（M7-0005） | 高风险状态、边界、语义与隐私验证 | `high` | `high` | 独立检查完整离线闭环 | platform-default | 只读 | code/AI 门、candidate、正式 state 不变 | PASS |

## 工作分解

| 步骤 | 状态（`pending`、`in_progress`、`blocked`、`done`） | 证据 |
| --- | --- | --- |
| M7-0001 保存基线并更新治理 | `done` | 基线提交 `2e63250`；A-009、AGENTS、CI 与测试布局已写入 |
| M7-0002 状态合同与唯一自动入口 | `done` | 受管连接、append-only、重试、HKT resolver 与 `auto.txt` 已实现 |
| M7-0003 六个 Skills 离线业务闭环 | `done` | candidate daily/weekly、报告、未发送邮件与未执行 GTS 合同均可离线落库 |
| M7-0004 建立 code/ai 双层测试 | `done` | `tests/code` 31 项通过；`tests/ai` cases/rubrics/templates 已建立，AI 评测按需 |
| M7-0005 独立验证与第二个本地提交 | `done` | 全新集成 Validator PASS；第二个本地提交已建立；clean checkout 的 31 项测试、Ruff、format、mypy 通过 |

## 当前检查点

- 当前 Loop：5 / 5
- 最近完成：基线提交、状态合同、唯一 auto Prompt、candidate 离线 daily/weekly 闭环与双层测试目录均已实现。
- 当前焦点：M7 离线实现、独立验证、本地提交和 clean checkout 均已完成。
- 下一动作：如需启用真实 Provider、Gmail、Sites 或 cron，另立并申请新的在线阶段。
- 阻塞项：无；正式 state 与外部调用保持冻结，cron 仍未安装或启用。
- 已变更文件：本计划、PLANS、rules、memory、CI、Skills、schemas、tests/code、tests/ai。
- 待验证项：无；真实外部动作不属于 M7 范围。

## 决策与发现

- `request-id` 不属于 Codex `exec` CLI 参数；不进入公开命令。SQLite 内部 `id`、`run_key`、
  `workflow_key`、`dedupe_key` 足以追踪和幂等，未来 request id 只能由 host 自动生成。
- `output-schema` 仅为测试/外部程序读取最终回执的约束，不是普通运行的状态存储；SQLite receipt
  才是下一次 due 判断的事实源。
- 正式 source/state 已由用户删除 backups/recovery-quarantine；本阶段不主动重建，候选测试需使用
  仓库外临时目录。

## 任务级独立验证

- 中性交接：实现完成后只提供当前提交/工作区、允许路径、测试命令和验收标准，不提供实施者推理。
- Validator 身份/上下文：全新集成只读 Agent（`m7_final_validator_r4`）。
- 模型/推理档位：`high/high`。
- 命令与观察：31 tests；Ruff/format/mypy/compile；8 schemas；candidate verify_state；边界、幂等、权限和零外调检查。
- 结果：`PASS`
- 未满足项与剩余风险：真实 Provider、Gmail、Sites、cron 仍按计划未启用。

## 集成级独立验证

- 集成范围：M7 全部 code/AI、candidate workflow、正式 state 不变和 clean checkout。
- 中性交接：当前源码冻结快照、合成 candidate、M7 验收标准。
- Validator 身份/上下文：同一全新集成只读 Agent 的 AI 语义范围。
- 模型/推理档位：`high/high`。
- 完整 lint/test 与回归观察：31 tests；日报日期分桶；恢复红旗课表剂量；weekly activity_days；receipt/lineage/幂等；零外调。
- 结果：`PASS`
- 未满足项与剩余风险：真实 `codex exec` 模型运行和外部服务调用不在本阶段授权范围。

## PLANS 回写清单

- [x] Exec plan 已归档到 `completed/`
- [x] Roadmap 叶子任务已更新为 `[x] completed`
- [x] 子项目和阶段状态已重新计算
- [x] `memory.md` 中的活动计划指针已删除

## 迭代日志

| 日期/上下文 | 已完成事项与证据 | 发现 | 下一动作 |
| --- | --- | --- | --- |
| 2026-08-16 / M7-0001 | 基线提交 `2e63250` 建立；暂存私有路径检查为空 | 旧 A-008 测试路径仍需替换 | 更新 A-009 对应治理与测试入口 |
| 2026-08-16 / M7-0002 | `recursive_triggers=ON`、REPLACE 绕过回归、attempt 重试与 HKT noon resolver 已实现；旧 daily/weekly prompt/config 已删除 | `request-id` 不是 Codex CLI 参数 | 只保留 `auto.txt`，由 SQLite receipt 判断 due |
| 2026-08-16 / M7-0003/0004 | candidate 离线 daily→weekly→report→email envelope→GTS contract 通过；`source/tests/code` 21 passed；Ruff、format、mypy 全部通过 | 真实 Codex AI 评测启动曾卡在模型启动阶段，未调用外部服务 | 交给全新 Code/AI Validator；如 AI 服务仍不可用保持 validating |
| 2026-08-16 / M7-0003 修正 | 发现离线 raw 未登记会使 `verify_state` 报 `raw_unregistered_file`；新增 `garmin-sync/scripts/index_raw.py`，先校验模式/日期/SHA 并写入 `raw_files`，再进入日报 | 现有 candidate 需用新脚本重建，旧 AI 回执不再作为最终证据 | 重新冻结源码后交给全新 Code/AI Validator |
| 2026-08-16 / M7-0005 rework | 独立 Code Validator 发现输出未实校验、租约/身份未冻结、重复 index 产生修订、raw 指标不足、weekly 依赖未强制；已补本地 Schema 验证、HKT workflow 锁/lease、run identity trigger、稳定 index 输出、bounded metrics、Sunday receipt gate 与回归案例 | 上一轮 Validator 结果作废，不作为最终 PASS | 冻结当前源码，重新派发全新 Code/AI Validator |
| 2026-08-16 / M7-0005 rework-02 | 修复日报 review/sleep 分离门、Schema 日期与字段边界、严格课表剂量/RPE/降级/停止合同、weekly fitness review 输出、日报最多14份历史摘要、FIT bounded activity metrics、weather/FIT/AI 布局回归；`pytest source/tests/code` 27 passed，Ruff、format、mypy 通过 | 尚未完成独立验证；正式 state 与外部调用保持冻结 | 冻结工作区，派发全新 Code/AI Validator |
| 2026-08-16 / M7-0005 rework-03 | 修复恢复红旗攀岩步骤剂量一致性；`pytest source/tests/code` 30 passed，Ruff、format、mypy 通过 | 集成 Validator 发现日报将昨日睡眠/今日活动混入错误分桶 | 按日期与资源过滤 review/sleep 证据并补回归 |
| 2026-08-16 / M7-0005 final | review 仅保留 D-1 非睡眠证据，sleep 仅保留 D 日睡眠；新增 4 活动/短睡边界回归；`pytest source/tests/code` 31 passed；Ruff、format、mypy、compile、8 schemas 通过；集成 Validator PASS | 无；candidate、正式 state、Git 状态与外部调用均保持冻结 | 检查公开暂存范围、建立第二个本地提交并做 clean checkout |
