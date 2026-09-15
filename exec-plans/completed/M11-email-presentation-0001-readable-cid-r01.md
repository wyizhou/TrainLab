# 执行计划：M11 v3 八封 Gmail 真实投递

## 对应目标

- 功能编号：M11-0015
- 功能状态：[completed]
- 总计划对应条目：[PLAN.md](../../PLAN.md) 的同编号/原Roadmap关联条目。
- 目标及范围和验收要求的引用：历史目标、范围、每个阶段/任务、验收要求及全部执行证据按对应原件保存；不是新的实施授权。
- 迁移说明：只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 当前协作规则仅以[AGENTS.md](../../AGENTS.md)为准；原合同及旧规范在快照中仅作历史来源，不继续生效为第二套流程。

## 阶段与任务

以下逐项迁移原实施分解；任务名称、已有编号、结果及明确依赖保留。原无编号步骤按原表顺序首次赋予L编号，不重编号已有步骤。HISTORY仅是原单阶段的归组，不再替代实际任务。此表描述历史工作，不是当前可执行规范/示例或外部授权；暂停条件见检查点。

| 阶段编号 | 状态 | 预期成果 | 依赖 |
| --- | --- | --- | --- |
| HISTORY | [completed] | 工作分解；保留原逐项成果/未完成边界 | 原前置要求及总计划同编号依赖；未另列的依赖不新增 |

| 任务编号 | 所属阶段 | 状态 | 输入输出及错误边界 | 依赖 | 检查方法 | 结果与证据（检查命令或人工方式、退出结果及关键证据） |
| --- | --- | --- | --- | --- | --- | --- |
| M11-0015-01 | HISTORY | [completed] | M11-0015-01 冻结授权、r06/OAuth/收件人/正式state基线；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原表未单列；沿用原功能前置条件，不按编号新增依赖；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：证据：r06 DB/build receipt SHA、owner-only收件/OAuth/Token和正式state指纹均只读核对通过；Provider调用0；原完成范围不扩大；对应原执行计划 L78 |
| M11-0015-02 | HISTORY | [completed] | M11-0015-02 实现参数化v3八封REST批次与回归；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原表未单列；沿用原功能前置条件，不按编号新增依赖；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：证据：新v3 marker/固定策略/根manifest/唯一item_key/严格串行/动态N项验证；44项Live定向测试PASS；原完成范围不扩大；对应原执行计划 L79 |
| M11-0015-03 | HISTORY | [completed] | M11-0015-03 完整代码门与全新Code Validator；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原表未单列；沿用原功能前置条件，不按编号新增依赖；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：证据：600 tests、Ruff、format、mypy、compile、65 Schema、metadata/Markdown、隐私/Git/diff全部PASS；全新high/high只读Code Validator PASS；原完成范围不扩大；对应原执行计划 L80 |
| M11-0015-04 | HISTORY | [completed] | M11-0015-04 建立Live Candidate并严格串行发送8封；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原表未单列；沿用原功能前置条件，不按编号新增依赖；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：证据：新Candidate `trainlab-m11-v3-live-r01.k2jDQJ`发送前8项均为prepared/0尝试；真实Gmail REST严格串行完成8项，32次API、8次send、0 unknown；原完成范围不扩大；对应原执行计划 L81 |
| M11-0015-05 | HISTORY | [completed] | M11-0015-05 重放、最终边界和Delivery/Data-Privacy Validator；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原表未单列；沿用原功能前置条件，不按编号新增依赖；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：证据：final verify PASS；重放Provider增量0、SQLite逻辑增量0、非DB产物增量0；全新high/high最终Validator PASS；原完成范围不扩大；对应原执行计划 L82 |

## 当前检查点

