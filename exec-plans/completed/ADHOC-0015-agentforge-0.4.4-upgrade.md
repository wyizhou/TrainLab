# 执行计划：升级 agentForge v0.4.4 并迁移 M11 诊断状态

## 对应目标

- 功能编号：ADHOC-0015
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
| L01 | HISTORY | [completed] | 固定上游与保护当前工作区；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原表未单列；沿用原功能前置条件，不按编号新增依赖；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：证据：v0.4.4 Tag/Commit 双重核对；115 项快照和恢复演练通过；原完成范围不扩大；对应原执行计划 L128 |
| L02 | HISTORY | [completed] | 三方适配六个上游核心文件；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原表未单列；沿用原功能前置条件，不按编号新增依赖；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：证据：六项均为 adapted；TrainLab 项目边界保留；原完成范围不扩大；对应原执行计划 L129 |
| L03 | HISTORY | [completed] | 新增 A-019、许可和稳定版本事实；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原表未单列；沿用原功能前置条件，不按编号新增依赖；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：证据：A-019 仅替代 A-003 当前版本事实；MIT 全文恢复；原完成范围不扩大；对应原执行计划 L130 |
| L04 | HISTORY | [completed] | 迁移 M11 为 DIAGNOSIS_PENDING；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原表未单列；沿用原功能前置条件，不按编号新增依赖；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：证据：legacy VC-001、blocked/pending；未运行 Failure Analyst、未改产品；原完成范围不扩大；对应原执行计划 L131 |
| L05 | HISTORY | [completed] | 完整静态与 source 回归；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原表未单列；沿用原功能前置条件，不按编号新增依赖；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：证据：664 tests；Ruff/format/mypy；97 AST；Schema/metadata/privacy；静态门和正式 state 指纹全部PASS；原完成范围不扩大；对应原执行计划 L132 |
| L06 | HISTORY | [completed] | 全新 Validator 与归档；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原表未单列；沿用原功能前置条件，不按编号新增依赖；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：证据：全新只读 high/high Validator 固定结构 PASS；原完成范围不扩大；对应原执行计划 L133 |

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
| ISSUE-L48 | 原要求/观察/裁决逐条记录；见本行源原文，不将规则或下一动作当发生事实 | 原行未单列修法则不推断；全部尝试/动作保留于右列及原上下文 | 原行未给统一累计值；保留原次数表述，不置0或按索引条数计次数 | &#124; `AC-002` &#124; 根治理完整采用冻结合同、固定 Validator 输出、FAIL/INCONCLUSIVE 边界、失败诊断门和五类 Failure Analyst 归因。 &#124;；原件L48 |
| ISSUE-L59 | 原要求/观察/裁决逐条记录；见本行源原文，不将规则或下一动作当发生事实 | 原行未单列修法则不推断；全部尝试/动作保留于右列及原上下文 | 原行未给统一累计值；保留原次数表述，不置0或按索引条数计次数 | &#124; `INV-002` &#124; 未绑定冻结标准的 blocker 必须为 INCONCLUSIVE；TM/EX 外发现只能 advisory/scope candidate。 &#124;；原件L59 |
| ISSUE-L69 | 原要求/观察/裁决逐条记录；见本行源原文，不将规则或下一动作当发生事实 | 原行未单列修法则不推断；全部尝试/动作保留于右列及原上下文 | 原行未给统一累计值；保留原次数表述，不置0或按索引条数计次数 | &#124; `TM-003` &#124; Validator 可能新增未冻结要求、读取历史 verdict 或把 INCONCLUSIVE 当成实现 FAIL。 &#124;；原件L69 |
| ISSUE-L184 | 原要求/观察/裁决逐条记录；见本行源原文，不将规则或下一动作当发生事实 | 原行未单列修法则不推断；全部尝试/动作保留于右列及原上下文 | 原行未给统一累计值；保留原次数表述，不置0或按索引条数计次数 | `blocking_findings`、`advisories`、`scope_change_candidates`、`unknowns` 和；原件L184 |
| ISSUE-L185 | 原要求/观察/裁决逐条记录；见本行源原文，不将规则或下一动作当发生事实 | 原行未单列修法则不推断；全部尝试/动作保留于右列及原上下文 | 原行未给统一累计值；保留原次数表述，不置0或按索引条数计次数 | `commands_and_evidence`。未绑定冻结标准的 blocker 使报告为 `INCONCLUSIVE`。；原件L185 |
| ISSUE-L193 | 原要求/观察/裁决逐条记录；见本行源原文，不将规则或下一动作当发生事实 | 原行未单列修法则不推断；全部尝试/动作保留于右列及原上下文 | 原行未给统一累计值；保留原次数表述，不置0或按索引条数计次数 | - `blocking_findings`：`[]`；原件L193 |

