# 执行计划：增量更新、补发日报周计划并监测 12 小时

## 对应目标

- 功能编号：ADHOC-0007
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
| L01 | HISTORY | [completed] | 审计日期、进程、数据覆盖、分析 Artifact 和 delivery；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原表未单列；沿用原功能前置条件，不按编号新增依赖；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：证据：香港日期 2026-08-12；无 TrainLab 业务进程；Supervisor 未加载；核心 Garmin cursor 到 08-09；日报 delivery 32–34 已交付；当前周报 79/80 尚无交付；原完成范围不扩大；对应原执行计划 L66 |
| L02 | HISTORY | [completed] | 冻结 Garmin 窗口/资源/预算并有界增量；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原表未单列；沿用原功能前置条件，不按编号新增依赖；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：证据：08-10..12 full succeeded/complete/gaps0；08-13 repair succeeded/gaps0；核心 8 cursors 到 08-13；token 不变；原完成范围不扩大；对应原执行计划 L67 |
| L03 | HISTORY | [completed] | 生成缺失日报与周计划；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原表未单列；沿用原功能前置条件，不按编号新增依赖；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：证据：summary 08-10/11/12 与 advice 08-11/12/13 已生成；当前修订周报 79/80 创建更正 delivery 39；原完成范围不扩大；对应原执行计划 L68 |
| L04 | HISTORY | [completed] | Gmail 幂等补发与正式对账；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原表未单列；沿用原功能前置条件，不按编号新增依赖；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：证据：delivery 36–39 均 sent；旧周报保留；最终 pending/unknown/failed 均 0；原完成范围不扩大；对应原执行计划 L69 |
| L05 | HISTORY | [completed] | 修复外置卷 LaunchAgent Python 导入路径；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原表未单列；沿用原功能前置条件，不按编号新增依赖；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：证据：失败回归先红；实现后本地门绿；全新独立 Validator PASS（19 focused、实际 host import、固定 CLI、安全边界）；原完成范围不扩大；对应原执行计划 L70 |
| L06 | HISTORY | [plan] | 每 15 分钟监测，累计 12 小时；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原表未单列；沿用原功能前置条件，不按编号新增依赖；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 本项待实施/验收；原栏：证据：用户于 2026-08-13 07:48 明确要求停止所有运行进程；等待会话、Supervisor 与 heartbeat 均已停止，现无有效连续窗口；原待实施项；按原文区分历史已发生结果与待办，不把预期写成通过；对应原执行计划 L71 |
| L07 | HISTORY | [plan] | 完成审计、归档计划、完成 goal；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原表未单列；沿用原功能前置条件，不按编号新增依赖；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 本项待实施/验收；原栏：证据：—；原待实施项；按原文区分历史已发生结果与待办，不把预期写成通过；对应原执行计划 L72 |

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
| ISSUE-L137 | 原要求/观察/裁决逐条记录；见本行源原文，不将规则或下一动作当发生事实 | 原行未单列修法则不推断；全部尝试/动作保留于右列及原上下文 | 原行未给统一累计值；保留原次数表述，不置0或按索引条数计次数 | &#124; 2026-08-12 / Loop 3 &#124; 冻结拆分预算并启动合法 08-10..11 full；receipt 显示 Provider/活动/FIT/raw 全 0，token 不变 &#124; cached DI token 需要刷新，而 cached-only 正确失败关闭 &#124; 请求一次仅 refresh-token 授权 &#124;；原件L137 |
| ISSUE-L143 | 原要求/观察/裁决逐条记录；见本行源原文，不将规则或下一动作当发生事实 | 原行未单列修法则不推断；全部尝试/动作保留于右列及原上下文 | 原行未给统一累计值；保留原次数表述，不置0或按索引条数计次数 | &#124; 2026-08-13 / Loop 9 &#124; 失败回归先红；修复 plist/安装器/runbook；15 项聚焦、静态门、repository quality 与实际渲染 host import 均绿 &#124; 真实 host Python 需受控 `src` + venv `site-packages`，不能依赖 `__PYVENV_LAUNCHER__` &#124; 全新只读 Validator &#124;；原件L143 |
| ISSUE-L146 | 原要求/观察/裁决逐条记录；见本行源原文，不将规则或下一动作当发生事实 | 原行未单列修法则不推断；全部尝试/动作保留于右列及原上下文 | 原行未给统一累计值；保留原次数表述，不置0或按索引条数计次数 | &#124; 2026-08-13 / Loop 12 &#124; 正式检查点 2/48 healthy；PID/runs 不变、新日志 0、doctor ready、数据和 delivery 无异常、token 不变 &#124; 连续稳定窗口成立 30 分钟 &#124; 等待检查点 3/48 &#124;；原件L146 |
| ISSUE-L148 | 原要求/观察/裁决逐条记录；见本行源原文，不将规则或下一动作当发生事实 | 原行未单列修法则不推断；全部尝试/动作保留于右列及原上下文 | 原行未给统一累计值；保留原次数表述，不置0或按索引条数计次数 | &#124; 2026-08-13 / Loop 14 &#124; 检查点 3 发现两个 startup expired misfire；立即停止 Supervisor，确认历史业务已交付且游标前移，正式 suppress 并重启 &#124; 这是启动恢复产生的需人工处置警告，不是业务重跑或新失败 &#124; 新窗口从 07:36:04、0/48 开始 &#124;；原件L148 |
| ISSUE-L149 | 原要求/观察/裁决逐条记录；见本行源原文，不将规则或下一动作当发生事实 | 原行未单列修法则不推断；全部尝试/动作保留于右列及原上下文 | 原行未给统一累计值；保留原次数表述，不置0或按索引条数计次数 | &#124; 2026-08-13 / Loop 15 &#124; 按用户明确指令中断等待、卸载 LaunchAgent、停止 Supervisor 并核对业务进程为 0；heartbeat 不存在 &#124; 12 小时连续窗口作废；数据与交付保持不变 &#124; 保持停止，等待用户下一步 &#124;；原件L149 |