- 工作目录与分支：项目根；本次格式迁移在work/adhoc-0029-agentsmd-upgrade，原执行目录/分支仅见历史证据。
- 验收要求与受验版本及未提交改动：本轮迁移基准ec36ce7bbdf9d70a509238dd771b155eb6f84261；原受验版本/未提交内容/合同全文保留于快照。不得把迁移HEAD当作原产品受验版本。
- 最近完成：仅迁移当前记录结构与路径；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。
- 下一动作：保留历史定位，不恢复原业务或重判历史结果。
- 暂停原因：无新的暂停；历史已完成范围只作记录，不是当前运行证明。
- 恢复条件：已完成范围不需重做；已取消/暂停部分不在当前待办，恢复前须用户另行明确目标/授权并核对原失败次数。
- PR 与交付情况：本轮只迁移记录，不提交/推送/PR。原Git交付事实及未知项保留于原件，不推断后续远端状态。

## 问题记录

原有明确问题编号保留；无编号记录首次按不可变源行号分配ISSUE-L编号。每行是原记录索引，可能含规范、观察、裁决或后续动作；重复引用不重新累计事件，也不把原未量化的计数清零。

| 稳定问题编号 | 对应要求与实际问题 | 已尝试修法 | 累计失败次数 | 证据及处理结果 |
| --- | --- | --- | --- | --- |
| 无单独故障条目 | 原计划未单列实际故障；具体检查/结果见任务表及原文 | 不新增或推断修法 | 原未给累计值，不补造0 | 保留原件；本轮不追溯重判历史 |

## 历史目标与原编号索引

下文仅引用当时目标，不是现行规范或可运行示例；已经被新方案替代的业务不复活。原阶段/任务已在上表逐项迁移；原早期状态与最终范围不同的映射依据逐项标明，不借迁移扩大历史完成范围。

> 使用已通过三类独立验收的 M11 v3 r06 离线结果，通过官方 Gmail REST 严格串行自投递：
>
> 1. `TrainLab · 每日训练简报 · 2026-08-12` 至 `2026-08-18`，共7封；
> 2. `TrainLab · 每周总结 · 2026-08-12~2026-08-18`，共1封。
>
> 每封必须具有唯一 Gmail ID、实际 RFC822 Message-ID 和闭合的 RAW、HTML、text、CID 证据；
> 累计恰好8次成功动作，无 `unknown/in_progress`。投递后重放的 Provider 调用与SQLite增量为0。

原阶段/任务及其结果见上表，原问题及计数见问题记录；额外来源标识仍可在迁移清单中检索，原件供逐行核对。

## 原任务定义与验收

本节承接原任务定义的全部内容，而非仅保留状态摘要或指向压缩包。上表每个原任务的输入输出/错误边界及检查方法均关联本节；原文有同编号专属标题时另外关联该精确段落，公共目标/范围/合同与其他定义完整保留在本节。不得把原表中的“已接入/PASS”当作完整定义。

**适用性：全部引文均属于该历史任务的原目标、合同修订和执行记录，不是当前开发协议、可运行示例或新的业务授权。** 多版本材料按原任务编号、版本和日期定位，不把后续规则回套早期结果。旧流程/命令/目录和“当前”措辞只描述原记录时点；根AGENTS是唯一现行协作规则，暂停/取消按本文件的新检查点处理，不恢复旧产品。

为保留可核查语义，原件按标题和源行完整投射为引用块；只增加引用前缀，并将旧Markdown导航链接显示为“原定位”文字，未更改原件。原字节/原哈希由history.zip及history-manifest.json证明，不把显示投射声称为原字节。全部源行连续覆盖，原始执行/协调记录也标为历史数据，不混入当前阶段状态。

### 原定义-L1

来源标题：原文导言；原件L1–L11。

> # 执行计划：M11 v3 八封 Gmail 真实投递
>
> - 状态：`completed`
> - 负责人：主协调 Agent
> - Roadmap ID：`M11-0015`
> - 阶段/子项目：`M11/live-v3-delivery`
> - Batch ID：`serial-m11-v3-live-r01`
> - 返工来源：`docs/exec-plans/completed/M11-email-presentation-0001-readable-cid.md`
> - 开始日期：2026-08-23
> - 最后更新：2026-08-23
>

### 原定义-L12

来源标题：目标与验收标准；原件L12–L21。