## 历史目标与原编号索引

下文仅引用当时目标，不是现行规范或可运行示例；已经被新方案替代的业务不复活。原阶段/任务已在上表逐项迁移；原早期状态与最终范围不同的映射依据逐项标明，不借迁移扩大历史完成范围。

> 将 TrainLab 根开发 Harness 从 agentForge `v0.4.2` 三方适配到正式 `v0.4.4`，引入冻结
> 验证合同、固定 Validator 输出、失败诊断门和 Failure Analyst，同时完整保留 TrainLab 的
> `source/` 产品边界、既有 A-001～A-018、当前 M11 工作和私人数据边界。当前 M11 只迁移为
> `DIAGNOSIS_PENDING`，不在本任务实施诊断或产品修复。

原阶段/任务及其结果见上表，原问题及计数见问题记录；额外来源标识仍可在迁移清单中检索，原件供逐行核对。

## 原任务定义与验收

本节承接原任务定义的全部内容，而非仅保留状态摘要或指向压缩包。上表每个原任务的输入输出/错误边界及检查方法均关联本节；原文有同编号专属标题时另外关联该精确段落，公共目标/范围/合同与其他定义完整保留在本节。不得把原表中的“已接入/PASS”当作完整定义。

**适用性：全部引文均属于该历史任务的原目标、合同修订和执行记录，不是当前开发协议、可运行示例或新的业务授权。** 多版本材料按原任务编号、版本和日期定位，不把后续规则回套早期结果。旧流程/命令/目录和“当前”措辞只描述原记录时点；根AGENTS是唯一现行协作规则，暂停/取消按本文件的新检查点处理，不恢复旧产品。

为保留可核查语义，原件按标题和源行完整投射为引用块；只增加引用前缀，并将旧Markdown导航链接显示为“原定位”文字，未更改原件。原字节/原哈希由history.zip及history-manifest.json证明，不把显示投射声称为原字节。全部源行连续覆盖，原始执行/协调记录也标为历史数据，不混入当前阶段状态。

### 原定义-L1

来源标题：原文导言；原件L1–L11。

> # 执行计划：升级 agentForge v0.4.4 并迁移 M11 诊断状态
>
> - 状态：`completed`
> - 负责人：主协调 Agent
> - Roadmap ID：`ADHOC-0015`
> - 阶段/子项目：`不适用`
> - Batch ID：`serial-agentforge-v044`
> - 返工来源：`docs/exec-plans/completed/ADHOC-0001-agentforge-0.4.2-upgrade.md`
> - 开始日期：2026-08-24
> - 最后更新：2026-08-24
>

### 原定义-L12

来源标题：目标与验收标准；原件L12–L18。

> ## 目标与验收标准
>
> 将 TrainLab 根开发 Harness 从 agentForge `v0.4.2` 三方适配到正式 `v0.4.4`，引入冻结
> 验证合同、固定 Validator 输出、失败诊断门和 Failure Analyst，同时完整保留 TrainLab 的
> `source/` 产品边界、既有 A-001～A-018、当前 M11 工作和私人数据边界。当前 M11 只迁移为
> `DIAGNOSIS_PENDING`，不在本任务实施诊断或产品修复。
>

### 原定义-L19

来源标题：范围与非目标；原件L19–L26。

> ## 范围与非目标
>
> - 允许写入：根 Harness 治理文档、exec-plan 说明/模板、第三方声明、本计划和当前 M11 active plan。
> - 禁止写入：`source/` 全部产品代码/测试/配置/state/凭据、M11 实现、Git index/commit/branch/
>   worktree/remote，以及 agentForge 上游 completed plans、示例 memory 和占位项目树。
> - 不运行 Failure Analyst，不建立 M11 Candidate，不调用 Codex、Garmin、Gmail、Workout、Sites
>   或 cron。
>

