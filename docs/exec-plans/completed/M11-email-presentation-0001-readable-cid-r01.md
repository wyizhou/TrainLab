# 执行计划：M11 v3 八封 Gmail 真实投递

- 状态：`completed`
- 负责人：主协调 Agent
- Roadmap ID：`M11-0015`
- 阶段/子项目：`M11/live-v3-delivery`
- Batch ID：`serial-m11-v3-live-r01`
- 返工来源：`docs/exec-plans/completed/M11-email-presentation-0001-readable-cid.md`
- 开始日期：2026-08-23
- 最后更新：2026-08-23

## 目标与验收标准

使用已通过三类独立验收的 M11 v3 r06 离线结果，通过官方 Gmail REST 严格串行自投递：

1. `TrainLab · 每日训练简报 · 2026-08-12` 至 `2026-08-18`，共7封；
2. `TrainLab · 每周总结 · 2026-08-12~2026-08-18`，共1封。

每封必须具有唯一 Gmail ID、实际 RFC822 Message-ID 和闭合的 RAW、HTML、text、CID 证据；
累计恰好8次成功动作，无 `unknown/in_progress`。投递后重放的 Provider 调用与SQLite增量为0。

## 范围与非目标

- 范围：版本化 v3 Live Candidate、确定性收件人MIME、Gmail REST串行发送、RAW/CID核验、
  崩溃只读恢复、权限/隐私/正式state核验、Code与Delivery/Data-Privacy独立验证。
- 非目标：重跑Garmin、Codex、AI、日报、周报或课表；修改邮件内容/样式；Workout、Sites、cron、
  正式state迁移、提交、推送、部署。
- 用户已一次性明确授权全部8封，无需第一封后的额外人工放行；每封仍须远端闭合后才领取下一封。
- “出现问题可修复后继续”仅允许修复实现并继续尚未发送的动作；任何已进入`unknown`的动作只读
  对账且停止批次，不允许自动再发或改用新的Message-ID规避单次发送合同。

## 适用规则与参考资料

- 已批准规则：A-004、A-008、A-009、A-010、A-011、A-013、A-014、A-015、A-016、A-017。
- 按需读取的 references：M11 r06 Candidate
  `/private/tmp/trainlab-m11-v3-r06.T6nbtk`；已归档M11计划；`gmail-sender` Skill。

## 依赖与隔离

- 显式依赖：M11-0014 completed；r06三类Validator全部PASS；现有OAuth认证与owner-only收件配置。
- 共享接口和冻结依据：8份r06 render/MIME、A-010/A-011 REST单写者、Gmail actual Message-ID核验。
- 任务分支：`不适用——用户未授权分支或提交`
- Worktree：`不适用`
- 集成分支：`不适用`
- 允许写入范围：本计划、PLANS/memory/CHANGELOG/rules；`source/skills/gmail-sender/**`、
  `source/skills/_shared/schemas/**`、`source/tests/code/**`；仓库外owner-only Live Candidate；
  专用OAuth token的正常原子刷新。
- 禁止写入范围：正式`source/state/**`、r06 Candidate、AI/课表84–93、goal、OAuth client、旧投递
  Candidate/证据、远端Git、Garmin/Workout/Sites/cron。

## 功能与测试映射

| 功能 | Feature slug | 测试目录 | 必须满足的行为 |
| --- | --- | --- | --- |
| v3八封Live Candidate | `m11-v3-live-batch` | `source/tests/code/integration` | 精确8项、r06字节绑定、新Message-ID、owner-only、正式state不变 |
| Gmail REST串行投递 | `m11-v3-live-delivery` | `source/tests/code/{contract,integration}` | intent先行、每封send≤1、RAW/CID闭合、成功后才领取下一封 |
| 崩溃与重放 | `m11-v3-live-recovery` | `source/tests/code/integration` | 响应丢失只读恢复、unknown停止、重放send=0/SQLite增量0 |

## 工具采用情况

- 可执行技术栈：Python 3.12、SQLite、官方Gmail REST、OAuth、MIME/CID。
- Linter 配置和命令：`ruff --config skills/_shared/ruff.toml check skills tests/code`；
  `ruff format --check skills tests/code`；`mypy --config-file skills/_shared/mypy.ini skills tests/code`。
- 测试框架、定向命令和完整命令：`pytest tests/code -q`、只读compile、全部Schema/metadata/Markdown、
  权限/隐私/布局、`git diff --check`。

## Subagent 派发

| Attempt | Agent 角色/任务 ID | 风险与复杂度 | 模型档位 | 推理档位 | 选档理由 | 平台支持 | 写入边界 | 产物与门禁 | 结果 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Code Validator / M11-0015 | 高：真实外部写入前的8项状态机与崩溃恢复 | high | high | Gmail真实发送、幂等和隐私均为高风险 | available | 只读 | 完整测试/静态门、Fake REST、r06绑定、send≤1 | PASS：600全量/44 Live、r06 9472 manifest/8 MIME/37 CID、严格串行/unknown/重放、旧入口和隐私门全部通过；网络/Provider 0 |
| 1 | Delivery/Data-Privacy Validator / M11-0015 | 高：8项远端事实、私人Candidate和正式边界 | high | high | 真实投递后必须独立验证远端证据与隐私 | available | 只读 | 8 Gmail ID/RAW、重放0、state/Token/Git边界 | PASS：8项succeeded/attempt=1，8个Gmail ID与实际Message-ID互异，32 REST/8 send、RAW/text/HTML/CID闭合，state/Token/Git与零越界调用通过 |

