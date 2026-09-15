# 执行计划：move local runtime data and switch product root

## 对应目标

- 功能编号：M1-0003
- 功能状态：[completed]
- 总计划对应条目：[PLAN.md](../../PLAN.md) 的同编号/原Roadmap关联条目。
- 目标及范围和验收要求的引用：历史目标、范围、每个阶段/任务、验收要求及全部执行证据按对应原件保存；不是新的实施授权。
- 迁移说明：只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 当前协作规则仅以[AGENTS.md](../../AGENTS.md)为准；原合同及旧规范在快照中仅作历史来源，不继续生效为第二套流程。

## 阶段与任务

以下逐项迁移原实施分解；任务名称、已有编号、结果及明确依赖保留。原无编号步骤按原表顺序首次赋予L编号，不重编号已有步骤。HISTORY仅是原单阶段的归组，不再替代实际任务。此表描述历史工作，不是当前可执行规范/示例或外部授权；暂停条件见检查点。

| 阶段编号 | 状态 | 预期成果 | 依赖 |
| --- | --- | --- | --- |
| HISTORY | [completed] | Work；保留原逐项成果/未完成边界 | 原前置要求及总计划同编号依赖；未另列的依赖不新增 |

| 任务编号 | 所属阶段 | 状态 | 输入输出及错误边界 | 依赖 | 检查方法 | 结果与证据（检查命令或人工方式、退出结果及关键证据） |
| --- | --- | --- | --- | --- | --- | --- |
| L01 | HISTORY | [completed] | Stop supervisor and prove no writers；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原表未单列；沿用原功能前置条件，不按编号新增依赖；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：Evidence：old failing LaunchAgent booted out; no TrainLab writer process；原完成范围不扩大；对应原执行计划 L26 |
| L02 | HISTORY | [completed] | Freeze metadata/hash manifest；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原表未单列；沿用原功能前置条件，不按编号新增依赖；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：Evidence：0600 `/tmp` evidence for 70,167 state files, 4 private configs, and 7 logs；原完成范围不扩大；对应原执行计划 L27 |
| L03 | HISTORY | [completed] | Atomically move runtime roots；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原表未单列；沿用原功能前置条件，不按编号新增依赖；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：Evidence：same-volume moves; every file hash/mode/owner matched; state/log root inodes preserved；原完成范围不扩大；对应原执行计划 L28 |
| L04 | HISTORY | [completed] | Switch and verify LaunchAgent/product root；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原表未单列；沿用原功能前置条件，不按编号新增依赖；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：Evidence：status/verify/doctor exits 0; plist points to `product/`; installed with `--no-start` because startup can dispatch unauthorized due business work；原完成范围不扩大；对应原执行计划 L29 |
| L05 | HISTORY | [completed] | Independent validation；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原表未单列；沿用原功能前置条件，不按编号新增依赖；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：Evidence：fresh read-only Validator PASS; migration accepted, activation explicitly separate；原完成范围不扩大；对应原执行计划 L30 |

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

> Move the local runtime roots into `product/` without byte, permission, or owner
> drift; switch the local supervisor to the product root; verify read-only product
> status; retain a reversible pre-switch manifest; and pass independent validation.

原阶段/任务及其结果见上表，原问题及计数见问题记录；额外来源标识仍可在迁移清单中检索，原件供逐行核对。

## 原任务定义与验收

本节承接原任务定义的全部内容，而非仅保留状态摘要或指向压缩包。上表每个原任务的输入输出/错误边界及检查方法均关联本节；原文有同编号专属标题时另外关联该精确段落，公共目标/范围/合同与其他定义完整保留在本节。不得把原表中的“已接入/PASS”当作完整定义。

**适用性：全部引文均属于该历史任务的原目标、合同修订和执行记录，不是当前开发协议、可运行示例或新的业务授权。** 多版本材料按原任务编号、版本和日期定位，不把后续规则回套早期结果。旧流程/命令/目录和“当前”措辞只描述原记录时点；根AGENTS是唯一现行协作规则，暂停/取消按本文件的新检查点处理，不恢复旧产品。

为保留可核查语义，原件按标题和源行完整投射为引用块；只增加引用前缀，并将旧Markdown导航链接显示为“原定位”文字，未更改原件。原字节/原哈希由history.zip及history-manifest.json证明，不把显示投射声称为原字节。全部源行连续覆盖，原始执行/协调记录也标为历史数据，不混入当前阶段状态。