> ## 目标与验收标准
>
> 使用已通过三类独立验收的 M11 v3 r06 离线结果，通过官方 Gmail REST 严格串行自投递：
>
> 1. `TrainLab · 每日训练简报 · 2026-08-12` 至 `2026-08-18`，共7封；
> 2. `TrainLab · 每周总结 · 2026-08-12~2026-08-18`，共1封。
>
> 每封必须具有唯一 Gmail ID、实际 RFC822 Message-ID 和闭合的 RAW、HTML、text、CID 证据；
> 累计恰好8次成功动作，无 `unknown/in_progress`。投递后重放的 Provider 调用与SQLite增量为0。
>

### 原定义-L22

来源标题：范围与非目标；原件L22–L31。

> ## 范围与非目标
>
> - 范围：版本化 v3 Live Candidate、确定性收件人MIME、Gmail REST串行发送、RAW/CID核验、
>   崩溃只读恢复、权限/隐私/正式state核验、Code与Delivery/Data-Privacy独立验证。
> - 非目标：重跑Garmin、Codex、AI、日报、周报或课表；修改邮件内容/样式；Workout、Sites、cron、
>   正式state迁移、提交、推送、部署。
> - 用户已一次性明确授权全部8封，无需第一封后的额外人工放行；每封仍须远端闭合后才领取下一封。
> - “出现问题可修复后继续”仅允许修复实现并继续尚未发送的动作；任何已进入`unknown`的动作只读
>   对账且停止批次，不允许自动再发或改用新的Message-ID规避单次发送合同。
>

### 原定义-L32

来源标题：适用规则与参考资料；原件L32–L37。

> ## 适用规则与参考资料
>
> - 已批准规则：A-004、A-008、A-009、A-010、A-011、A-013、A-014、A-015、A-016、A-017。
> - 按需读取的 references：M11 r06 Candidate
>   `/private/tmp/trainlab-m11-v3-r06.T6nbtk`；已归档M11计划；`gmail-sender` Skill。
>

### 原定义-L38

来源标题：依赖与隔离；原件L38–L50。

> ## 依赖与隔离
>
> - 显式依赖：M11-0014 completed；r06三类Validator全部PASS；现有OAuth认证与owner-only收件配置。
> - 共享接口和冻结依据：8份r06 render/MIME、A-010/A-011 REST单写者、Gmail actual Message-ID核验。
> - 任务分支：`不适用——用户未授权分支或提交`
> - Worktree：`不适用`
> - 集成分支：`不适用`
> - 允许写入范围：本计划、PLANS/memory/CHANGELOG/rules；`source/skills/gmail-sender/**`、
>   `source/skills/_shared/schemas/**`、`source/tests/code/**`；仓库外owner-only Live Candidate；
>   专用OAuth token的正常原子刷新。
> - 禁止写入范围：正式`source/state/**`、r06 Candidate、AI/课表84–93、goal、OAuth client、旧投递
>   Candidate/证据、远端Git、Garmin/Workout/Sites/cron。
>

### 原定义-L51

来源标题：功能与测试映射；原件L51–L58。

> ## 功能与测试映射
>
> | 功能 | Feature slug | 测试目录 | 必须满足的行为 |
> | --- | --- | --- | --- |
> | v3八封Live Candidate | `m11-v3-live-batch` | `source/tests/code/integration` | 精确8项、r06字节绑定、新Message-ID、owner-only、正式state不变 |
> | Gmail REST串行投递 | `m11-v3-live-delivery` | `source/tests/code/{contract,integration}` | intent先行、每封send≤1、RAW/CID闭合、成功后才领取下一封 |
> | 崩溃与重放 | `m11-v3-live-recovery` | `source/tests/code/integration` | 响应丢失只读恢复、unknown停止、重放send=0/SQLite增量0 |
>

### 原定义-L59

来源标题：工具采用情况；原件L59–L66。

> ## 工具采用情况
>
> - 可执行技术栈：Python 3.12、SQLite、官方Gmail REST、OAuth、MIME/CID。
> - Linter 配置和命令：`ruff --config skills/_shared/ruff.toml check skills tests/code`；
>   `ruff format --check skills tests/code`；`mypy --config-file skills/_shared/mypy.ini skills tests/code`。
> - 测试框架、定向命令和完整命令：`pytest tests/code -q`、只读compile、全部Schema/metadata/Markdown、
>   权限/隐私/布局、`git diff --check`。
>