## 历史目标与原编号索引

下文仅引用当时目标，不是现行规范或可运行示例；已经被新方案替代的业务不复活。原阶段/任务已在上表逐项迁移；原早期状态与最终范围不同的映射依据逐项标明，不借迁移扩大历史完成范围。

> - 基于现有正式数据，将 Garmin 数据有界增量更新到 `Asia/Hong_Kong` 的今天。
> - 从仓库根运行产品 Harness；AI 路由继续使用本机 Codex CLI。
> - 识别并生成缺失的每日总结、每日建议和周计划，不重复已接受结果。
> - 通过精确 Gmail MCP 做逐项幂等搜索、发送、标签与正式对账，最终无 actionable pending delivery。
> - 每 15 分钟检查唯一 Supervisor、任务状态、失败/未知投递和凭据安全，累计满足 12 小时。
> - 异常时先停止相关进程，在本计划内诊断；需要代码修复时按开发 Harness 建任务、测试、独立验证后再启动。

原阶段/任务及其结果见上表，原问题及计数见问题记录；额外来源标识仍可在迁移清单中检索，原件供逐行核对。

## 原任务定义与验收

本节承接原任务定义的全部内容，而非仅保留状态摘要或指向压缩包。上表每个原任务的输入输出/错误边界及检查方法均关联本节；原文有同编号专属标题时另外关联该精确段落，公共目标/范围/合同与其他定义完整保留在本节。不得把原表中的“已接入/PASS”当作完整定义。

**适用性：全部引文均属于该历史任务的原目标、合同修订和执行记录，不是当前开发协议、可运行示例或新的业务授权。** 多版本材料按原任务编号、版本和日期定位，不把后续规则回套早期结果。旧流程/命令/目录和“当前”措辞只描述原记录时点；根AGENTS是唯一现行协作规则，暂停/取消按本文件的新检查点处理，不恢复旧产品。

为保留可核查语义，原件按标题和源行完整投射为引用块；只增加引用前缀，并将旧Markdown导航链接显示为“原定位”文字，未更改原件。原字节/原哈希由history.zip及history-manifest.json证明，不把显示投射声称为原字节。全部源行连续覆盖，原始执行/协调记录也标为历史数据，不混入当前阶段状态。