### 原定义-L27

来源标题：适用规则与参考资料；原件L27–L34。

> ## 适用规则与参考资料
>
> - 已批准规则：A-001～A-018；本任务经用户批准新增 A-019，只替代 A-003 的当前版本固定事实。
> - 上游来源：agentForge `v0.4.4`，Tag 对象
>   `34f548d4fbf31d7850388b40997edaa4eb33ebad`，Commit
>   `00e03cfb6e25e35967e414bea9233dc7b33929d5`。
> - 按需读取的 references：无。
>

### 原定义-L35

来源标题：冻结验证合同；原件L35–L42。

> ## 冻结验证合同
>
> - 合同版本：`VC-001`
> - 合同状态：`frozen`
> - 冻结依据：用户于 2026-08-24 明确批准《ADHOC-0015：agentForge v0.4.4 Harness
>   升级与 M11 诊断迁移》并要求实施。
> - 冻结时点：2026-08-24，早于任何仓库内 Harness 修改。
>

### 原定义-L43

来源标题：验收标准；原件L43–L53。

> ### 验收标准
>
> | ID | 必须满足的结果 |
> | --- | --- |
> | `AC-001` | 当前 Harness 精确绑定 v0.4.4 Tag/Commit，六个上游变更文件的每项差异均有 adopted/adapted/not_applicable 结论。 |
> | `AC-002` | 根治理完整采用冻结合同、固定 Validator 输出、FAIL/INCONCLUSIVE 边界、失败诊断门和五类 Failure Analyst 归因。 |
> | `AC-003` | TrainLab 的 source 产品边界、A-001～A-018、Skills/隐私/Git/零外部动作规则不被覆盖或弱化。 |
> | `AC-004` | 当前 M11 active plan 以透明 legacy transition 冻结面向未来工作的 VC-001，并保持 blocked/DIAGNOSIS_PENDING/pending。 |
> | `AC-005` | 完整 MIT 文本、上游版本和“不重新许可 TrainLab 产品”范围声明闭合。 |
> | `AC-006` | 全部 Harness 静态门、source 完整回归、正式 state 前后指纹和独立 Validator 均通过。 |
>

### 原定义-L54

来源标题：行为不变量；原件L54–L62。

> ### 行为不变量
>
> | ID | 必须始终成立的行为 |
> | --- | --- |
> | `INV-001` | 本任务不修改 source、正式 state、私人配置或任何 M11 实现。 |
> | `INV-002` | 未绑定冻结标准的 blocker 必须为 INCONCLUSIVE；TM/EX 外发现只能 advisory/scope candidate。 |
> | `INV-003` | Validator 只接收冻结合同、适用规则和当前结果；只有 Failure Analyst 可以读取失败历史。 |
> | `INV-004` | 不复制上游历史计划、示例项目事实或静态 src/tests 占位，不提交、不推送。 |
>

### 原定义-L63

来源标题：威胁模型；原件L63–L71。

> ### 威胁模型
>
> | ID | 范围内风险 |
> | --- | --- |
> | `TM-001` | 当前 115 个未提交文件可能在三方适配中被覆盖、遗漏或错误纳入。 |
> | `TM-002` | 机械覆盖上游模板可能删除 TrainLab 项目级 source、隐私、测试和外部动作边界。 |
> | `TM-003` | Validator 可能新增未冻结要求、读取历史 verdict 或把 INCONCLUSIVE 当成实现 FAIL。 |
> | `TM-004` | 当前 M11 历史先于 v0.4.4，迁移时可能被错误描述为事前已冻结合同。 |
>

### 原定义-L72

来源标题：明确排除项；原件L72–L79。

> ### 明确排除项
>
> | ID | 不属于当前交付的场景 |
> | --- | --- |
> | `EX-001` | M11 Failure Analyst、r10 修复、真实 Candidate、模型调用或邮件。 |
> | `EX-002` | agentForge 发布、上游仓库修改、TrainLab commit/push/branch/worktree。 |
> | `EX-003` | source 运行 Harness、业务 Schema、产品测试或私人数据迁移。 |
>

