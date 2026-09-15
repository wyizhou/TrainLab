# 执行计划：M6 活动证据一致性与真实报告预览（已被 ADHOC-0011 取代）

## 对应目标

- 功能编号：M6
- 功能状态：[exec]
- 总计划对应条目：[PLAN.md](../../PLAN.md) 的同编号/原Roadmap关联条目。
- 目标及范围和验收要求的引用：历史目标、范围、每个阶段/任务、验收要求及全部执行证据按对应原件保存；不是新的实施授权。
- 迁移说明：用户已取消/替代的历史任务；已发生的局部成果和失败保留，取消不等于完整验收通过。 当前协作规则仅以[AGENTS.md](../../AGENTS.md)为准；原合同及旧规范在快照中仅作历史来源，不继续生效为第二套流程。

## 阶段与任务

以下逐项迁移原实施分解；任务名称、已有编号、结果及明确依赖保留。原无编号步骤按原表顺序首次赋予L编号，不重编号已有步骤。HISTORY仅是原单阶段的归组，不再替代实际任务。此表描述历史工作，不是当前可执行规范/示例或外部授权；暂停条件见检查点。

| 阶段编号 | 状态 | 预期成果 | 依赖 |
| --- | --- | --- | --- |
| HISTORY | [exec] | 工作分解；保留原逐项成果/未完成边界 | 原前置要求及总计划同编号依赖；未另列的依赖不新增 |

| 任务编号 | 所属阶段 | 状态 | 输入输出及错误边界 | 依赖 | 检查方法 | 结果与证据（检查命令或人工方式、退出结果及关键证据） |
| --- | --- | --- | --- | --- | --- | --- |
| M6-0001 | HISTORY | [completed] | M6-0001 保存 M5 单一本地基线；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原Roadmap同编号依赖：M5；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：证据：commit `0687d9f`，敏感路径未跟踪；原完成范围不扩大；对应原执行计划 L57 |
| M6-0002 | HISTORY | [exec] | M6-0002 审计并统一 inventory 生命周期证据；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原Roadmap同编号依赖：M6-0001；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：证据：任务级独立 Validator PASS；最终脱敏审计含 28 observations、28 unique revisions、512 seen、absence_proven=0、parse/hash failures=0；正式库未写；仅保留已开展但未完成完整交付的原范围；暂停/取消不恢复；对应原执行计划 L58 |
| M6-0003 | HISTORY | [exec] | M6-0003 candidate 离线修复与完整性验证；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原Roadmap同编号依赖：M6-0002；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：证据：任务级独立 Validator PASS；`/private/tmp/trainlab-m6-audit/candidate-r01-activity-lifecycle.json` SHA `9064a82adaefdf66986d20a8180338745452f096da95d553bb9ed18eb0e91c7b`；candidate quick_check/FK/raw 闭包通过；7 条 seen evidence 重激活，21 条保持 unresolved；仅保留已开展但未完成完整交付的原范围；暂停/取消不恢复；对应原执行计划 L59 |
| M6-0004 | HISTORY | [exec] | M6-0004 真实周报、日报和 HTML/JSON 预览；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原Roadmap同编号依赖：M6-0003；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：证据：先在同一任务内修复离线课程合同与容量闭门；真实 weekly→daily→preview 仍未运行；仅保留已开展但未完成完整交付的原范围；暂停/取消不恢复；对应原执行计划 L60 |

## 当前检查点

- 工作目录与分支：项目根；本次格式迁移在work/adhoc-0029-agentsmd-upgrade，原执行目录/分支仅见历史证据。
- 验收要求与受验版本及未提交改动：本轮迁移基准ec36ce7bbdf9d70a509238dd771b155eb6f84261；原受验版本/未提交内容/合同全文保留于快照。不得把迁移HEAD当作原产品受验版本。
- 最近完成：仅迁移当前记录结构与路径；用户已取消/替代的历史任务；已发生的局部成果和失败保留，取消不等于完整验收通过。
- 下一动作：保留历史定位，不恢复原业务或重判历史结果。
- 暂停原因：已取消，不纳入当前待办；只有用户另行改变目标并授权才可重新规划。
- 恢复条件：已完成范围不需重做；已取消/暂停部分不在当前待办，恢复前须用户另行明确目标/授权并核对原失败次数。
- PR 与交付情况：本轮只迁移记录，不提交/推送/PR。原Git交付事实及未知项保留于原件，不推断后续远端状态。