### 原定义-L1

来源标题：原文导言；原件L1–L11。

> # 执行计划：增量更新、补发日报周计划并监测 12 小时
>
> - 状态：`cancelled`
> - 负责人：主协调 Agent
> - Roadmap ID：`ADHOC-0007`
> - 阶段/子项目：`不适用`
> - Batch ID：`serial-production`
> - 返工来源：`无`
> - 开始日期：2026-08-12
> - 最后更新：2026-08-13
>

### 原定义-L12

来源标题：目标与验收标准；原件L12–L20。

> ## 目标与验收标准
>
> - 基于现有正式数据，将 Garmin 数据有界增量更新到 `Asia/Hong_Kong` 的今天。
> - 从仓库根运行产品 Harness；AI 路由继续使用本机 Codex CLI。
> - 识别并生成缺失的每日总结、每日建议和周计划，不重复已接受结果。
> - 通过精确 Gmail MCP 做逐项幂等搜索、发送、标签与正式对账，最终无 actionable pending delivery。
> - 每 15 分钟检查唯一 Supervisor、任务状态、失败/未知投递和凭据安全，累计满足 12 小时。
> - 异常时先停止相关进程，在本计划内诊断；需要代码修复时按开发 Harness 建任务、测试、独立验证后再启动。
>

### 原定义-L21

来源标题：范围与非目标；原件L21–L26。

> ## 范围与非目标
>
> - 允许写入：正式 Garmin 增量数据、分析 Artifact/plan/delivery 状态、经幂等门发送的固定自投邮件、本计划和必要开发修复。
> - 禁止写入：未授权收件人、密码/MFA、额外 token 刷新、历史全量回退、私人数据进 Git、远端 Git、发布。
> - 不删除旧邮件、正式 raw/FIT/数据库或凭据；不恢复旧 `.orchestration` 控制面。
>

### 原定义-L27

来源标题：适用规则与参考资料；原件L27–L34。

> ## 适用规则与参考资料
>
> - 已批准规则：A-001、A-002、A-003、A-004。
> - 产品 Harness：`harness/shared/HARNESS.md`、`harness/analysis/HARNESS.md`、
>   `harness/analysis/daily.md`、`weekly.md`、`delivery.md`、`harness/mail/HARNESS.md`。
> - Runbook：Garmin collection、analysis controlled acceptance、Gmail production、macOS Supervisor。
> - 用户授权：当前 goal 的增量、分析、补发、故障修复与 12 小时监测目标。
>

### 原定义-L35

来源标题：依赖与隔离；原件L35–L41。

> ## 依赖与隔离
>
> - 显式依赖：ADHOC-0005/0006 已验证 Gmail 与 Garmin 项目 token 有效。
> - 共享接口和冻结依据：`Asia/Hong_Kong` 本地日期、正式 SQLite 元数据、稳定 invocation ID、accepted-before-send/idempotency 合同。
> - 分支/Worktree/集成分支：默认不适用；若发现代码缺陷，需在本计划记录独立任务范围后再创建。
> - 生产执行严格串行；任何时刻只允许一个业务命令或 Supervisor owner。
>

### 原定义-L42

来源标题：功能与测试映射；原件L42–L50。

> ## 功能与测试映射
>
> | 功能 | Feature slug | 测试目录 | 必须满足的行为 |
> | --- | --- | --- | --- |
> | Garmin 有界增量 | 既有 | 既有 Garmin 合同 | 明确日期/资源/预算，cached-only，禁止历史回退 |
> | 日报与周计划 | 既有 | 既有 analysis 合同 | 根目录 Harness、Codex CLI、accepted Artifact |
> | Gmail 交付 | 既有 | 既有 delivery 合同 | 精确搜索、自投、标签、正式对账、无重复 |
> | 12 小时监测 | 既有 | Supervisor/status 合同 | 每 15 分钟、唯一进程、异常失败关闭 |
>

### 原定义-L51

来源标题：工具采用情况；原件L51–L57。