## 工作分解

| 步骤 | 状态（`pending`、`in_progress`、`blocked`、`done`） | 证据 |
| --- | --- | --- |
| M11-0015-01 冻结授权、r06/OAuth/收件人/正式state基线 | done | r06 DB/build receipt SHA、owner-only收件/OAuth/Token和正式state指纹均只读核对通过；Provider调用0 |
| M11-0015-02 实现参数化v3八封REST批次与回归 | done | 新v3 marker/固定策略/根manifest/唯一item_key/严格串行/动态N项验证；44项Live定向测试PASS |
| M11-0015-03 完整代码门与全新Code Validator | done | 600 tests、Ruff、format、mypy、compile、65 Schema、metadata/Markdown、隐私/Git/diff全部PASS；全新high/high只读Code Validator PASS |
| M11-0015-04 建立Live Candidate并严格串行发送8封 | done | 新Candidate `trainlab-m11-v3-live-r01.k2jDQJ`发送前8项均为prepared/0尝试；真实Gmail REST严格串行完成8项，32次API、8次send、0 unknown |
| M11-0015-05 重放、最终边界和Delivery/Data-Privacy Validator | done | final verify PASS；重放Provider增量0、SQLite逻辑增量0、非DB产物增量0；全新high/high最终Validator PASS |

## 当前检查点

- 当前 Loop：M11 v3八封真实Gmail投递已完成。
- 最近完成：8封真实投递、RAW/CID闭合、零调用重放与Delivery/Data-Privacy Validator PASS。
- 当前焦点：已完成并归档。
- 下一动作：无；部署与定时运行仍需新的明确计划和授权。
- 阻塞项：无。
- 已变更文件：本exec plan；Roadmap/memory/rules待同步。
- 待验证项：无。

## 决策与发现

- 旧M11 Live入口只绑定历史两封canary，不能直接冒充v3八封授权；新批次只参数化复用底层单写者。
- 用户批准全部8封，因此不增加人工canary停点；仍严格逐封远端闭合。

## 任务级独立验证

- 中性交接：仅提供冻结8项范围、A-010/A-011/A-013/A-017、当前代码与Candidate。
- Validator 身份/上下文：`m11_v3_live_delivery_validator`，全新只读Agent。
- 模型/推理档位：high/high。
- 命令与观察：只读权限审计、SQLite immutable integrity/FK与证据链查询、Python 3.12正式MIME校验、Git ignore/privacy/diff检查；8/8远端链闭合，32 REST/8 send，无越界Provider。
- 结果：`PASS`
- 未满足项与剩余风险：无未满足项；未单独生成replay receipt，但终态marker、capture计数、SQLite逻辑与非DB产物零增量提供中等强度重放证据。

## 集成级独立验证

- 集成范围：严格串行，无并行集成。
- 中性交接：不适用。
- Validator 身份/上下文：不适用。
- 模型/推理档位：不适用。
- 完整 lint/test 与回归观察：由任务级Validator覆盖。
- 结果：`不适用——无并行集成`
- 未满足项与剩余风险：无。

## PLANS 回写清单

- [x] Exec plan 已归档到`completed/`
- [x] Roadmap叶子任务已更新为`[x] completed`
- [x] 子项目和阶段状态已重新计算
- [x] `memory.md`中的活动计划指针已删除

## 迭代日志

| 日期/上下文 | 已完成事项与证据 | 发现 | 下一动作 |
| --- | --- | --- | --- |
| 2026-08-23 / start | 用户明确授权发送7份日报与1份周报，并允许修复实现后继续尚未发送项 | 旧Live入口只支持历史两封，不可扩大解释为v3八封 | 建立版本化薄适配器与Fake REST回归，Code PASS后才真实发送 |
| 2026-08-23 / preflight | r06数据库与build receipt冻结SHA、私有收件配置、OAuth回执、Token权限和正式state指纹全部只读通过；无Provider调用 | r06使用根`declared_files`闭包且7个日报共享`kind=daily`，旧per-preview receipt与kind身份均不可复用 | 以唯一`action_key`和根manifest实现v3策略，旧v1/v2入口保持兼容 |
| 2026-08-23 / code-gates | 测试先行新增v3批次Schema与6项回归；参数化同一Live Adapter，保留v1/v2。600 tests、Ruff/format/mypy/compile、65 Schema、6 Skill metadata、19 Markdown、隐私/Git/diff门PASS | 旧`validate_schema`未注册本地跨Schema引用，会尝试解析伪域名；已改为完整本地Registry，离线闭合 | 派发全新high/high只读Code Validator；PASS前不建立真实Candidate、不调用Gmail |
| 2026-08-23 / live-complete | Code Validator PASS后建立新Candidate，严格串行完成32 REST/8 send；8项RAW/CID与远端ID闭合，零调用重放和最终Validator PASS | SQLite checkpoint可能改变容器字节但逻辑内容无增长；最终Validator确认不构成重复输出 | 归档M11-0015；部署与定时运行留待新授权 |