## 问题记录

原有明确问题编号保留；无编号记录首次按不可变源行号分配ISSUE-L编号。每行是原记录索引，可能含规范、观察、裁决或后续动作；重复引用不重新累计事件，也不把原未量化的计数清零。

| 稳定问题编号 | 对应要求与实际问题 | 已尝试修法 | 累计失败次数 | 证据及处理结果 |
| --- | --- | --- | --- | --- |
| ISSUE-L106 | 原要求/观察/裁决逐条记录；见本行源原文，不将规则或下一动作当发生事实 | 原行未单列修法则不推断；全部尝试/动作保留于右列及原上下文 | 原行未给统一累计值；保留原次数表述，不置0或按索引条数计次数 | &#124; 2026-08-14 / validator-r01 &#124; 独立 Validator `FAIL` &#124; 指出审计缺逐 revision 观察、离线工具规则漂移、Safety 降级可能携带原始硬课剂量；均已在当前快照修订并补回归 &#124; 完成最终门禁并交给新 Validator &#124;；原件L106 |
| ISSUE-L107 | 原要求/观察/裁决逐条记录；见本行源原文，不将规则或下一动作当发生事实 | 原行未单列修法则不推断；全部尝试/动作保留于右列及原上下文 | 原行未给统一累计值；保留原次数表述，不置0或按索引条数计次数 | &#124; 2026-08-14 / final-gates &#124; 当前快照完整 pytest 唯一终态 exit `0`，日志 `/private/tmp/trainlab-m6-final-Dk2i5h/pytest.log` SHA `1b1002ffe35c3bed0e8da301d2b3ffc3ddb18700d95c195e4991cc0c1eb9d93b`；exit 标记 SHA `9a271f2a916b0b6ee6cecb2426f0b3206ef074578be55d9bc94f6f3fe3ab86aa`；2573 dots、无 FAILED/ERROR &#124; 真实 weekly→daily→preview 仍因 safety rejection 未产生 delivery &#124; 等待最终独立 Validator &#124;；原件L107 |
| ISSUE-L109 | 原要求/观察/裁决逐条记录；见本行源原文，不将规则或下一动作当发生事实 | 原行未单列修法则不推断；全部尝试/动作保留于右列及原上下文 | 原行未给统一累计值；保留原次数表述，不置0或按索引条数计次数 | &#124; 2026-08-14 / validator-r02 &#124; 独立 Validator `PASS`（仅 M6-0002/0003 与 M6-0004 失败关闭）；最终 pytest `/private/tmp/trainlab-m6-final-Dk2i5h/pytest.log` SHA `1b1002ffe35c3bed0e8da301d2b3ffc3ddb18700d95c195e4991cc0c1eb9d93b`，exit `0`；mypy 105 files/0、Ruff/format/schema/quality/layout/compile/shell/diff 全绿 &#124; 21 条活动仍无离线缺席证明；无 weekly delivery/artifact，真实 daily/preview 未运行 &#124; M6 保持 blocked；需要当前 Provider 状态时另立 M7 &#124;；原件L109 |

## 历史目标与原编号索引

下文仅引用当时目标，不是现行规范或可运行示例；已经被新方案替代的业务不复活。原阶段/任务已在上表逐项迁移；原早期状态与最终范围不同的映射依据逐项标明，不借迁移扩大历史完成范围。

> 在不调用 Garmin/Gmail、不修改正式 `source/state` 的前提下，修复活动 inventory
> 生命周期证据规则，并在仓库外 candidate 中成功生成 2026-08-09 周报、2026-08-12
> 日报和只读 HTML/JSON 预览。若离线证据不足，必须保持 fail-closed 并记录缺口。

原阶段/任务及其结果见上表，原问题及计数见问题记录；额外来源标识仍可在迁移清单中检索，原件供逐行核对。

## 原任务定义与验收