### 原定义-L1

来源标题：原文导言；原件L1–L9。

> # Execution plan: move local runtime data and switch product root
>
> - Status: `completed`
> - Roadmap ID: `M1-0003`
> - Owner: coordinating Agent
> - Dependency: M1-0002 completed and independently validated
> - Started: 2026-08-12
> - Updated: 2026-08-12
>

### 原定义-L10

来源标题：Goal and acceptance；原件L10–L15。

> ## Goal and acceptance
>
> Move the local runtime roots into `product/` without byte, permission, or owner
> drift; switch the local supervisor to the product root; verify read-only product
> status; retain a reversible pre-switch manifest; and pass independent validation.
>

### 原定义-L16

来源标题：Scope and exclusions；原件L16–L21。

> ## Scope and exclusions
>
> Local `state`, private config, logs, ignored fixture metadata, local LaunchAgent,
> and obsolete root venv. No Garmin provider call, analysis, mail, remote Git,
> release, or publication.
>

### 原定义-L22

来源标题：Work；原件L22–L31。

> ## Work
>
> | Step | Status | Evidence |
> | --- | --- | --- |
> | Stop supervisor and prove no writers | done | old failing LaunchAgent booted out; no TrainLab writer process |
> | Freeze metadata/hash manifest | done | 0600 `/tmp` evidence for 70,167 state files, 4 private configs, and 7 logs |
> | Atomically move runtime roots | done | same-volume moves; every file hash/mode/owner matched; state/log root inodes preserved |
> | Switch and verify LaunchAgent/product root | done | status/verify/doctor exits 0; plist points to `product/`; installed with `--no-start` because startup can dispatch unauthorized due business work |
> | Independent validation | done | fresh read-only Validator PASS; migration accepted, activation explicitly separate |
>

### 原定义-L32

来源标题：Current checkpoint；原件L32–L40。

> ## Current checkpoint
>
> - Current loop: completed
> - Last completed: independent Validator PASS
> - Next action: archive plan and close M1 Roadmap
> - Blockers: none
> - Changed paths: local runtime roots, LaunchAgent plist, deploy no-start control and migration governance
> - Pending validation: none; business supervisor remains intentionally unloaded pending separate authorization to dispatch due work
>

### 原定义-L41

来源标题：Independent validation；原件L41–L46。

> ## Independent validation
>
> - Neutral brief: validate only metadata, process paths, Git/privacy boundaries, and read-only product status; never inspect private contents.
> - Validator tier: `high/high`
> - Result: `PASS`
>

### 原定义-L47

来源标题：Iteration log；原件L47–L53。

> ## Iteration log
>
> | Date/context | Evidence | Finding | Next action |
> | --- | --- | --- | --- |
> | 2026-08-12/current | M1-0002 final Validator PASS | runtime switch dependency satisfied | preflight and freeze evidence |
> | 2026-08-12/current | all migration manifests compare equal; read-only status/verify/doctor exit 0 | starting Supervisor can claim due Garmin/analysis/mail work, conflicting with this migration's zero-business-effect boundary | install product-root plist with `--no-start`; require separate authorization for activation |
> | 2026-08-12/current | independent Validator confirmed data parity, read-only receipts, LaunchAgent target, inactive safety state, Git/privacy and dist boundaries | PASS; activation remains separate | archive and close Roadmap |

## 历史来源与证据

- [不可变原件快照](../evidence/ADHOC-0029/history.zip)，条目`docs/exec-plans/completed/M1-runtime-root-0003-data-switch.md`，原SHA-256：`bf0d29a3e53fb02dadcff7ffaf5abafb266250bf3f26b6d3932bf41129d1e364`。
- [来源清单](../evidence/ADHOC-0029/history-manifest.json)、[迁移/编号映射](../evidence/ADHOC-0029/migration-manifest.json)、[原问题与失败计数索引](../evidence/ADHOC-0029/failure-index.json)。原记录中的绝对路径和失效外部证据只说明当时事实，不据此复建旧路径。
- 历史快照仅用于保真审查，不作为现行规范、产品导入、Schema、AI输入或CI运行依赖。当前实际迁移验收见[ADHOC-0029](../completed/ADHOC-0029-agentsmd-upgrade.md)。