### 原定义-L67

来源标题：Subagent 派发；原件L67–L73。

> ## Subagent 派发
>
> | Attempt | Agent 角色/任务 ID | 风险与复杂度 | 模型档位 | 推理档位 | 选档理由 | 平台支持 | 写入边界 | 产物与门禁 | 结果 |
> | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
> | 1 | Code Validator / M11-0015 | 高：真实外部写入前的8项状态机与崩溃恢复 | high | high | Gmail真实发送、幂等和隐私均为高风险 | available | 只读 | 完整测试/静态门、Fake REST、r06绑定、send≤1 | PASS：600全量/44 Live、r06 9472 manifest/8 MIME/37 CID、严格串行/unknown/重放、旧入口和隐私门全部通过；网络/Provider 0 |
> | 1 | Delivery/Data-Privacy Validator / M11-0015 | 高：8项远端事实、私人Candidate和正式边界 | high | high | 真实投递后必须独立验证远端证据与隐私 | available | 只读 | 8 Gmail ID/RAW、重放0、state/Token/Git边界 | PASS：8项succeeded/attempt=1，8个Gmail ID与实际Message-ID互异，32 REST/8 send、RAW/text/HTML/CID闭合，state/Token/Git与零越界调用通过 |
>

### 原定义-L74

来源标题：工作分解；原件L74–L83。

> ## 工作分解
>
> | 步骤 | 状态（`pending`、`in_progress`、`blocked`、`done`） | 证据 |
> | --- | --- | --- |
> | M11-0015-01 冻结授权、r06/OAuth/收件人/正式state基线 | done | r06 DB/build receipt SHA、owner-only收件/OAuth/Token和正式state指纹均只读核对通过；Provider调用0 |
> | M11-0015-02 实现参数化v3八封REST批次与回归 | done | 新v3 marker/固定策略/根manifest/唯一item_key/严格串行/动态N项验证；44项Live定向测试PASS |
> | M11-0015-03 完整代码门与全新Code Validator | done | 600 tests、Ruff、format、mypy、compile、65 Schema、metadata/Markdown、隐私/Git/diff全部PASS；全新high/high只读Code Validator PASS |
> | M11-0015-04 建立Live Candidate并严格串行发送8封 | done | 新Candidate `trainlab-m11-v3-live-r01.k2jDQJ`发送前8项均为prepared/0尝试；真实Gmail REST严格串行完成8项，32次API、8次send、0 unknown |
> | M11-0015-05 重放、最终边界和Delivery/Data-Privacy Validator | done | final verify PASS；重放Provider增量0、SQLite逻辑增量0、非DB产物增量0；全新high/high最终Validator PASS |
>

### 原定义-L84

来源标题：当前检查点；原件L84–L93。

> ## 当前检查点
>
> - 当前 Loop：M11 v3八封真实Gmail投递已完成。
> - 最近完成：8封真实投递、RAW/CID闭合、零调用重放与Delivery/Data-Privacy Validator PASS。
> - 当前焦点：已完成并归档。
> - 下一动作：无；部署与定时运行仍需新的明确计划和授权。
> - 阻塞项：无。
> - 已变更文件：本exec plan；Roadmap/memory/rules待同步。
> - 待验证项：无。
>

### 原定义-L94

来源标题：决策与发现；原件L94–L98。

> ## 决策与发现
>
> - 旧M11 Live入口只绑定历史两封canary，不能直接冒充v3八封授权；新批次只参数化复用底层单写者。
> - 用户批准全部8封，因此不增加人工canary停点；仍严格逐封远端闭合。
>

### 原定义-L99

来源标题：任务级独立验证；原件L99–L107。