本节承接原任务定义的全部内容，而非仅保留状态摘要或指向压缩包。上表每个原任务的输入输出/错误边界及检查方法均关联本节；原文有同编号专属标题时另外关联该精确段落，公共目标/范围/合同与其他定义完整保留在本节。不得把原表中的“已接入/PASS”当作完整定义。

**适用性：全部引文均属于该历史任务的原目标、合同修订和执行记录，不是当前开发协议、可运行示例或新的业务授权。** 多版本材料按原任务编号、版本和日期定位，不把后续规则回套早期结果。旧流程/命令/目录和“当前”措辞只描述原记录时点；根AGENTS是唯一现行协作规则，暂停/取消按本文件的新检查点处理，不恢复旧产品。

为保留可核查语义，原件按标题和源行完整投射为引用块；只增加引用前缀，并将旧Markdown导航链接显示为“原定位”文字，未更改原件。原字节/原哈希由history.zip及history-manifest.json证明，不把显示投射声称为原字节。全部源行连续覆盖，原始执行/协调记录也标为历史数据，不混入当前阶段状态。

### 原定义-L1

来源标题：原文导言；原件L1–L11。

> # 执行计划：M6 活动证据一致性与真实报告预览（已被 ADHOC-0011 取代）
>
> - 状态：`cancelled`
> - 负责人：主协调 Agent
> - Roadmap ID：`M6`
> - 阶段/子项目：`M6/活动证据一致性与真实报告预览`
> - Batch ID：`serial-m6`
> - 返工来源：`无`
> - 开始日期：2026-08-14
> - 最后更新：2026-08-15
>

### 原定义-L12

来源标题：目标与验收标准；原件L12–L17。

> ## 目标与验收标准
>
> 在不调用 Garmin/Gmail、不修改正式 `source/state` 的前提下，修复活动 inventory
> 生命周期证据规则，并在仓库外 candidate 中成功生成 2026-08-09 周报、2026-08-12
> 日报和只读 HTML/JSON 预览。若离线证据不足，必须保持 fail-closed 并记录缺口。
>

### 原定义-L18

来源标题：范围与非目标；原件L18–L23。

> ## 范围与非目标
>
> - 范围：M5 本地基线、Garmin inventory 生命周期决策、离线 candidate 修复、真实报告预览。
> - 非目标：Provider 补数、Garmin/Gmail 调用、正式库写入、邮件发送、远端 Git、正式状态切换。
> - M5 已验证改动先保存为本地提交 `0687d9f`：`feat: add adaptive coaching and local report previews`。
>

### 原定义-L24

来源标题：适用规则与参考资料；原件L24–L29。

> ## 适用规则与参考资料
>
> - A-001：任何在线 Garmin 操作必须另立计划并明确窗口、资源和预算。
> - A-004/A-007：私有数据不入 Git；source 为唯一产品工程；禁止旧编排控制面。
> - 产品 Harness：`source/src/resources/harness/shared/HARNESS.md`、`source/src/resources/harness/analysis/HARNESS.md`。
>

### 原定义-L30

来源标题：依赖与隔离；原件L30–L38。

> ## 依赖与隔离
>
> - 显式依赖：M5 `0687d9f` 本地基线；现有 Foundation v4 candidate/source 数据。
> - 任务顺序：M6-0001 → M6-0002 → M6-0003 → M6-0004，严格串行。
> - 分支/worktree：沿用本地 `main`，不创建并行 worktree。
> - 允许写入：本计划、`PLANS.md`、`memory.md`、source 生产代码/测试和脱敏 schema。
> - 禁止写入：`source/state`、私有 config/logs、`data-backup` 内容、远端、Gmail、Garmin。
> - candidate、审计 JSON、报告预览均位于仓库外 `0700` 临时目录。
>

### 原定义-L39

来源标题：功能与测试映射；原件L39–L46。

> ## 功能与测试映射
>
> | 功能 | Feature slug | 测试目录 | 必须满足的行为 |
> | --- | --- | --- | --- |
> | 生命周期决策 | `activity-lifecycle` | `source/tests/activity-lifecycle/` | 有界 inventory 不得伪装 full；出现/首次缺席/二次缺席/重现及重放规则正确 |
> | 离线 candidate 修复 | `offline-repair` | `source/tests/offline-repair/` | raw/revision 闭包、SQLite 完整性、权限、正式库摘要不变 |
> | 真实报告预览 | `real-report-preview` | `source/tests/real-report-preview/` | weekly→daily→preview、课程绑定、0600、无 delivery/provider 副作用 |
>

