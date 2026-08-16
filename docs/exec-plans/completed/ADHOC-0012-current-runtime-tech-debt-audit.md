# 执行计划：当前运行架构完成度与技术债审计

- 状态：`completed`
- 负责人：主协调 Agent
- Roadmap ID：`ADHOC-0012`
- 阶段/子项目：`不适用`
- Batch ID：`audit-read-only`
- 返工来源：`无`
- 开始日期：2026-08-16
- 最后更新：2026-08-16

## 目标与验收标准

- 以当前 Git、开发 Harness、`source/` 运行 Harness、SQLite/raw 和验证入口为事实源，客观判断
  ADHOC-0011 的完成度。
- 区分阻塞性缺口、需要尽快处理的技术债、可延后的维护债和已明确接受的非目标。
- 每项结论给出可复核证据、影响和建议，不自动修复、不自动加入 Roadmap。

## 范围与非目标

- 范围：根治理/CI/工作区、六个运行 Skills/cron/模板/测试、SQLite/raw/备份/恢复及隐私边界。
- 非目标：不修改产品代码和正式 state；不调用 Garmin、Gmail、Sites；不安装 cron；不提交或推送。

## 适用规则与参考资料

- 已批准规则：A-001、A-002、A-004、A-008。
- 按需读取的 references：无。

## 依赖与隔离

- 显式依赖：已完成的 ADHOC-0011。
- 共享接口和冻结依据：当前 `main` 工作树、completed plan 和 active state。
- 任务分支：`不适用——只读审计`
- Worktree：`不适用——只读审计`
- 集成分支：`不适用`
- 允许写入范围：本 exec plan 与 `memory.md` 活动指针；审计结束后归档并清除指针。
- 禁止写入范围：`source/**`、`source/state/**`、`data-backup/**`、Git index、外部服务。

## 功能与测试映射

`不适用——只读审计`。

## 工具采用情况

- 可执行技术栈：Python 3.12、SQLite、JSON、Markdown、GitHub Actions YAML。
- Linter 配置和命令：沿用 `memory.md` 已验证入口；所有 Python 检查禁用字节码写入。
- 测试框架：聚焦 Skill 合同测试；不重复无必要的历史完整测试。

## Subagent 派发

| Attempt | Agent 角色/任务 ID | 风险与复杂度 | 模型档位 | 推理档位 | 选档理由 | 平台支持 | 写入边界 | 产物与门禁 | 结果 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 治理与交付审计 | high | high | high | 大规模未提交迁移与规则一致性 | supported | 只读 | 完成度、CI/Git/治理债清单 | completed |
| 1 | Skills 与测试审计 | high | high | high | 新运行架构缺少传统集中式应用层 | supported | 只读 | 六 Skill 可运行性与测试真实性 | completed |
| 1 | 状态与恢复审计 | high | high | high | 私有 raw/SQLite/备份高风险边界 | supported | 只读 | 数据闭包、安全与恢复债清单 | completed |

## 工作分解

| 步骤 | 状态（`pending`、`in_progress`、`blocked`、`done`） | 证据 |
| --- | --- | --- |
| 1. 核对治理、Git 与目标结构 | `done` | 当前 worktree、HEAD clean export 与权威文件 |
| 2. 审计 Skills、cron、模板和测试 | `done` | 13 项测试、静态门、合成负向探针与源码通读 |
| 3. 审计 SQLite/raw/备份/恢复 | `done` | 正式库、raw、备份和旧归档只读闭包检查 |
| 4. 分级技术债并交付结论 | `done` | 三条独立证据链交叉核对 |

## 当前检查点

- 当前 Loop：审计已结束。
- 最近完成：治理、Skills、状态/恢复三条独立只读审计及本地主门复核。
- 当前焦点：无；等待用户决定是否把候选债项提升为后续开发任务。
- 下一动作：不自动实施；若继续，优先建立可重跑的本地无外部调用闭环，再讨论 Provider 启用。
- 阻塞项：无审计阻塞；运行启用阻塞见下方发现。
- 已变更文件：本 exec plan 与 `memory.md` 审计状态事实；未修改 `source/` 或正式 state。
- 待验证项：无。

## 决策与发现

### 客观完成度

- **本机结构与私人数据切换：通过。** 新 `source/` 树、六表 SQLite、9,336 个 raw、配对备份、
  权限和旧 state 归档均存在；正式库完整性、外键及 raw 双向哈希闭包通过，未发现数据丢失。
- **状态安全底座：大部分完成。** 六表均为 STRICT，现有 56 个触发器覆盖多数批准、SHA、修订和
  外部动作约束；当前库尚无批准或外部动作，未发生 Provider 副作用。
- **六个 Skill 的业务闭环：未完成。** 当前主要是窗口规划器、迁移器、证据外形扫描器、历史 ID
  选择器和外部动作准备器；只有本地报告渲染达到单次可运行。日报、周报、课表、Garmin/Gmail
  适配、对账与 workflow runner 尚未闭环。
- **cron：按批准范围只生成配置且保持关闭。** 但现有 JSON 不能直接执行：命令从 stdin 读 prompt，
  没有 host 把 `prompt_file` 接入，也没有锁、步骤恢复、备份和最终 receipt runner。