> ## 任务级独立验证
>
> - 中性交接：仅提供冻结8项范围、A-010/A-011/A-013/A-017、当前代码与Candidate。
> - Validator 身份/上下文：`m11_v3_live_delivery_validator`，全新只读Agent。
> - 模型/推理档位：high/high。
> - 命令与观察：只读权限审计、SQLite immutable integrity/FK与证据链查询、Python 3.12正式MIME校验、Git ignore/privacy/diff检查；8/8远端链闭合，32 REST/8 send，无越界Provider。
> - 结果：`PASS`
> - 未满足项与剩余风险：无未满足项；未单独生成replay receipt，但终态marker、capture计数、SQLite逻辑与非DB产物零增量提供中等强度重放证据。
>

### 原定义-L108

来源标题：集成级独立验证；原件L108–L117。

> ## 集成级独立验证
>
> - 集成范围：严格串行，无并行集成。
> - 中性交接：不适用。
> - Validator 身份/上下文：不适用。
> - 模型/推理档位：不适用。
> - 完整 lint/test 与回归观察：由任务级Validator覆盖。
> - 结果：`不适用——无并行集成`
> - 未满足项与剩余风险：无。
>

### 原定义-L118

来源标题：PLANS 回写清单；原件L118–L124。

> ## PLANS 回写清单
>
> - [x] Exec plan 已归档到`completed/`
> - [x] Roadmap叶子任务已更新为`[x] completed`
> - [x] 子项目和阶段状态已重新计算
> - [x] `memory.md`中的活动计划指针已删除
>

### 原定义-L125

来源标题：迭代日志；原件L125–L132。

> ## 迭代日志
>
> | 日期/上下文 | 已完成事项与证据 | 发现 | 下一动作 |
> | --- | --- | --- | --- |
> | 2026-08-23 / start | 用户明确授权发送7份日报与1份周报，并允许修复实现后继续尚未发送项 | 旧Live入口只支持历史两封，不可扩大解释为v3八封 | 建立版本化薄适配器与Fake REST回归，Code PASS后才真实发送 |
> | 2026-08-23 / preflight | r06数据库与build receipt冻结SHA、私有收件配置、OAuth回执、Token权限和正式state指纹全部只读通过；无Provider调用 | r06使用根`declared_files`闭包且7个日报共享`kind=daily`，旧per-preview receipt与kind身份均不可复用 | 以唯一`action_key`和根manifest实现v3策略，旧v1/v2入口保持兼容 |
> | 2026-08-23 / code-gates | 测试先行新增v3批次Schema与6项回归；参数化同一Live Adapter，保留v1/v2。600 tests、Ruff/format/mypy/compile、65 Schema、6 Skill metadata、19 Markdown、隐私/Git/diff门PASS | 旧`validate_schema`未注册本地跨Schema引用，会尝试解析伪域名；已改为完整本地Registry，离线闭合 | 派发全新high/high只读Code Validator；PASS前不建立真实Candidate、不调用Gmail |
> | 2026-08-23 / live-complete | Code Validator PASS后建立新Candidate，严格串行完成32 REST/8 send；8项RAW/CID与远端ID闭合，零调用重放和最终Validator PASS | SQLite checkpoint可能改变容器字节但逻辑内容无增长；最终Validator确认不构成重复输出 | 归档M11-0015；部署与定时运行留待新授权 |

## 历史来源与证据

- [不可变原件快照](../evidence/ADHOC-0029/history.zip)，条目`docs/exec-plans/completed/M11-email-presentation-0001-readable-cid-r01.md`，原SHA-256：`c48168d139c828cb0755f28983c1674eaa17ebfd2faf0e1c5c29b40248db662f`。
- [来源清单](../evidence/ADHOC-0029/history-manifest.json)、[迁移/编号映射](../evidence/ADHOC-0029/migration-manifest.json)、[原问题与失败计数索引](../evidence/ADHOC-0029/failure-index.json)。原记录中的绝对路径和失效外部证据只说明当时事实，不据此复建旧路径。
- 历史快照仅用于保真审查，不作为现行规范、产品导入、Schema、AI输入或CI运行依赖。当前实际迁移验收见[ADHOC-0029](../completed/ADHOC-0029-agentsmd-upgrade.md)。