> ## 工具采用情况
>
> - 先使用只读 `foundation/garmin/orchestrate/supervisor` 状态与 SQLite 元数据审计。
> - 生产命令使用 `.venv/bin/trainlab`；AI 子进程由项目既有 Codex CLI 入口管理。
> - Gmail 仅使用当前精确 `gmail` MCP 绑定。
> - 代码修复才运行适用 Ruff、mypy、定向/完整 pytest 和全新独立 Validator。
>

### 原定义-L58

来源标题：Subagent 派发；原件L58–L61。

> ## Subagent 派发
>
> 当前不派发——生产动作串行且用户未要求并行；如发生代码修复，按 AGENTS 动态选档并记录。
>

### 原定义-L62

来源标题：工作分解；原件L62–L73。

> ## 工作分解
>
> | 步骤 | 状态 | 证据 |
> | --- | --- | --- |
> | 审计日期、进程、数据覆盖、分析 Artifact 和 delivery | `completed` | 香港日期 2026-08-12；无 TrainLab 业务进程；Supervisor 未加载；核心 Garmin cursor 到 08-09；日报 delivery 32–34 已交付；当前周报 79/80 尚无交付 |
> | 冻结 Garmin 窗口/资源/预算并有界增量 | `completed` | 08-10..12 full succeeded/complete/gaps0；08-13 repair succeeded/gaps0；核心 8 cursors 到 08-13；token 不变 |
> | 生成缺失日报与周计划 | `completed` | summary 08-10/11/12 与 advice 08-11/12/13 已生成；当前修订周报 79/80 创建更正 delivery 39 |
> | Gmail 幂等补发与正式对账 | `completed` | delivery 36–39 均 sent；旧周报保留；最终 pending/unknown/failed 均 0 |
> | 修复外置卷 LaunchAgent Python 导入路径 | `completed` | 失败回归先红；实现后本地门绿；全新独立 Validator PASS（19 focused、实际 host import、固定 CLI、安全边界） |
> | 每 15 分钟监测，累计 12 小时 | `pending` | 用户于 2026-08-13 07:48 明确要求停止所有运行进程；等待会话、Supervisor 与 heartbeat 均已停止，现无有效连续窗口 |
> | 完成审计、归档计划、完成 goal | `pending` | — |
>

### 原定义-L74

来源标题：当前检查点；原件L74–L85。

> ## 当前检查点
>
> - 当前 Loop：用户要求的完全停止状态。
> - 最近完成：日报 delivery 36–38 与更正周报 delivery 39 均 sent；正式 status pending/unknown/failed 均 0。首次启动 Supervisor 后出现 launchd crash loop，已立即卸载且进程数 0。
> - 当前焦点：保持所有 TrainLab 运行进程停止。
> - 下一动作：除非用户另行要求恢复，否则不重启 Supervisor、不恢复 heartbeat、不执行业务命令。
> - 阻塞项：无；用户已明确授权一次受限刷新。
> - 已变更文件：本计划、memory 活动指针。
> - 待验证项：12 小时连续稳定性监测结果。
>
> > 终止说明：用户在新的 goal 中将目标切换为仓库结构、配置、打包和历史文件优化。主协调 Agent 已删除旧 heartbeat 并精确停止 Supervisor；12 小时监测不再继续，本计划保留既有补数、交付和监测证据后以 `cancelled` 归档。
>

### 原定义-L86

来源标题：12 小时监测记录；原件L86–L93。

> ## 12 小时监测记录
>
> | 检查点 | 香港时间 | Supervisor | 产品状态 | 数据/交付/凭据 | 结论 |
> | --- | --- | --- | --- | --- | --- |
> | 1/48 | 2026-08-13 07:04:38 | launchd running；PID 99996；进程 1；runs 2；新 stdout/stderr 0 | doctor accepted/ready；无新 workflow failure | 核心 cursors 8/8 到今天；gaps 0；正式 actionable delivery 0；历史 incident 无新增；token 不变 | healthy |
> | 2/48 | 2026-08-13 07:19:06 | launchd running；PID 99996；进程 1；runs 2；新 stdout/stderr 0 | doctor accepted/ready；无新 workflow failure | 核心 cursors 8/8 到今天；gaps 0；正式 pending/unknown/failed 与 actionable 均 0；历史 incident 无新增；token 不变 | healthy |
> | 3/48（原窗口） | 2026-08-13 07:34:04 | PID 99996 连续、日志 0、doctor ready，但按规则立即停止 | 新增 morning 08-08 与 weekly 08-10 两个 expired misfire incident | 对应历史业务已人工补齐并交付；正式 suppress 审计 21436/21437 accepted；调度游标已前移 | failed；窗口重置 |
>