- **仓库交付：未完成。** 目标架构仍是大规模未提交工作树；HEAD clean checkout 仍为旧运行层。
  这符合 ADHOC-0011“不自动提交”的授权边界，但不能称为已形成可跨机、可 CI 复现的交付物。

### 启用前阻塞项

1. `record_skill_result()` 的重跑/修订路径与数据库约束冲突：相同输入重跑、同 logical key 新输入、
   第二个周期报告均可复现 `IntegrityError`。当前设计无法可靠重试、恢复或追加新修订。
2. 普通写连接在数据库缺失时会静默创建空库，且各 Skill 不持有 workflow lock；这与运行 Harness
   “缺库即停止”冲突，可能丢失原幂等与批准上下文。
3. `training-coach` 只返回 JSON 结构、XML 元素数和 FIT 消息类型，不生成睡眠、RHR/HRV、距离、
   配速、心率或圈段等有界指标；AI 又不得直接读 raw，因此无法做有证据的总结和排课。
4. 课程校验没有强制连续七天、硬负荷最多三次、课程语义推导、进阶/恢复和完整剂量安全合同；
   合成的跨度十天四次 hard 课表仍会通过。
5. Garmin/Gmail 仅有 no-network 准备器，没有 output/approval/action 绑定和 MCP 执行/对账；GTS
   只凭 `-GTS` 后缀接受不完整项目，Gmail HTML 只拒绝 `<script>`，会放行事件处理器、iframe 和
   远程跟踪资源。
6. 输出 lineage helper 默认写空数组；周历史在零日报/零周报时仍记成功；cron 输出 Schema 不要求
   `provider_calls`，也未约束逐步 receipt，不能作为安全门。
7. 备份没有接入 daily/weekly 或 `external_barrier`，没有当前持续测试覆盖的 full-bytes apply/rollback
   演练；active、唯一快照和旧归档均在同一磁盘。
8. clean checkout/CI 不成立：目标文件尚未提交，且合同测试直接读取被忽略的私有 `goal.md`；即使
   提交当前公开文件，干净 CI 也会失败。

### 技术债候选

- P1：恢复适配新结构的永久 repository-quality、Schema、模板安全和 tracked-private 门禁；当前 CI
  相比既有永久门明显缩窄。
- P1：补 clean-checkout bootstrap/restore 文档和仓库外合成实例 smoke，避免把本机私人实例当成
  可交付产品。
- P1：修正已完成动作在临时 approval 到期后被 verifier 判坏的逻辑；当前应只对非终态/重试检查
  现时有效性。
- P2：备份创建前运行完整合同校验并用实际代码/Skill SHA；保留 migration manifest 与逐行来源绑定。
- P2：修复 A-007 被包含在规则模板代码块、根/运行 Skill 路径措辞冲突、过时 CHANGELOG 和已退役
  TD-0001。
- P2：`requirements.txt` 无传递依赖哈希、GitHub Actions 未按提交 SHA 固定、YAML 只检查非空；
  属于用户选择简化依赖后的可复现性/供应链权衡。
- P2：正式测试仅 13 项且偏重数据库约束，缺 parse/history/cron/backfill/retry/course/credential/
  reconcile/HTML allowlist/第二周期和真实 restore apply 回归。
- P2：旧归档可取证但无整包 manifest/现行回滚手册；两项只有 GPX/TCX 的 activity 需确保消费者支持。
- P3：3,022 个 raw 路径为 5 组重复内容；`source/state/.DS_Store` 为 0644；一次性 candidate 迁移器
  仍留在日常 Skill；均不代表数据损坏。

上述债项仅作为本次审计候选，不自动写入技术债跟踪表、不自动加入 Roadmap。

## 任务级独立验证

- 中性交接：不适用；本任务本身为只读多方审计。
- Validator 身份/上下文：三名互不写入的审计 Agent。
- 模型/推理档位：high/high。
- 命令与观察：三名只读 Agent 分别审计 Git/CI/治理、六 Skills/cron/测试、SQLite/raw/恢复；主 Agent
  复跑 13 项 pytest、Ruff、format、mypy、AST/JSON/metadata、goal validator、`verify_state`、
  只读 backup verify 和 `git diff --check`，全部通过。
- 结果：`PASS——审计证据充分`；这不是对运行启用或业务闭环的 PASS。
- 未满足项与剩余风险：见“启用前阻塞项”和“技术债候选”。

## 集成级独立验证

- 结果：`不适用——无代码集成`

## PLANS 回写清单

- [x] Exec plan 已归档到 `completed/`
- [x] Roadmap 叶子任务：不适用
- [x] 子项目和阶段状态：不适用
- [x] `memory.md` 中的活动计划指针已删除

## 迭代日志

| 日期/上下文 | 已完成事项与证据 | 发现 | 下一动作 |
| --- | --- | --- | --- |
| 2026-08-16 / audit | Git/治理、六 Skills、SQLite/raw/恢复三条只读审计与本地主门完成 | 数据底座健康；业务闭环、重跑、clean CI 和启用前恢复仍有阻塞 | 向用户交付分级结论，等待是否提升候选债项 |