### 原定义-L47

来源标题：工具采用情况；原件L47–L52。

> ## 工具采用情况
>
> - Python 3.12、SQLite、现有 source runtime Harness。
> - 维护命令：`pytest`、`mypy src`、Ruff check/format、compile、schema、repository quality、source-layout、diff/privacy。
> - 外部调用：禁止；任何 Garmin/Gmail transport 计数必须为零。
>

### 原定义-L53

来源标题：工作分解；原件L53–L61。

> ## 工作分解
>
> | 步骤 | 状态 | 证据 |
> | --- | --- | --- |
> | M6-0001 保存 M5 单一本地基线 | `done` | commit `0687d9f`，敏感路径未跟踪 |
> | M6-0002 审计并统一 inventory 生命周期证据 | `validated` | 任务级独立 Validator PASS；最终脱敏审计含 28 observations、28 unique revisions、512 seen、absence_proven=0、parse/hash failures=0；正式库未写 |
> | M6-0003 candidate 离线修复与完整性验证 | `validated` | 任务级独立 Validator PASS；`/private/tmp/trainlab-m6-audit/candidate-r01-activity-lifecycle.json` SHA `9064a82adaefdf66986d20a8180338745452f096da95d553bb9ed18eb0e91c7b`；candidate quick_check/FK/raw 闭包通过；7 条 seen evidence 重激活，21 条保持 unresolved |
> | M6-0004 真实周报、日报和 HTML/JSON 预览 | `active` | 先在同一任务内修复离线课程合同与容量闭门；真实 weekly→daily→preview 仍未运行 |
>

### 原定义-L62

来源标题：当前检查点；原件L62–L71。

> ## 当前检查点
>
> - 当前 Loop：M6-0002/0003 已 `validated`；M6-0004 按用户决定继续暂停，先完成 ADHOC-0011 state raw 保留决策与数据调整。
> - 最近完成：M5 已提交；生命周期决策、collector 接入、离线审计/修复工具和安全边界适配已完成。
> - 当前焦点：冻结当前实现，不继续优化或生成报告；只讨论和规划 `source/state/` 数据保留策略。
> - 下一动作：等待用户完成 ADHOC-0011 数据决策；未经新指令不恢复 M6。
> - 阻塞项：此前 weekly 候选因模型处方与 deterministic safety request 字段不一致而被拒绝；当前已加入按运动类型的严格处方 schema、climbing rationale 模板和分支诊断，但真实 weekly delivery 尚未重跑。21 条历史 lifecycle unresolved 仍阻塞可信容量，必须先完成 M7。
> - 已变更文件：本计划、`PLANS.md`、`memory.md`、生命周期/离线修复/安全边界代码与测试。
> - 待验证项：M6-0004 只有在 candidate 产生有效 weekly delivery 后，才可继续 daily→preview；当前不得伪造报告或归档 M6。
>

### 原定义-L72

来源标题：决策与发现；原件L72–L77。

> ## 决策与发现
>
> - 目标周的活动状态为 `suspected_missing`，但同日期已有 `fetched` inventory coverage；不能直接批量恢复。
> - 8/12 `full:through:2026-08-12` 与 `repair:2026-08-10:2026-08-12` 共享 raw，说明 full 结果可能实际有界；需以 inventory 成员和窗口证据核定。
> - raw 对象按 SHA 去重时，`raw_objects.resource_kind` 与 revision kind 不同可能是合法别名；必须验证字节 SHA、revision kind、parser 和窗口，不得仅凭标签判坏。
>

### 原定义-L78

来源标题：任务级独立验证；原件L78–L85。