### 原定义-L94

来源标题：决策与发现；原件L94–L117。

> ## 决策与发现
>
> - “今天”固定为命令执行时 `Asia/Hong_Kong` 的本地日期。
> - 不假定缺失日期；从正式元数据只读审计后逐项生成。
> - Garmin 本次冻结窗口为 `2026-08-10..2026-08-12`；资源为 `heart_rates`、`rhr`、`spo2`、`sleep`、`hrv`、`body_composition`、`weigh_ins`、`max_metrics`、`activity_inventory`、`activity_summary`、`activity_fit`、`activity_weather`；预算为 Provider 80、wall 600 秒、activities 20、FIT 20、new raw 80，且仅 cached token。
> - 产品合同禁止 full 的 through 为香港当天；08-12 当时曾拆为 08-10..11 full 与 08-12 repair，但均未进入 Provider；跨日后已由下面的新冻结范围替代。
> - 原 08-10..12 full 命令仅在本地参数预检以 `invalid_request` 停止；随后合法的 08-10..11 full 在 Provider 前以 `cached_token_refresh_forbidden` 停止。两次均没有 Provider/数据写入，token 未变，不视为已消耗生产预算。
> - 再次只读比较默认 Garmin MCP token 与项目 token：字节完全一致，目录 0700、文件 0600；因此重复复制不能解决过期问题，必须由现有 refresh token 产生新 DI token。
> - 已核对依赖实现：单次受限刷新可仅加载项目 tokenstore、调用 DI refresh、持久化刷新结果并验证 profile/settings；不需要用户名、密码或 MFA。未获新授权前不执行。
> - 用户授权后已完成单次受限刷新：refresh 调用 1、项目 token 写入 1、token 发生变化、权限与属主保持、无密码/MFA；随后 cached-only 验证成功并确认 token 不变。
> - 香港本地日期已变为 2026-08-13。新的冻结范围为 08-10..12 full（Provider 75 / wall 600s / activities 20 / FIT 20 / raw 75）与 08-13 repair（Provider 25 / wall 300s / activities 5 / FIT 5 / raw 25）；12 项资源不变，总上限 100 / 900s / 25 / 25 / 100。
> - 首次路径修正后调用仍读到旧 token，最终定位为 Foundation 的活动 `state_root` 是 `state/runtime`，而先前刷新落在 `state/secrets`。未再次 refresh；按既有同步授权将刷新结果一次性原子复制到活动 `state/runtime/secrets/garmin`，旧活动 token 已保存于 0700/0600 临时备份。正式路径 cached-only 验证随后通过。
> - 08-10..12 full 终态 succeeded/complete/open gaps 0；08-13 repair succeeded/open gaps 0；核心 8 个 health cursor 全到 08-13。
> - 三份日报分别生成 Artifact 81/82、83/84、85/86 与 delivery 36/37/38；质量依次 ready、ready、ready_with_warnings，均无 errors。更正周报使用当前 79/80 创建 delivery 39。四条 delivery 均经精确 Gmail 绑定正式 sent，status 显示 pending/unknown/failed 皆 0。
> - 用户反馈未看到邮件后已暂停计时等待并做 Gmail 直接核验：delivery 36–39 的精确 transport marker 各命中 1 条；四封均为 self-delivery，实际标签同时含 `INBOX`、`UNREAD`、`SENT` 与 TrainLab 专用标签，且不在 spam/trash。没有重发，Supervisor 连续运行未中断。
> - Supervisor doctor 通过但 LaunchAgent 启动失败；日志末尾证明真实 host Python `No module named trainlab`。安装器解析 host Python 后只设置 `__PYVENV_LAUNCHER__`，该变量对直接执行真实解释器无效。服务已卸载，未留下进程。
> - 修复后全新独立 Validator PASS；LaunchAgent 已安装并稳定为单一 PID，doctor accepted/ready，新日志字节为 0，核心 Garmin 资源仍覆盖到 08-13、gaps 0，活动 token 与冻结刷新结果字节一致。连续监测从香港时间 2026-08-13 06:48:55 开始。
> - 原稳定窗口在检查点 3 发现启动恢复产生的 `scheduler:morning:2026-08-08:misfire` 与 `scheduler:weekly:2026-08-10:misfire`。按计划停止唯一 Supervisor；验证这两个过期任务的日报/周报已由本次正式补发覆盖、morning/weekly 游标已前移到 08-13/08-17 后，使用正式 `orchestrate suppress` 留下审计 21436/21437。Supervisor 于 07:36:04 以新 PID 2215 恢复，连续窗口从该时刻重置。
> - 用户随后明确要求停止所有运行进程：计时等待会话以中断码 130 结束；LaunchAgent 已卸载并删除 plist；Supervisor 精确进程数 0；项目 heartbeat 已不存在；TrainLab 业务进程扫描为 0。日志、数据库、邮件与凭据均保留。
> - 历史 delivery 32–34 已覆盖 08-07/08/09；旧 pending 20–25 不属于本次“这几天”范围，不盲发。
> - 当前周报 Artifact 79/80 是修订 2；已发送 delivery 35 绑定的是已 supersede 的 77/78。用户已批准额外更正周报，因此使用不可变 resend authorization 创建新的 pending delivery，旧邮件保留。
> - incident 17/19 分别绑定 08-06/08-07 的失败 morning workflow；当前无对应进程，保留历史证据，待新流程稳定后按正式状态处理。
> - 监测的 12 小时完成前 goal 保持 active。
>