### 原定义-L80

来源标题：Lint/Test 与静态门禁；原件L80–L91。

> ### Lint/Test 与静态门禁
>
> | ID | 命令或检查 | 预期结果 |
> | --- | --- | --- |
> | `GATE-001` | v0.4.4 Tag/Commit、上游 clean checkout、六文件差异映射 | 精确匹配且无遗漏 |
> | `GATE-002` | 仓库外快照、SHA 清单和恢复演练 | 115 项闭合、owner-only、restore_verified=true |
> | `GATE-003` | Markdown 链接、Mermaid 围栏、术语/版本/许可证一致性 | 全部通过 |
> | `GATE-004` | `pytest tests/code`、Ruff、format、mypy、只读 AST/JSON/metadata/隐私 | 全部通过 |
> | `GATE-005` | Git 范围、ignore、权限、`git diff --check` | 无 source 新改动、无私人内容、无空白错误 |
> | `GATE-006` | 正式 state before/after 指纹 | 完全一致 |
> | `GATE-007` | 全新只读 high/high Validator | 固定结构 `PASS` |
>

### 原定义-L92

来源标题：合同修订记录；原件L92–L97。

> ### 合同修订记录
>
> | 版本 | 状态 | 变更、理由与受影响标准 | 人工批准依据 |
> | --- | --- | --- | --- |
> | `VC-001` | `frozen` | 初始升级与 M11 诊断迁移合同 | 用户于 2026-08-24 明确批准并要求实施 |
>

### 原定义-L98

来源标题：依赖与隔离；原件L98–L107。

> ## 依赖与隔离
>
> - 显式依赖：Git 可用；TrainLab HEAD `b172f95b9c6d1c01b71f3c00e447facffa55540b`；
>   agentForge 本机 clean checkout 与 GitHub 均解析到固定 v0.4.4。
> - 保护快照：`/private/tmp/trainlab-agentforge-v044-preupdate.neh11qs8`，115 项、恢复演练
>   通过；正式 state before SHA
>   `7cc9f67d5e31c4aa16d5fa2eaacdf3b20b7f2f5515a093d9623db32f35030f43`。
> - 任务分支/Worktree/集成分支：不适用——用户明确禁止。
> - 允许写入范围：见“范围与非目标”；所有修改严格串行。
>

### 原定义-L108

来源标题：功能与测试映射；原件L108–L111。

> ## 功能与测试映射
>
> `不适用——纯治理 Harness 升级，不引入产品功能行为。`
>

### 原定义-L112

来源标题：工具采用情况；原件L112–L117。

> ## 工具采用情况
>
> - 可执行技术栈：Markdown/JSON 治理文档；现有 Python source 回归门。
> - Linter/测试：source 既有 pytest、Ruff、format、mypy、AST/Schema/metadata/隐私门；
>   根 Markdown/链接/Mermaid/术语/许可/Git 范围静态检查。
>

### 原定义-L118

来源标题：Subagent 派发；原件L118–L123。

> ## Subagent 派发
>
> | Attempt | Agent 角色/任务 ID | 合同版本 | 风险与复杂度 | 模型档位 | 推理档位 | 写入边界 | 产物与门禁 | 结果 |
> | --- | --- | --- | --- | --- | --- | --- | --- | --- |
> | 1 | Validator / ADHOC-0015 | VC-001 | 高：跨治理适配与当前脏工作区保护 | high | high | 只读 | 固定输出、全部 AC/INV/TM/EX/GATE | PASS |
>

### 原定义-L124

来源标题：工作分解；原件L124–L134。

> ## 工作分解
>
> | 步骤 | 状态 | 证据 |
> | --- | --- | --- |
> | 固定上游与保护当前工作区 | `done` | v0.4.4 Tag/Commit 双重核对；115 项快照和恢复演练通过 |
> | 三方适配六个上游核心文件 | `done` | 六项均为 adapted；TrainLab 项目边界保留 |
> | 新增 A-019、许可和稳定版本事实 | `done` | A-019 仅替代 A-003 当前版本事实；MIT 全文恢复 |
> | 迁移 M11 为 DIAGNOSIS_PENDING | `done` | legacy VC-001、blocked/pending；未运行 Failure Analyst、未改产品 |
> | 完整静态与 source 回归 | `done` | 664 tests；Ruff/format/mypy；97 AST；Schema/metadata/privacy；静态门和正式 state 指纹全部PASS |
> | 全新 Validator 与归档 | `done` | 全新只读 high/high Validator 固定结构 PASS |
>