> ## 任务级独立验证
>
> - 中性交接：仅提供当前候选、脱敏审计、测试命令和计划验收标准。
> - Validator：全新、只读、高风险档位；不得参与实现。
> - 结果：`PASS`（范围：M6-0002/0003；M6-0004 的失败关闭行为）
> - 证据：正式数据库 SHA `0b380b596022af17a1f87a000780be0864ea84c7ac57c0fa9053a1fef0acdb57` 未变；candidate-r01 Foundation/schema/raw/FK/权限闭包通过；审计 SHA `9064a82adaefdf66986d20a8180338745452f096da95d553bb9ed18eb0e91c7b`；无 Provider/Garmin/Gmail 调用。
> - 限制：weekly 候选均被确定性 safety request schema 拒绝，deliveries/artifacts 均为 0，因此真实 daily 和 preview 未运行；M6-0004 仍 blocked。
>

### 原定义-L86

来源标题：集成级独立验证；原件L86–L91。

> ## 集成级独立验证
>
> - 集成范围：M6-0002 至 M6-0004 串行结果。
> - 结果：`PASS`（M6-0002/0003 与 M6-0004 失败关闭）；M6 整体仍 `blocked`，不归档。
> - 限制：candidate 没有有效 weekly delivery/artifact，真实 daily→preview 证据不存在。
>

### 原定义-L92

来源标题：PLANS 回写清单；原件L92–L98。

> ## PLANS 回写清单
>
> - [ ] Exec plan 已归档到 `completed/`
> - [ ] Roadmap 叶子任务已更新为 `[x] completed`
> - [ ] 子项目和阶段状态已重新计算
> - [ ] `memory.md` 中的活动计划指针已删除
>

### 原定义-L99

来源标题：迭代日志；原件L99–L114。