### 原定义-L118

来源标题：任务级独立验证；原件L118–L122。

> ## 任务级独立验证
>
> - 生产结果以正式 receipt、状态表、Gmail 对账和监测记录为权威证据。
> - 若发生代码修改，必须另行派发全新只读 Validator。
>

### 原定义-L123

来源标题：集成级独立验证；原件L123–L126。

> ## 集成级独立验证
>
> - 结果：`不适用——生产动作严格串行`
>

### 原定义-L127

来源标题：PLANS 回写清单；原件L127–L130。

> ## PLANS 回写清单
>
> 非 Roadmap 任务；完成后归档计划并清除 memory 指针。
>

### 原定义-L131

来源标题：迭代日志；原件L131–L149。

> ## 迭代日志
>
> | 日期/上下文 | 已完成事项与证据 | 发现 | 下一动作 |
> | --- | --- | --- | --- |
> | 2026-08-12 / Loop 1 | 读取根开发与产品 Harness；建立长期执行计划 | 生产动作必须串行、12 小时前 goal 不完成 | 只读审计 |
> | 2026-08-12 / Loop 2 | 完成进程、覆盖、Artifact、delivery 与 incident 元数据审计 | 缺 08-10/11 日报；当前周报 79/80 未交付；旧 pending 20–25 不在范围 | 执行 08-10..12 有界 Garmin 增量 |
> | 2026-08-12 / Loop 3 | 冻结拆分预算并启动合法 08-10..11 full；receipt 显示 Provider/活动/FIT/raw 全 0，token 不变 | cached DI token 需要刷新，而 cached-only 正确失败关闭 | 请求一次仅 refresh-token 授权 |
> | 2026-08-12 / Loop 4 | 默认 MCP 与项目 token 字节一致；权限正确；只读确认依赖支持无密码 DI refresh | 再次同步无效，唯一安全解法是获授权后单次刷新 | 等待明确刷新授权 |
> | 2026-08-13 / Loop 5 | 用户明确授权项目现有 refresh token 执行一次 DI refresh；禁止密码/MFA；项目 token 仅写一次结果 | goal 已自动恢复 active | 执行单次刷新并 cached-only 验证 |
> | 2026-08-13 / Loop 6 | 单次 refresh 与单次落盘成功；cached-only profile/settings 2/6，token 不变 | 香港日期已跨到 08-13，需将 08-12 纳入完整日、08-13 作为当日 repair | 执行重新冻结的两段增量 |
> | 2026-08-13 / Loop 7 | 定位活动 token 路径错位并原子同步；正式路径验证通过；full run 83 与 repair run 84 均 succeeded，核心 cursors 到 08-13 | 无 Garmin gap；下一缺口是 08-10/11/12 日报 | 串行运行三次 analysis-only daily |
> | 2026-08-13 / Loop 8 | 修复 activity_inventory coverage 后三份日报和更正周报均 accepted 并 sent；最终 delivery status 无 actionable 项 | Supervisor 启动暴露 host Python import 缺陷；已卸载、进程 0 | TDD 修复 LaunchAgent 导入路径并独立验证 |
> | 2026-08-13 / Loop 9 | 失败回归先红；修复 plist/安装器/runbook；15 项聚焦、静态门、repository quality 与实际渲染 host import 均绿 | 真实 host Python 需受控 `src` + venv `site-packages`，不能依赖 `__PYVENV_LAUNCHER__` | 全新只读 Validator |
> | 2026-08-13 / Loop 10 | 独立 Validator PASS；安装唯一 LaunchAgent，PID 单一、doctor ready、新日志无错误；创建 15 分钟 heartbeat | 实际 launchd 入口已恢复，数据 gaps 0、token 不变 | 累计 12 小时/48 个连续健康检查点 |
> | 2026-08-13 / Loop 11 | 正式检查点 1/48 healthy；唯一 PID 未重启、doctor ready、gaps/actionable delivery 皆 0、token 不变 | SQLite 路径探测误建 0 字节 `state/runtime/data.db`，已精确移入 `/tmp` 隔离；正式 DB 未受影响 | 等待检查点 2/48 |
> | 2026-08-13 / Loop 12 | 正式检查点 2/48 healthy；PID/runs 不变、新日志 0、doctor ready、数据和 delivery 无异常、token 不变 | 连续稳定窗口成立 30 分钟 | 等待检查点 3/48 |
> | 2026-08-13 / Loop 13 | 针对“未收到”反馈直接核对 Gmail：36–39 各精确 1 条且均在 inbox/unread/sent，spam/trash 0；未重发 | 数据库 sent 与真实邮箱可见性已交叉验证；可能是 Gmail 自投展示/筛选造成未看到 | 继续原稳定窗口，等待检查点 3/48 |
> | 2026-08-13 / Loop 14 | 检查点 3 发现两个 startup expired misfire；立即停止 Supervisor，确认历史业务已交付且游标前移，正式 suppress 并重启 | 这是启动恢复产生的需人工处置警告，不是业务重跑或新失败 | 新窗口从 07:36:04、0/48 开始 |
> | 2026-08-13 / Loop 15 | 按用户明确指令中断等待、卸载 LaunchAgent、停止 Supervisor 并核对业务进程为 0；heartbeat 不存在 | 12 小时连续窗口作废；数据与交付保持不变 | 保持停止，等待用户下一步 |

## 历史来源与证据

- [不可变原件快照](../evidence/ADHOC-0029/history.zip)，条目`docs/exec-plans/completed/ADHOC-0007-production-backfill-and-monitor.md`，原SHA-256：`a381d45672ca328d4b39223b9c380f9f8e5c661501663248a9691da3ce9be9c9`。
- [来源清单](../evidence/ADHOC-0029/history-manifest.json)、[迁移/编号映射](../evidence/ADHOC-0029/migration-manifest.json)、[原问题与失败计数索引](../evidence/ADHOC-0029/failure-index.json)。原记录中的绝对路径和失效外部证据只说明当时事实，不据此复建旧路径。
- 历史快照仅用于保真审查，不作为现行规范、产品导入、Schema、AI输入或CI运行依赖。当前实际迁移验收见[ADHOC-0029](../completed/ADHOC-0029-agentsmd-upgrade.md)。