### 原定义-L135

来源标题：当前检查点；原件L135–L146。

> ## 当前检查点
>
> - 当前 Loop：1
> - 最近完成：唯一全新只读 high/high Validator 按 VC-001 返回固定结构 PASS，无 blocker/unknown。
> - 当前焦点：任务完成并归档；M11 继续等待下一阶段 Failure Analyst。
> - 下一动作：由用户决定是否启动独立 M11 诊断；本任务不自动续跑。
> - 阻塞项：无。
> - blocker_type：`none`
> - 诊断状态：`not_triggered`
> - 已变更文件：根 Harness 六文件、A-019、第三方声明、M11/PLANS/memory/本计划；`source/` 未新增本任务改动。
> - 待验证项：无。
>

### 原定义-L147

来源标题：Validator 结论处理；原件L147–L152。

> ## Validator 结论处理
>
> | Loop | Validator 身份 | 合同版本 | 结论 | 绑定标准与证据 | 主协调 Agent处理 | 是否触发诊断 | 下一 Validator |
> | --- | --- | --- | --- | --- | --- | --- | --- |
> | 1 | 全新只读 ADHOC-0015 Validator | VC-001 | PASS | AC-001～006、INV-001～004、GATE-001～007 全部通过 | 完成并归档 | 否 | 无 |
>

### 原定义-L153

来源标题：失败尝试与诊断；原件L153–L159。

> ## 失败尝试与诊断
>
> 当前没有本任务失败特征或诊断触发。第一次快照恢复演练因本机 Python 不支持
> `tarfile.extractall(filter=...)` 在仓库外失败；未修改仓库，随后使用同等路径逃逸检查的兼容
> 方式完成恢复演练，不属于产品或合同失败。未完成目录已标记为
> `/private/tmp/trainlab-agentforge-v044-preupdate.invalid.rapavuhv`，不得作为恢复依据。
>

### 原定义-L160

来源标题：决策与发现；原件L160–L166。

> ## 决策与发现
>
> - 上游 v0.4.2→v0.4.4 只修改六个核心模板文件并新增上游自身历史计划；后者不复制。
> - 当前六文件三方预演：template 无冲突；AGENTS 2 处、README/CHANGELOG/memory 各 1 处、
>   exec-plan README 3 处需要人工适配。
> - v0.4.4 不改变 src/tests 布局，A-003 的历史布局决定保留；A-019 只更新当前治理版本。
>

### 原定义-L167

来源标题：v0.4.2 → v0.4.4 差异映射；原件L167–L180。

> ### v0.4.2 → v0.4.4 差异映射
>
> | 上游项目 | 处理结论 | TrainLab 适配 |
> | --- | --- | --- |
> | `AGENTS.md` | `adapted` | 采用冻结合同、固定 Validator 输出、诊断门与 Failure Analyst；保留 source、隐私、Skills、Git 和外部动作规则。 |
> | `README.md` | `adapted` | 更新为 v0.4.4 和开发—验证—诊断流程；保留 TrainLab 产品目录与运行说明。 |
> | `CHANGELOG.md` | `adapted` | 仅在 TrainLab `Unreleased` 记录本次适配，不复制上游发布历史。 |
> | `memory.md` | `adapted` | 更新稳定版本事实、合同/诊断规则和活动指针，不复制上游静态模板事实。 |
> | `docs/exec-plans/README.md` | `adapted` | 采用完整合同/诊断/隔离协议；保留 TrainLab 串行与禁用 orchestrate 规则。 |
> | `docs/exec-plans/template.md` | `adapted` | 采用 v0.4.4 全部字段；测试映射改为 A-009 的 `source/tests` 双层结构。 |
> | 上游 completed plans | `not_applicable` | 属于 agentForge 自身发布历史，不复制到 TrainLab。 |
> | 上游示例 memory 与 `src/tests` 占位 | `not_applicable` | 不属于 TrainLab 当前事实或产品布局。 |
> | 上游 MIT `LICENSE` | `adapted` | 完整文本保存于 `docs/legal/third-party-notices.md`，仅覆盖所采用脚手架，不重新许可产品。 |
>