> ## 迭代日志
>
> | 日期/上下文 | 已完成事项与证据 | 发现 | 下一动作 |
> | --- | --- | --- | --- |
> | 2026-08-14 / start | M5 已保存为 `0687d9f`，Git 未跟踪私有 state/config/logs/data-backup | 目标活动均 suspected_missing，但 coverage 存在 fetched 记录 | 建立 lifecycle 审计与 fail-closed 决策模块 |
> | 2026-08-14 / lifecycle | 新增 `source/src/garmin/lifecycle.py`、collector 证据门、`reconcile_activity_lifecycle.py`、schema 与回归测试；聚焦测试通过 | formal audit window `2026-07-13..2026-08-09` 无 absence proof；7 条 seen evidence 可重激活，21 条 unresolved；审计 JSON 现在含逐 revision 脱敏观察 | 在 candidate 应用离线修复并核验 raw/revision/SQLite 闭包 |
> | 2026-08-14 / candidate | `/private/tmp/trainlab-m6-candidate-r01` owner-only；Foundation verify ready、quick_check ok、FK 0、raw 27388 与 formal 一致；formal DB SHA `0b380b596022af17a1f87a000780be0864ea84c7ac57c0fa9053a1fef0acdb57` 未变；candidate audit SHA `9064a82adaefdf66986d20a8180338745452f096da95d553bb9ed18eb0e91c7b` | candidate weekly 3 次 rejected、0 delivery、0 artifact、无 interrupted started run；无外部调用 | 保持 M6-0004 blocked，不运行无前置 delivery 的 daily/preview |
> | 2026-08-14 / validator-r01 | 独立 Validator `FAIL` | 指出审计缺逐 revision 观察、离线工具规则漂移、Safety 降级可能携带原始硬课剂量；均已在当前快照修订并补回归 | 完成最终门禁并交给新 Validator |
> | 2026-08-14 / final-gates | 当前快照完整 pytest 唯一终态 exit `0`，日志 `/private/tmp/trainlab-m6-final-Dk2i5h/pytest.log` SHA `1b1002ffe35c3bed0e8da301d2b3ffc3ddb18700d95c195e4991cc0c1eb9d93b`；exit 标记 SHA `9a271f2a916b0b6ee6cecb2426f0b3206ef074578be55d9bc94f6f3fe3ab86aa`；2573 dots、无 FAILED/ERROR | 真实 weekly→daily→preview 仍因 safety rejection 未产生 delivery | 等待最终独立 Validator |
> | 2026-08-14 / gates | 唯一完整 pytest exit `0`，最终证据见 `/private/tmp/trainlab-m6-final-Dk2i5h/pytest.log`；mypy/Ruff/format/schema/quality/layout/compile/diff 全绿 | 真实报告产物仍不可证明，需独立 Validator 判定 | 交接独立只读 Validator |
> | 2026-08-14 / validator-r02 | 独立 Validator `PASS`（仅 M6-0002/0003 与 M6-0004 失败关闭）；最终 pytest `/private/tmp/trainlab-m6-final-Dk2i5h/pytest.log` SHA `1b1002ffe35c3bed0e8da301d2b3ffc3ddb18700d95c195e4991cc0c1eb9d93b`，exit `0`；mypy 105 files/0、Ruff/format/schema/quality/layout/compile/shell/diff 全绿 | 21 条活动仍无离线缺席证明；无 weekly delivery/artifact，真实 daily/preview 未运行 | M6 保持 blocked；需要当前 Provider 状态时另立 M7 |
> | 2026-08-14 / offline-contract-repair | 在同一 M6-0004 内完成离线返修：running/climbing/rest 处方按运动类型严格约束；climbing 模板补受控 rationale；oneOf 分支错误保留 required/pattern/type 且不泄露模型原文；四周窗口含 lifecycle unresolved 时容量返回 `activity_lifecycle_unresolved`；新增混合周和诊断回归 | 真实 weekly→daily→preview 仍未运行；不调用 Provider | 完成静态门后仅运行一次完整 pytest，再交给全新只读 Validator；若门禁通过，M6 回到 blocked 等待 M7 批准 |
> | 2026-08-14 / offline-gates | 离线聚焦分析/生命周期/容量/修复回归全部通过；Ruff、format、`mypy src`（105 files/0）、Schema=32、quality、layout、compile、diff 全绿；唯一完整 pytest 日志 `/private/tmp/trainlab-m6-offline-full-r01.E1kZxo/pytest.log` 到 100%，2578 个通过点、无 `F`/`E` | zsh 包装脚本使用保留变量名导致退出标记未写入，宿主 exit code 未捕获；未重跑完整 pytest | 以“内容完成、退出码未捕获”交由独立 Validator 判定；不调用 Garmin/Gmail，不生成真实报告 |
> | 2026-08-14 / paused-for-audit | 用户决定先检查 source 开发状态、文件数据和数据库来源；已中止进行中的离线合同 Validator | 是否继续 M6 或进入 M7 取决于 ADHOC-0009 来源审计 | 保持代码和正式数据原状，完成只读审计 |
> | 2026-08-15 / state-decision | ADHOC-0009/0010 已解释数据库来源和 raw 目录；建立 ADHOC-0011 记录 state-only 数据调整与后续开发需求 | backup 有登记证据；gmail/legacy 是现行目录合同；仅 `.DS_Store` 可无合同变更清理 | 保持 M6 blocked，等待用户确认精确数据动作 |
> | 2026-08-15 / provider-layout-plan | 用户确认 future active raw 删除 backup/gmail/legacy 命名空间并保留 Garmin Provider 层；ADHOC-0011 已细化为可开发规格 | 44 份 backup-only 文件实际属于 Garmin，规划无损归入 Garmin；入站 Mail 路径需退役才能防止 gmail 重建 | 继续保持 M6 blocked；只完善规划，不执行 |

## 历史来源与证据

- [不可变原件快照](../evidence/ADHOC-0029/history.zip)，条目`docs/exec-plans/completed/M6-activity-evidence-0001-lifecycle-and-preview.md`，原SHA-256：`8ec0afea11dee21fb50d0865ead1fbe46e1f9ee61598008b9484c590546d393d`。
- [来源清单](../evidence/ADHOC-0029/history-manifest.json)、[迁移/编号映射](../evidence/ADHOC-0029/migration-manifest.json)、[原问题与失败计数索引](../evidence/ADHOC-0029/failure-index.json)。原记录中的绝对路径和失效外部证据只说明当时事实，不据此复建旧路径。
- 历史快照仅用于保真审查，不作为现行规范、产品导入、Schema、AI输入或CI运行依赖。当前实际迁移验收见[ADHOC-0029](../completed/ADHOC-0029-agentsmd-upgrade.md)。