### 原定义-L181

来源标题：Validator 固定输出；原件L181–L186。

> ## Validator 固定输出
>
> 必须原样包含 `contract_version`、`overall_verdict`、`criterion_results`、
> `blocking_findings`、`advisories`、`scope_change_candidates`、`unknowns` 和
> `commands_and_evidence`。未绑定冻结标准的 blocker 使报告为 `INCONCLUSIVE`。
>

### 原定义-L187

来源标题：任务级独立验证；原件L187–L199。

> ## 任务级独立验证
>
> - 逐字冻结合同版本：`VC-001`
> - 中性交接：`仅冻结合同、适用规则和当前仓库结果`
> - Validator 身份/上下文：全新只读 high/high `adhoc0015_validator`；未参与实施。
> - `criterion_results`：AC-001～006、INV-001～004、GATE-001～007 全部 `PASS`。
> - `blocking_findings`：`[]`
> - `advisories`：默认 Python 环境未装 pytest，使用与 `requirements.txt` 精确版本一致的既有只读缓存环境完成门禁；不影响裁决。
> - `scope_change_candidates`：`[]`
> - `unknowns`：`[]`
> - `commands_and_evidence`：Tag/Commit、六文件映射、115项快照与restore、MIT逐字比较、664 tests、Ruff/format/mypy、97 AST、78 JSON、隐私/权限/diff、正式state完整对象相等。
> - `overall_verdict`：`PASS`
>

### 原定义-L200

来源标题：集成级独立验证；原件L200–L203。

> ## 集成级独立验证
>
> - `overall_verdict`：`不适用——严格串行、无并行集成`
>

### 原定义-L204

来源标题：PLANS 回写清单；原件L204–L207。

> ## PLANS 回写清单
>
> `不适用——ADHOC 治理任务；已归档计划并删除 memory 活动指针，M11 Roadmap 保持 blocked/DIAGNOSIS_PENDING。`
>

### 原定义-L208

来源标题：迭代日志；原件L208–L214。

> ## 迭代日志
>
> | 日期/上下文 | 已完成事项与证据 | 发现 | 下一动作 |
> | --- | --- | --- | --- |
> | 2026-08-24 / upgrade-start | Git 与 v0.4.4 来源核对；115 项 owner-only 快照和仓库外恢复演练通过 | 当前工作区很脏但已闭合保护；正式 state before 指纹已保存 | 冻结 VC-001 后三方适配根 Harness |
> | 2026-08-24 / gates-pass | 六核心文件适配、A-019、MIT、M11迁移和静态门完成；664 tests、Ruff/format/mypy、97 AST及隐私门PASS；state SHA仍为`7cc9f67...30f43` | 本任务未改变107个既有source文件字节/权限，Provider与外部动作0 | 交唯一全新只读Validator |
> | 2026-08-24 / validator-pass | 全新只读high/high Validator按VC-001复跑并返回固定结构PASS | 无blocking finding、scope candidate或unknown；正式state完整对象相等 | 归档ADHOC-0015；M11保持等待诊断 |

## 历史来源与证据

- [不可变原件快照](../evidence/ADHOC-0029/history.zip)，条目`docs/exec-plans/completed/ADHOC-0015-agentforge-0.4.4-upgrade.md`，原SHA-256：`a629877ebb1c4e91ecb2fae43a21fcbd8e721f0f386633198244bd02e341bfa9`。
- [来源清单](../evidence/ADHOC-0029/history-manifest.json)、[迁移/编号映射](../evidence/ADHOC-0029/migration-manifest.json)、[原问题与失败计数索引](../evidence/ADHOC-0029/failure-index.json)。原记录中的绝对路径和失效外部证据只说明当时事实，不据此复建旧路径。
- 历史快照仅用于保真审查，不作为现行规范、产品导入、Schema、AI输入或CI运行依赖。当前实际迁移验收见[ADHOC-0029](../completed/ADHOC-0029-agentsmd-upgrade.md)。
