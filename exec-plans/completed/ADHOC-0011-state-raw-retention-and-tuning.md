# 执行计划：需求草案：source 运行结构、Skills 与 state 数据整理

## 对应目标

- 功能编号：ADHOC-0011
- 功能状态：[completed]
- 总计划对应条目：[PLAN.md](../../PLAN.md) 的同编号/原Roadmap关联条目。
- 目标及范围和验收要求的引用：历史目标、范围、每个阶段/任务、验收要求及全部执行证据按对应原件保存；不是新的实施授权。
- 迁移说明：只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 当前协作规则仅以[AGENTS.md](../../AGENTS.md)为准；原合同及旧规范在快照中仅作历史来源，不继续生效为第二套流程。

## 阶段与任务

以下逐项迁移原实施分解；任务名称、已有编号、结果及明确依赖保留。原无编号步骤按原表顺序首次赋予L编号，不重编号已有步骤。HISTORY仅是原单阶段的归组，不再替代实际任务。此表描述历史工作，不是当前可执行规范/示例或外部授权；暂停条件见检查点。

| 阶段编号 | 状态 | 预期成果 | 依赖 |
| --- | --- | --- | --- |
| HISTORY | [completed] | 原Roadmap四项实施任务及其原完成范围；保留原逐项成果/未完成边界 | 原M6工作区与用户ADHOC-0011目标；不恢复旧业务 |

| 任务编号 | 所属阶段 | 状态 | 输入输出及错误边界 | 依赖 | 检查方法 | 结果与证据（检查命令或人工方式、退出结果及关键证据） |
| --- | --- | --- | --- | --- | --- | --- |
| ADHOC-0011-0001 | HISTORY | [completed] | ADHOC-0011-0001 保存当前 M6 工作区保护提交；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | M6 | 原最终原子切换/回滚、六Skills/备份/raw/删除清单独立复核；只引用原结果；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：Git 本地保护提交；原PLANS明确完成；原执行计划已执行与最终结果确认收尾完成；PLANS.md L176 |
| ADHOC-0011-0002 | HISTORY | [completed] | ADHOC-0011-0002 建立 source Harness、Skills、模板和 SQLite 工具；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | ADHOC-0011-0001 | 原最终原子切换/回滚、六Skills/备份/raw/删除清单独立复核；只引用原结果；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：`source/AGENTS.md`、`source/skills`、模板、共享脚本、SQLite Schema；原PLANS明确完成；原执行计划已执行与最终结果确认收尾完成；PLANS.md L177 |
| ADHOC-0011-0003 | HISTORY | [completed] | ADHOC-0011-0003 candidate raw 重组和新数据库建立；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | ADHOC-0011-0002 | 原最终原子切换/回滚、六Skills/备份/raw/删除清单独立复核；只引用原结果；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：仓库外 candidate、脱敏迁移收据；原PLANS明确完成；原执行计划已执行与最终结果确认收尾完成；PLANS.md L178 |
| ADHOC-0011-0004 | HISTORY | [completed] | ADHOC-0011-0004 归档旧 state、原子切换和离线验证；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | ADHOC-0011-0003 | 原最终原子切换/回滚、六Skills/备份/raw/删除清单独立复核；只引用原结果；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：`data-backup` 归档、`source/state`、只读 cron 配置；原PLANS明确完成；原执行计划已执行与最终结果确认收尾完成；PLANS.md L179 |
| CLOSE-01 | HISTORY | [completed] | candidate 与正式 state 的最终原子切换及回滚收据；；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原四项任务；源退役清单要求切换/备份及独立验证先通过 | 原独立Validator、切换回滚、精确退役与未启用cron记录；不重跑；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：candidate 与正式 state 的最终原子切换及回滚收据；；源已执行与最终结果明确均已完成；原无编号收尾项首次编号；对应原执行计划 L1121 |
| CLOSE-02 | HISTORY | [completed] | 独立 Validator 对六 Skills、备份配对、raw 闭包和删除清单的最终复核；；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原四项任务；源退役清单要求切换/备份及独立验证先通过 | 原独立Validator、切换回滚、精确退役与未启用cron记录；不重跑；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：独立 Validator 对六 Skills、备份配对、raw 闭包和删除清单的最终复核；；源已执行与最终结果明确均已完成；原无编号收尾项首次编号；对应原执行计划 L1122 |
| CLOSE-03 | HISTORY | [completed] | 旧 `source/src`、`source/tests`、`source/scripts`、`source/tools`、`source/typings`、旧 `source/docs`、`source/index.py`、`source/pyproject.toml` 和 `source/requirements.lock` 的 精确退役；；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原四项任务；源退役清单要求切换/备份及独立验证先通过 | 原独立Validator、切换回滚、精确退役与未启用cron记录；不重跑；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：旧 `source/src`、`source/tests`、`source/scripts`、`source/tools`、`source/typings`、旧 `source/docs`、`source/index.py`、`source/pyproject.toml` 和 `source/requirements.lock` 的 精确退役；；源已执行与最终结果明确均已完成；原无编号收尾项首次编号；对应原执行计划 L1123 |
| CLOSE-04 | HISTORY | [completed] | cron 配置只保留文件，不安装、不启用、不调用外部服务。；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原四项任务；源退役清单要求切换/备份及独立验证先通过 | 原独立Validator、切换回滚、精确退役与未启用cron记录；不重跑；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：cron 配置只保留文件，不安装、不启用、不调用外部服务。；源已执行与最终结果明确均已完成；原无编号收尾项首次编号；对应原执行计划 L1126 |

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
| ISSUE-L1216 | 原要求/观察/裁决逐条记录；见本行源原文，不将规则或下一动作当发生事实 | 原行未单列修法则不推断；全部尝试/动作保留于右列及原上下文 | 原行未给统一累计值；保留原次数表述，不置0或按索引条数计次数 | &#124; 2026-08-15 / runtime-skill-contracts-v1 &#124; 完成六个 Skill 的公共信封、精确操作、输入输出、失败、幂等及每日/周日串行关系 &#124; 全新 Validator &#124;；原件L1216 |
| ISSUE-L1217 | 原要求/观察/裁决逐条记录；见本行源原文，不将规则或下一动作当发生事实 | 原行未单列修法则不推断；全部尝试/动作保留于右列及原上下文 | 原行未给统一累计值；保留原次数表述，不置0或按索引条数计次数 | &#124; 2026-08-15 / contract-validation &#124; 修正模板职责、备份类型、raw unresolved 绑定、失败码和两阶段报告落库歧义；第三位全新高风险 Validator 最终 PASS &#124; 等待用户批准实施分解 &#124;；原件L1217 |

## 历史目标与原编号索引

下文仅引用当时目标，不是现行规范或可运行示例；已经被新方案替代的业务不复活。原阶段/任务已在上表逐项迁移；原早期状态与最终范围不同的映射依据逐项标明，不借迁移扩大历史完成范围。

> 当前已确认的完整顶层目标为：
>
> ```text
> source/
> ├── AGENTS.md
> ├── requirements.txt
> ├── config.json
> ├── goal.module.md
> ├── goal.md
> ├── credentials.json
> ├── gcp-oauth.keys.json
> ├── templates/
> │   ├── fixed/
> │   │   ├── daily_report.html
> │   │   └── weekly_report.html
> │   └── open-report/
> │       ├── daily_report.html
> │       └── weekly_report.html
> ├── skills/
> │   ├── README.md
> │   ├── _shared/                 # 内部公共状态/校验库，不是 Skill
> │   ├── garmin-sync/
> │   ├── training-coach/
> │   ├── garmin-training-sender/
> │   ├── weekly-fitness-summary/
> │   ├── gmail-sender/
> │   └── training-report-publisher/
> └── state/
>     ├── trainlab.db
>     ├── trainlab.lock
>     ├── backups/sqlite/
>     ├── recovery-quarantine/
>     └── raw/
>     │   └── garmin/
>     │       ├── health/
>     │       │   ├── .gitkeep
>     │       │   └── <YYYYMMDD>-<resource>-<content-hash>.json
>     │       └── activities/
>     │           ├── .gitkeep
>     │           ├── <YYYYMMDD>-<activity-hash>.fit
>     │           ├── <YYYYMMDD>-<activity-hash>.gpx
>     │           ├── <YYYYMMDD>-<activity-hash>.tcx
>     │           └── <YYYYMMDD>-<activity-hash>.weather.json
> ```
>
> 未来 Provider 使用相同的“Provider 平级”原则，但不要求拥有与 Garmin 相同的子目录。

原阶段/任务及其结果见上表，原问题及计数见问题记录；额外来源标识仍可在迁移清单中检索，原件供逐行核对。

## 原任务定义与验收

本节承接原任务定义的全部内容，而非仅保留状态摘要或指向压缩包。上表每个原任务的输入输出/错误边界及检查方法均关联本节；原文有同编号专属标题时另外关联该精确段落，公共目标/范围/合同与其他定义完整保留在本节。不得把原表中的“已接入/PASS”当作完整定义。

**适用性：全部引文均属于该历史任务的原目标、合同修订和执行记录，不是当前开发协议、可运行示例或新的业务授权。** 多版本材料按原任务编号、版本和日期定位，不把后续规则回套早期结果。旧流程/命令/目录和“当前”措辞只描述原记录时点；根AGENTS是唯一现行协作规则，暂停/取消按本文件的新检查点处理，不恢复旧产品。

为保留可核查语义，原件按标题和源行完整投射为引用块；只增加引用前缀，并将旧Markdown导航链接显示为“原定位”文字，未更改原件。原字节/原哈希由history.zip及history-manifest.json证明，不把显示投射声称为原字节。全部源行连续覆盖，原始执行/协调记录也标为历史数据，不混入当前阶段状态。

### 原定义-L1

来源标题：原文导言；原件L1–L11。

> # 需求草案：source 运行结构、Skills 与 state 数据整理
>
> - 状态：`completed`
> - 负责人：主协调 Agent
> - Roadmap ID：`ADHOC-0011`
> - 阶段/子项目：`不适用`
> - Batch ID：`不适用`
> - 返工来源：`无`
> - 开始日期：2026-08-15
> - 最后更新：2026-08-16
>

### 原定义-L12

来源标题：文档用途；原件L12–L17。

> ## 文档用途
>
> 本文件记录用户确认的目标需求、六表 SQLite 合同、六个运行 Skills 及其可恢复迁移顺序。
> 用户已批准按本文的 ADHOC-0011 实施；执行严格串行，先建立新运行骨架和仓库外 candidate，
> 再归档旧 state 并原子切换。任何 Garmin/Gmail/Sites/cron 外部动作仍留在本次非目标内。
>

### 原定义-L18

来源标题：当前执行检查点；原件L18–L57。

> ## 当前执行检查点
>
> - `ADHOC-0011-0001` 已完成：保护提交 `9130461`，未包含私有 state、凭据或 `data-backup/`。
> - `ADHOC-0011-0002` 已验证通过：`source/AGENTS.md`、六个 Skills、两套模板、共享 SQLite
>   工具、`goal.md`/`goal.module.md` 已建立；goal 私有值只保留在 `goal.md`，模板字段与其
>   标题及字段标签一致。
> - `ADHOC-0011-0003` 已重建最新 r22 candidate，位于
>   `/Volumes/DiskOther/Code/trainlab-adhoc0011-candidate-r22.tB7ub1`；候选包含 512 条 activity inventory、
>   9,336 个 raw 文件索引，SQLite v1 六表、STRICT、完整性、外键、追加修订、精确批准范围、
>   外部动作语义/状态机和跨表绑定检查通过，Provider 调用为零；已生成符合命名合同、包含最高
>   ID/raw 聚合/code+Skill 摘要的 pre-change SQLite 备份与 manifest。candidate DB SHA-256 为
>   `ecb80354952855a980ad48d369ccbe291ea2190cd048c9cd9e9f94191f40a1ec`，migration manifest SHA-256 为
>   `9abcfa04b828624b41c23b593d5abfc7dd4bae0f774eb2664abb0f85c3cf369d`；备份 SHA-256 为
>   `e8bc6dc80a22883a8f53cace789b8e52f2812e725fdf05fd488d0de2fe7265e0`，manifest SHA-256 为
>   `84e0ca1c5ba0081a48c929b4cfd646830453b7cd0e9e83a4ef231ce2148a6226`；候选及备份旁车文件已清理，
>   并由 r23 独立 Validator 复核通过。
> - 独立 Validator r23 已对 r22 candidate 给出 `PASS`：六表/约束、raw 闭包、权限、备份配对、
>   中性模板渲染、Skill 测试、Ruff、format、mypy、cron/schema、编译和漂移检查均通过；未调用
>   外部服务。`ADHOC-0011-0003` 已验证通过。
> - 历史检查点：`ADHOC-0011-0004` 当时进入 active，随后执行了无外部调用的 writer 冻结、旧
>   `source/state` 可恢复归档、candidate 原子切换和切换后独立验证；旧 state、旧源码和旧配置在
>   切换验证完成前均保留。
> - 独立 Validator r23 已完成切换前复核并给出 `PASS`。随后执行操作
>   `adhoc0011-cutover-20260815T165449Z`：旧 `source/state` 已原样归档到
>   `data-backup/adhoc0011-cutover-20260815T165449Z/old-source-state`，r22 candidate state
>   已原子移入 `source/state`。切换收据位于同一归档目录，阶段已推进为 `old_runtime_layer_archived`；新数据库和配对备份
>   SHA-256 分别为 `ecb80354952855a980ad48d369ccbe291ea2190cd048c9cd9e9f94191f40a1ec` 与
>   `e8bc6dc80a22883a8f53cace789b8e52f2812e725fdf05fd488d0de2fe7265e0`。
> - 历史检查点：切换后 `verify_state.py` 与只读 `restore_state.py` 均通过，active state 无 WAL/SHM、
>   权限和路径边界保持通过；正式旧 state 仍在 data-backup，可回滚。当时的后续动作是交由全新
>   独立 Validator 复核切换结果，旧源码层退役在该复核通过后进行。
> - 切换后独立 Validator 已给出 `PASS`。随后旧 `source/config` 与 `source/logs` 已归档到本次
>   operation 目录，旧 `source/src`、`source/tests`、`source/scripts`、`source/tools`、
>   `source/typings`、`source/index.py`、旧项目文件和旧产品文档已从产品树精确移出，并保留在
>   `data-backup/adhoc0011-cutover-20260815T165449Z/retired-source-layer/` 作为回滚材料；新
>   `source/AGENTS.md`、Skills、模板、requirements、config.json、goal 文件和新 state 未移动。
> - 旧运行层退役后的全新独立 Validator 已给出 `PASS`：根目录白名单、Skills/模板、active state、
>   raw 闭包、备份恢复、Git 忽略、缓存清理、CI/README/AGENTS/memory 一致性和全部聚焦门均通过。
>   `ADHOC-0011-0004` 已完成；本计划可归档。
>

### 原定义-L58

来源标题：已确认需求；原件L58–L59。

> ## 已确认需求
>

### 原定义-L60

来源标题：R-001：按数据来源保留 Provider 层；原件L60–L76。

> ### R-001：按数据来源保留 Provider 层
>
> - `source/state/raw/` 继续作为原始来源证据根目录。
> - 保留 `source/state/raw/garmin/` 以及其中全部有效数据。
> - “保留”包含两层：active candidate 只复制本计划 R-008/R-019 明确纳入的六类健康 raw、活动
>   原始文件与天气；其余历史 Garmin raw 不删除，随旧 state 原样进入 `data-backup` 归档，仍可
>   在以后单独批准的重建中使用。active state 的裁剪不等于历史字节删除。
> - 未来接入其他数据源时，与 Garmin 平级建立独立目录：
>
> ```text
> source/state/raw/
> ├── garmin/
> └── <future-provider>/
> ```
>
> - 不把 Garmin 数据直接搬到 `source/state/garmin/`；`raw` 和 Provider 两层语义都保留。
>

### 原定义-L77

来源标题：R-002：移除非 Provider 命名空间；原件L77–L86。

> ### R-002：移除非 Provider 命名空间
>
> - active state 最终不再保留以下目录：
>   - `source/state/raw/backup/`
>   - `source/state/raw/gmail/`
>   - `source/state/raw/legacy/`
> - 本条只确定目标目录状态，不在当前阶段决定其中数据如何归档、迁移或删除，也不提前决定
>   需要联动调整哪些代码和工作流。
> - 任何 Garmin 原始数据都不得因为目录整理而丢失或被改写。
>

### 原定义-L87

来源标题：R-003：把运动活动文件与天气平铺归为一组；原件L87–L116。

> ### R-003：把运动活动文件与天气平铺归为一组
>
> - 当前 Garmin 下分散的 FIT、GPX、TCX 文件统一归入“运动活动文件”目录。
> - 目标结构使用 `activities`，而不是 `sports` 或 `fitness`；FIT、GPX、TCX 不再各自
>   建立子目录，而是直接存放在 `activities/`：
>
> ```text
> source/state/raw/garmin/
> ├── health/
> └── activities/
>     ├── 20260815-<activity-hash>.fit
>     ├── 20260815-<activity-hash>.gpx
>     ├── 20260815-<activity-hash>.tcx
>     └── 20260815-<activity-hash>.weather.json
> ```
>
> - 推荐 `activities` 的原因：FIT、GPX、TCX 都是单项运动活动的文件格式；`fitness` 容易与
>   心率、睡眠、压力等日常健康数据混淆，`sports` 也无法准确表达 Garmin 的 Activity
>   业务对象。
> - 文件名需求为 `<运动日期 YYYYMMDD>-<活动关联哈希>.<fit|gpx|tcx>`。
> - 同一项活动的 FIT、GPX、TCX 应使用相同的活动关联哈希，以便按文件名识别它们属于同一
>   项活动。
> - 活动关联哈希与文件内容 SHA-256 是两个概念：三种格式的内容不同，文件内容哈希通常也
>   不同；每个文件仍需独立保留内容 SHA-256，用于完整性和原始字节校验。
> - 活动关联哈希的具体输入、算法和历史数据兼容方式，留到后续分析阶段决定。
> - FIT、GPX、TCX 的原始字节、来源和关联关系必须保留；本需求只改变未来目标分类，不授权
>   现在移动文件。
> - `activity_weather` 属于活动附属证据，不属于健康数据。天气文件与对应活动使用相同的
>   activity hash，文件自身的完整 SHA-256 仍单独记录。
>

### 原定义-L117

来源标题：R-004：把健康 raw 平铺到独立目录；原件L117–L137。

> ### R-004：把健康 raw 平铺到独立目录
>
> - Garmin 健康原始响应统一存放于 `source/state/raw/garmin/health/`，不再使用语义混杂的
>   `json/` 目录。
> - `health/` 不按资源建立子目录，健康 JSON 直接平铺。
> - 文件名需求为 `<数据日期 YYYYMMDD>-<资源类型>-<内容哈希前缀>.json`，例如：
>
> ```text
> 20260815-sleep-<content-hash>.json
> 20260814-heart-rates-<content-hash>.json
> 20260814-rhr-<content-hash>.json
> 20260815-hrv-<content-hash>.json
> ```
>
> - 数据日期使用该健康事实的归属日期；跨夜主睡眠使用醒来日期。
> - 文件名中的哈希来源于该文件的实际内容；数据库仍保存完整 SHA-256、资源类型、归属日期
>   和来源关联。
> - 明确补采后若响应内容变化，产生新的内容哈希文件，不覆盖旧文件。
> - 文件名必须显式包含资源类型，确保数据库丢失时仍能仅凭 health raw 识别资源并重建健康
>   事实。
>

### 原定义-L138

来源标题：R-005：Activity Inventory 只作为数据库控制状态；原件L138–L147。

> ### R-005：Activity Inventory 只作为数据库控制状态
>
> - `activity_inventory` 是采集程序用于发现和关联活动的控制状态，不属于健康数据或运动
>   内容，不建立 `collection/` 或其他 raw 目录。
> - 正常每日同步只查询昨日范围一次，用于发现新活动；不自动回查更早历史，也不根据
>   Provider 清单中的缺席自动删除本地活动。
> - 数据库中的 inventory 状态至少表达活动 ID、活动日期、activity hash、采集状态和最后
>   采集时间；具体 Schema 留到后续分析阶段。
> - inventory 控制状态允许在数据库重建时重新初始化，不作为健康或运动事实的重建来源。
>

### 原定义-L148

来源标题：R-006：取消 Activity Summary 依赖；原件L148–L155。

> ### R-006：取消 Activity Summary 依赖
>
> - 未来正常采集不再请求、保存或依赖 `activity_summary`。
> - 活动事实只从 FIT、GPX、TCX 原始文件确定性解析；inventory 只负责发现活动和绑定原始
>   文件。
> - 没有原始活动文件或原始文件不足以重建必要事实时，将该活动标记为不完整，不使用
>   Garmin Summary 补齐，也不猜测缺失字段。
>

### 原定义-L156

来源标题：R-007：每日一次、无历史回读的同步窗口；原件L156–L171。

> ### R-007：每日一次、无历史回读的同步窗口
>
> - 同步时间固定为项目主体本地时间每日 `12:00`。
> - 设同步执行日为 `D`，正常同步只获取：
>   - `D-1` 本地自然日已经结束的活动和非睡眠健康数据；
>   - 在 `D` 当天早晨已经结束的唯一主睡眠。
> - 不获取 `D` 当天仍在变化的白天健康数据或未结束数据。
> - 跨夜主睡眠以醒来日归属：例如 8 月 14 日晚至 8 月 15 日早的睡眠，数据归属日为
>   8 月 15 日；日报显示为“14 日晚至 15 日早的昨夜睡眠”。
> - 取消默认 incremental 的最近 14 日自动回读；正常定时同步不得自动向更早历史日期
>   扩展，也不得以重叠窗口反复请求已经完成的数据。
> - 某日数据不完整时只记录并报告该日期需要补数，不自动重新请求。只有用户明确指定补数
>   日期并批准后，才允许重新获取该日期。
> - 本条只确定同步时间、数据日期边界和禁止自动补数的产品需求；相关依赖、实现入口、失败
>   处理和迁移方式留到后续分析阶段。
>

### 原定义-L172

来源标题：R-008：重置现有非 raw state；原件L172–L188。

> ### R-008：重置现有非 raw state
>
> - 当前 `source/state/` 下除 `source/state/raw/` 及其全部内容以外的现有文件和目录，均视为
>   旧系统运行状态，未来重构时全部删除。
> - 删除范围明确包括当前数据库及其伴随文件，以及现有运行收据、manifest、锁、缓存、候选
>   状态、报告和其他派生运行产物；不把旧数据库内容迁入新数据库。
> - 本条不授权删除或改写 `source/state/raw/` 中的任何内容。raw 内部的 Provider、health、
>   activities、backup、gmail 和 legacy 目标分别由本计划其他需求约束，和本次非 raw state
>   重置互不替代。
> - 删除旧 state 后，未来系统可以重新创建新的数据库和必要控制状态；因此本需求描述的是
>   一次旧状态重置，不表示 `source/state/` 永久只能包含 `raw/`。
> - 新数据库不建立健康、睡眠或活动业务事实表；未来分析所需的有界证据只能由确认保留并
>   完成整理的 health raw 与 activity 原始文件按需解析。新数据库只重新建立 raw 索引、
>   `activity_inventory` 等程序控制状态，并从新系统开始保存 Skill 输出和运行状态。
> - 本条目前只确认删除边界和重建原则，不分析删除顺序、备份、回滚、停机、Schema、工具或
>   执行条件，也不授权现在删除任何 state 内容。
>

### 原定义-L189

来源标题：R-009：运行时改为完全由 AI 与本地 Skills 驱动；原件L189–L201。

> ### R-009：运行时改为完全由 AI 与本地 Skills 驱动
>
> - `source/` 未来不再保留传统集中式 Python 产品包、统一 CLI 或旧运行 Harness；AI 读取
>   `source/AGENTS.md` 后，按任务触发 `source/skills/` 中的本地 Skill。
> - 运行实现、Schema、引用资料和自测可按需放在各自 Skill 目录内，不再建立集中式
>   `source/src/`、`source/tests/`、`source/scripts/` 或 `source/tools/`。
> - 当前 `source/index.py`、`source/pyproject.toml`、`source/requirements.lock`、旧产品代码、
>   旧运行 Harness 及其他未列入目标结构的内容，均列为未来重构时的退役候选。
> - 该方向接受 `source/` 在迁移中暂时不可运行；只有新 Skills、数据重建和验证合同具备后，
>   才确认旧运行实现可以删除。
> - 仓库根 agentForge 开发 Harness 继续负责开发治理；`source/AGENTS.md` 只负责产品运行，
>   不得替代或弱化根规则。
>

### 原定义-L202

来源标题：R-010：最小 source 顶层结构；原件L202–L226。

> ### R-010：最小 source 顶层结构
>
> - 未来 `source/` 顶层只保留以下运行必需类别：
>
> ```text
> source/
> ├── AGENTS.md
> ├── requirements.txt
> ├── config.json
> ├── goal.module.md
> ├── goal.md                         # 私有，Git 忽略
> ├── credentials.json                # 私有，Git 忽略
> ├── gcp-oauth.keys.json             # 私有，Git 忽略
> ├── skills/
> ├── templates/
> └── state/                           # 私有数据，Git 忽略内容
> ```
>
> - `requirements.lock` 退役，使用唯一 `requirements.txt`；具体依赖等各 Skill 设计稳定后再定，
>   已知直接依赖优先固定精确版本。
> - `config.json` 只记录用户不参与、且不会改变训练分析结论的系统参数；不得保存秘密、用户
>   目标、训练偏好或健康事实。
> - 两份凭据文件只允许本机私有保存，保持 owner-only 权限，不得进入 Prompt、日志、模板、
>   Git 或任何报告。
>

### 原定义-L227

来源标题：R-011：goal 与 state 的 Git 表达；原件L227–L245。

> ### R-011：goal 与 state 的 Git 表达
>
> - 私有 `source/goal.md` 和 `source/state/**` 全部由 Git 精确忽略。
> - 提供可跟踪的 `source/goal.module.md`，只包含中文填写说明和无个人信息的示例占位，不得
>   预填用户真实健康、比赛或训练数据。
> - `goal.md` 使用中文自然语言表达训练目标、可训练日期、攀岩安排、限制、恢复关注点和偏好。
> - 训练强度偏好使用 `1–5` 档并写明各档含义；它只影响计划保守程度，不得覆盖恢复证据、
>   疼痛红旗或其他安全规则。
> - 使用反向 ignore 规则只跟踪 state 的空目录占位；至少保留：
>
> ```text
> source/state/raw/garmin/
> ├── health/.gitkeep
> └── activities/.gitkeep
> ```
>
> - `.gitkeep` 只表达目标目录，不包含数据；未来其他 Provider 可用相同方式增加被批准的空目录
>   骨架。
>

### 原定义-L246

来源标题：R-012：六个初始本地 Skills；原件L246–L311。

> ### R-012：六个初始本地 Skills
>
> - `source/skills/README.md` 是运行 Skill 索引，只列名称、用途、触发条件、读取范围、写入范围
>   和外部副作用。
> - 每个 Skill 使用独立目录和 `SKILL.md`；实现脚本、Schema、引用资料和自测仅在需要时放入
>   对应 Skill 内。
> - 初始 Skill 精确为：
>
> ```text
> source/skills/
> ├── README.md
> ├── garmin-sync/SKILL.md
> ├── training-coach/SKILL.md
> ├── garmin-training-sender/SKILL.md
> ├── weekly-fitness-summary/SKILL.md
> ├── gmail-sender/SKILL.md
> └── training-report-publisher/SKILL.md
> ```
>
> - `garmin-sync`：基于本地 Garmin MCP 服务工作。它读取后续 SQLite 中的采集状态，按已确认
>   日期边界增量获取 activities 与 health 数据，分别写入已规划的 raw 目录，并同步记录采集
>   状态，供缺口识别、去重和 `training-coach` 后续按需解析使用。
> - `garmin-sync` 的“增量”表示依据数据库状态只获取尚未完成的目标日期或活动；正常同步仍不
>   自动回读历史，补数必须由用户明确指定。
> - `garmin-sync` 只索引 raw 文件与采集状态，不把 health 或 activities 清洗成数据库业务事实。
> - `training-coach`：定位为类似 “Course Coach” 的教练 Skill。它接受统一输入合同，调用方可以
>   是用户，也可以是运行中的 AI；输入可以包含自然语言要求、`goal.md` 以及已批准提供的健康、
>   恢复和活动证据，并必须标明输入来源。
> - `training-coach` 自带确定性脚本，按任务日期读取需要的 health JSON、FIT、GPX、TCX 和天气
>   JSON，输出有界的结构化证据给 AI；不得把完整大型 raw 或二进制文件直接放进 AI 上下文。
> - 每日模式正常输入为当前新增 raw 的脚本解析结果，以及 SQLite 中此前 14 份日总结；不得为了
>   正常日报重新解析过去 14 天 raw。
> - 每周模式正常输入为当前周期的 7 份日总结，以及 SQLite 中此前 4 份周总结；不得为了正常
>   周报重新解析过去 4 周 raw。
> - 只有总结缺失、数据矛盾、需要总结未保存的详细指标、需要复核某项 FIT，或用户明确要求时，
>   才由脚本定向读取对应历史 raw；不得无条件全窗口重算。
> - `training-coach` 提供两个运行模式：每日模式输出昨日健康、运动与昨夜睡眠总结；每周模式
>   输出一周总结以及下一周期的跑步、攀岩和休息课表。课表包含目的、剂量、强度、执行说明、
>   降级条件和停止条件。
> - `training-coach` 不承担 Garmin 数据同步、原始文件清洗、Gmail 发送或 Garmin 写入。
> - 输入中的单周临时调整可以进入本次课表，但不得自动改写长期 `goal.md`。
> - 课表可以通过两种批准路径进入 `garmin-training-sender`：用户直接审核批准；或已由用户预先
>   授权的定时 AI，依据固定输入、训练安全规则和确定性校验完成审核批准。普通、临时或没有
>   对应预授权的 AI 调用不得自行批准 Garmin 写入。
> - `weekly-fitness-summary`：由 `training-coach` 每周模式按需使用，正常读取本周期 7 份日总结
>   与此前 4 份周总结完成跑步、攀岩和恢复趋势分析；只有信息不足时才通过 `training-coach`
>   脚本定向读取 raw。本地版本不得依赖 Garmin `activity_summary` 或在线详情接口。
> - `garmin-training-sender`：在用户直接批准，或预授权的定时 AI 已按固定规则批准后，才可调用
>   Garmin MCP；先形成确定性课程合同，再进行幂等检查、写入和回读验证。
> - `training-coach` 本身只生成总结与课表结果；调用它的 AI 流程负责记录批准来源，并在批准
>   成立时把课表交给 `garmin-training-sender`。定时运行不要求用户逐次重复确认，但必须落在
>   用户预先批准的自动运行范围内。
> - `gmail-sender`：基于本地、已配置的精确 `gmail` MCP 绑定读取和发送邮件。它负责邮件收取、
>   查询、内容交接以及获授权后的发送，不负责生成训练事实或课表，也不得在缺少有效认证、
>   收件边界或发送授权时自行回退到其他传输方式。
> - `training-report-publisher`：只把已通过结构和安全校验的日报、周报和课表转换为阅读产物，
>   不生成或修改训练事实。它提供 `open_report` 与 `fixed_email` 两种模式；前者默认采用已安装
>   Data Analytics 插件的 `$data-analytics:build-report` 构建开放式报告，后者沿用 TrainLab
>   固定邮件模板。两种模式最终都必须生成可由 `gmail-sender` 发送的邮件安全 HTML。
> - `garmin-training-sender` 与 `weekly-fitness-summary` 以用户点名的现有全局 Skill 及其引用规范
>   为适配来源；全局原件不修改、不覆盖、不移动，本地版本按 TrainLab 的 raw-first 数据边界
>   重新编写。
> - 两个来源 Skill 对“配速上限/下限”的文字定义目前互相相反；本地合同必须改用无歧义的
>   数值字段（较快边界、较慢边界或每公里秒数），并由展示层和 Garmin 映射层分别渲染，禁止
>   沿用歧义。
>

### 原定义-L312

来源标题：R-013：Skill 采用脚本优先；原件L312–L329。

> ### R-013：Skill 采用脚本优先
>
> - 能稳定定义输入、输出和错误码的重复工作优先实现为各 Skill 自己的 `scripts/`，避免 AI 在
>   每次运行时重新生成代码或展开大量中间数据。
> - `SKILL.md` 保持简短，只描述触发条件、输入输出、脚本调用顺序、权限边界和失败处理；详细
>   Schema、MCP 字段说明和领域资料按需放入 `references/`，模板等输出资产放入 `assets/`。
> - 脚本优先覆盖：文件命名与哈希、增量差集、SQLite 状态读写、按需解析 raw、确定性课程合同、
>   报告渲染、幂等检查和脱敏结果摘要。
> - MCP 实际能力必须以当前本地服务为准；若某个 MCP 动作没有稳定的脚本调用接口，则由 AI
>   调用 MCP，脚本只负责调用前验证与调用后整理，不伪造接口。
> - 脚本输出使用有界、结构化、可校验的数据，避免把 raw 健康内容、完整 FIT 样本或邮件正文
>   大量放入 AI 上下文，以减少 Token 使用并保护隐私。
> - 每个脚本都必须与所属 Skill 一起验证；禁止把脚本散落回 `source/scripts/` 或
>   `source/tools/`。
> - canonical JSON、SQLite 状态/备份、摘要、权限与通用 Schema 校验可以共享一份内部实现，
>   放入 `source/skills/_shared/`。该目录不得含 `SKILL.md`，不是可触发 Skill，也不得承载任何
>   训练、Garmin、Gmail 或报告业务判断。
>

### 原定义-L330

来源标题：R-014：source 运行 AGENTS；原件L330–L339。

> ### R-014：source 运行 AGENTS
>
> - `source/AGENTS.md` 至少引用 `goal.md`、`config.json` 和 `skills/README.md`，并说明缺少私有
>   goal 或凭据时如何安全停止和引导用户。
> - 运行硬规则至少包含：Hansons 训练原则、Easy 与 SOS 区分、跑步与攀岩统一计入负荷、硬课
>   间隔、错过质量课不补偿、恢复与安全优先、疼痛/胸痛/晕眩等红旗停止条件。
> - AI 只能在安全边界内解释与提出计划；确定性安全验证不得被自然语言偏好覆盖。
> - `source/AGENTS.md` 必须明确服从仓库根开发治理，不能授权修改代码、泄露秘密、调用外部
>   服务或执行数据写入。
>

### 原定义-L340

来源标题：R-015：两套日报与周计划邮件模板；原件L340–L357。

> ### R-015：两套日报与周计划邮件模板
>
> - `source/templates/fixed/` 保存当前固定样式：
>   - `fixed/daily_report.html`
>   - `fixed/weekly_report.html`
> - 固定样式初次迁移直接保留当前模板字节和视觉样式，不做重新设计。当前基线摘要为：
>   - `daily_report.html`：`ae984077103216364b7fa6ed3feaaad82175f62b7c31210fa9664b305437db52`
>   - `weekly_report.html`：`86eb5f3b221a29e8f70132aa08e541f55a4445a4fbee1ecc543276fb800a5263`
> - `source/templates/open-report/` 保存 Data Analytics 报告转邮件时使用的本地安全外壳：
>   - `open-report/daily_report.html`
>   - `open-report/weekly_report.html`
>   该外壳允许正文结构更开放，但只负责邮件兼容、视觉一致性和安全过滤，不复制插件实现。
> - 模板只负责展示，不保存健康事实、目标、地址、凭据或发送状态。
> - `training-coach` 的每日和每周模式只产生已验证的 JSON 与纯文本；
>   `training-report-publisher` 选择并填充对应模板、生成报告与邮件 HTML；`gmail-sender` 只负责
>   获授权后的实际发送。
> - 模板存在不代表自动获得邮件发送权限；定时流程必须使用已记录的自动运行授权。
>

### 原定义-L358

来源标题：R-020：两套报告展示路径与可选 Sites 快照；原件L358–L375。

> ### R-020：两套报告展示路径与可选 Sites 快照
>
> - `training-report-publisher` 负责两套互不混合的展示路径：
>   - `open_report`：当前默认。以 `training-coach` 已验证的结构化输出为唯一事实输入，调用
>     `$data-analytics:build-report` 形成开放式、证据优先的完整报告，再转换为邮件友好的 HTML。
>   - `fixed_email`：兼容路径。使用 `source/templates/fixed/daily_report.html` 或
>     `source/templates/fixed/weekly_report.html` 生成固定样式邮件。
> - `$data-analytics:publish-artifact-to-sites` 只负责把已经验证的 Data Analytics 报告快照发布到
>   Sites，不负责生成报告，也不是默认邮件渲染步骤。只有用户明确要求，或以后存在覆盖该动作的
>   有效定时预授权时，才允许发布 Sites；本次创建 Skill 不发布任何站点。
> - `open_report` 的邮件版必须是静态、自包含、适合常见邮件客户端阅读的 HTML；不得依赖
>   JavaScript、远程交互组件或 Sites 页面才能显示正文。若已有获准的 Sites 快照，可在邮件中
>   附加链接，但邮件正文必须独立可读。
> - `training-report-publisher` 只改变表现层，不得改写训练结论、课程合同、证据、批准或安全判断；
>   `gmail-sender` 仍是唯一邮件发送 Skill。
> - 每次运行只选择一种主展示模式，禁止把两套正文拼接成一封邮件。选用模式、模板/报告版本、
>   输入输出摘要和可选 Sites 结果都必须进入 SQLite。
>

### 原定义-L376

来源标题：R-016：无状态定时运行原则；原件L376–L387。

> ### R-016：无状态定时运行原则
>
> - 每次 `cron + codex exec` 都视为全新、无上下文运行；先读取 `source/AGENTS.md`、
>   `config.json`、`goal.md`、对应 Skill 和 SQLite 状态，不依赖历史聊天或上一次 AI 记忆。
> - 健康和活动原始证据保存为 raw 文件；课表、日报、周报、邮件内容、批准、外部动作结果及
>   成功、失败或待处理状态统一追加写入 SQLite。HTML 文件仅作为明确请求导出或预览时的派生
>   视图，不是权威状态来源。
> - 每个 Skill 结束前都必须把成功、失败或待处理结果写入 SQLite；下次运行只依据 raw 文件、
>   `source/AGENTS.md`、`config.json`、`goal.md`、Skill 定义和 SQLite 持久状态继续。
> - Garmin 与 Gmail 操作前先检查 SQLite 是否已完成，操作后记录 Provider 标识和结果，防止
>   重复创建 Workout、重复排期或重复发送邮件。
>

### 原定义-L388

来源标题：R-017：两个 cron Prompt；原件L388–L432。

> ### R-017：两个 cron Prompt
>
> - 时区固定为 `Asia/Hong_Kong`。cron 只保存短 Prompt，完整流程继续由
>   `source/AGENTS.md` 与各 Skill 定义。
> - 每日 `12:00` 执行昨日总结，顺序固定为：
>
> ```text
> garmin-sync → training-coach（每日模式）→ training-report-publisher → gmail-sender
> ```
>
> - 每日内容只包含昨日已经结束的健康与运动，以及昨日晚上至今日早晨、按醒来日归属的主睡眠。
> - 每日 cron Prompt 目标文本为：
>
> ```text
> 按 source/AGENTS.md 执行每日总结流程。依次使用 garmin-sync、training-coach 每日模式、
> training-report-publisher 和 gmail-sender；只处理昨日完整健康与运动以及今日早晨已结束的主睡眠；由 training-coach
> 脚本解析当前新增 raw，并结合 SQLite 中前 14 份日总结生成结果；把所有 Skill 输出写入
> SQLite，禁止重复采集、无条件重算历史 raw 或重复发送。
> ```
>
> - 每周日 `12:30` 执行周总结和下周期课表，顺序固定为：
>
> ```text
> garmin-sync → training-coach（每周模式，按需使用 weekly-fitness-summary）
> → garmin-training-sender → training-report-publisher → gmail-sender
> ```
>
> - 周日中午只使用已经完整落地的七个每日证据单元；最后一个单元包含周六完整健康与运动、
>   以及周六晚上至周日早晨的主睡眠。不得把尚未结束的周日白天数据伪装成完整周数据。
> - `training-coach` 正常使用本周期 7 份日总结和此前 4 份周总结；按需调用
>   `weekly-fitness-summary` 完成趋势分析，最后输出周总结和课表。只有摘要缺失、矛盾或缺少
>   必要细节时才定向解析对应 raw。
> - 每周 cron Prompt 目标文本为：
>
> ```text
> 按 source/AGENTS.md 执行每周总结与排课流程。依次使用 garmin-sync、training-coach 每周模式、
> garmin-training-sender、training-report-publisher 和 gmail-sender；training-coach 使用本周期 7 份日总结与此前 4 份
> 周总结，按需使用 weekly-fitness-summary，只有缺少必要信息时才定向读取 raw；按预授权定时
> AI 规则审核课表，安全替换本项目的 GTS Workout 并排入日历，最后发送包含实际 Garmin 执行
> 结果的周邮件；所有输出和状态必须写入 SQLite。
> ```
>
> - 上述“同时调用”表示在同一个 cron 工作流中依次执行，不表示并行。Garmin 写入与回读验证
>   先完成，周邮件后发送，以便邮件准确反映实际排期结果。
>

### 原定义-L433

来源标题：R-018：管理 Garmin My Workouts 中的 GTS 模板；原件L433–L445。

> ### R-018：管理 Garmin My Workouts 中的 GTS 模板
>
> - 本需求中的 Workout 指 Garmin Connect “My Workouts” 课程模板库中的记录，例如
>   `Easy-6KM-GTS`，不是已完成的运动活动，也不是健康数据。
> - 本地 `garmin-training-sender` 继续使用名称末尾精确 `-GTS` 作为项目标识，不改为
>   `-TrainLab`；SQLite 另外记录 Garmin Workout ID，形成名称和 ID 双重归属证明。
> - 每周替换顺序为：读取 My Workouts 与相关日历范围；解除旧 GTS Workout 尚未执行的未来
>   排期；删除确认属于本项目的旧 GTS 模板；创建新 GTS 模板；回读验证结构；添加到新日历。
> - 删除只针对名称精确以 `-GTS` 结尾且归属已确认的 My Workouts 模板。不得删除已完成运动
>   历史、非 GTS Workout，或仅在名称中间出现 `GTS` 的记录。
> - 用户对定时周流程的预授权包含上述 GTS 清理、重建和排期，因此预授权的定时 AI 不需要每周
>   再次请求人工确认；不在自动授权范围内的临时调用仍不得删除或写入 Garmin。
>

### 原定义-L446

来源标题：R-019：SQLite 保存所有项目输出与状态；原件L446–L475。

> ### R-019：SQLite 保存所有项目输出与状态
>
> - 新系统只使用一个主数据库：`source/state/trainlab.db`。
> - health JSON、FIT、GPX、TCX 和天气 JSON 继续只保存为原始文件，不再清洗成健康、睡眠或活动
>   业务事实表。
> - AI 不直接读取完整大型 raw；`training-coach` 的脚本按任务窗口解析所需文件，生成有界证据。
> - 所有 Skill 的最终输入摘要、输出内容和状态统一追加写入 SQLite，包括：有界证据、每日总结、
>   周总结、课表、最终邮件标题/纯文本/HTML、Garmin Workout 构建结果和运行结果。
> - 每份日总结和周总结都同时保存结构化 JSON 与人类可读的文本/HTML。结构化 JSON 必须包含
>   必要训练指标、判断结果和来源 raw ID/SHA-256，使后续总结能够直接复用并在需要时回查原始
>   证据。
> - Skill 输出不得原地覆盖；修订时插入新记录并关联被替代版本。
> - SQLite 首批表固定为六类，具体字段在下一步设计：
>   - `raw_files`：原始健康、活动和天气文件的路径、类型、日期与 SHA-256；
>   - `activity_inventory`：Garmin 活动发现、原始文件获取和完成状态；
>   - `skill_runs`：每次 Skill 的运行目标、开始结束时间和结果；
>   - `skill_outputs`：所有 Skill 的结构化 JSON、文本或 HTML 输出、摘要、版本与替代关系；
>   - `approvals`：用户或预授权定时 AI 对课表的批准记录；
>   - `external_actions`：Gmail 邮件、Garmin Workout/排期及可选 Sites 快照的幂等状态和
>     Provider ID。
> - `training-report-publisher` 必须先把实际报告及邮件主题、纯文本与 HTML 保存为
>   `skill_outputs`；`gmail-sender` 只能引用其确切 ID/SHA，禁止发送前静默改写，再由
>   `external_actions` 记录 Gmail Message ID 与发送状态。
> - `garmin-training-sender` 必须把实际使用的 Workout 合同保存在 `skill_outputs`，再由
>   `external_actions` 记录删除、创建、验证与排期结果。
> - 获准发布 Sites 时，`training-report-publisher` 必须把 canonical report 保存为
>   `skill_outputs`，再由 `external_actions` 记录 Sites 项目、版本、快照时间与发布状态。
> - `trainlab.db` 因保存无法从 raw 原样重现的 AI 输出而成为重要私有文件，必须采用 SQLite
>   一致性备份；备份位置、频率与保留数量留到实施设计阶段。
>

### 原定义-L476

来源标题：技术合同 1：SQLite 六表 Schema v1（初始设计记录；后续已实施）；原件L476–L481。

> ## 技术合同 1：SQLite 六表 Schema v1（初始设计记录；后续已实施）
>
> 以下两段记录初始设计阶段的边界：当时只设计字段和数据库内约束，不创建数据库、不迁移或读取
> 私人数据，也不提前设计备份命令或六个 Skill 的完整输入输出 Schema。后续实施已按本合同建立
> candidate 与 active state，并通过独立 Validator。
>

### 原定义-L482

来源标题：全局规则；原件L482–L495。

> ### 全局规则
>
> - 首版严格只有六张表；不增加健康、睡眠、活动、邮件、Workout、Cron、队列或 Schema
>   migration 表。Schema 版本使用 `PRAGMA user_version=1`。
> - 六表使用 SQLite `STRICT`，主键均为 `INTEGER PRIMARY KEY`；启用
>   `PRAGMA foreign_keys=ON`，所有外键采用 `ON DELETE RESTRICT`，禁止级联删除。
> - 日期为 `YYYY-MM-DD`，日历语义固定为 `Asia/Hong_Kong`；时间保存为 UTC RFC3339。
> - SHA-256 保存完整的 64 位小写十六进制；JSON 保存前规范化并通过 `json_valid()`。
> - raw 字节不进入 SQLite；数据库只保存相对路径、完整摘要、大小、关联和状态。相对路径必须
>   位于 `source/state/raw/` 内，禁止绝对路径、`..`、符号链接和越界解析。
> - 数据库按单用户、两个串行 Cron 设计，不建立多用户、通用插件、并行队列或工作流 DAG。
> - 由于只允许六张表，多来源血缘使用经过 Schema 校验的 JSON 清单保存；实施时必须提供一致性
>   检查脚本，逐项验证清单中的 raw ID/SHA 与上游 output ID/SHA。
>

### 原定义-L496

来源标题：1. `skill_runs`：每次 Skill 的运行状态；原件L496–L527。

> ### 1. `skill_runs`：每次 Skill 的运行状态
>
> 该表先创建，供其余五表引用。
>
> | 字段 | 类型/约束 | 作用 |
> | --- | --- | --- |
> | `id` | INTEGER PK | 本地运行 ID |
> | `run_key` | TEXT UNIQUE NOT NULL | 单次 Skill 调用的唯一键 |
> | `workflow_key` | TEXT NOT NULL | 同一日报、周报或人工流程的关联键 |
> | `dedupe_key` | TEXT NOT NULL | 同一逻辑工作的稳定去重键 |
> | `parent_run_id` | INTEGER NULL FK → `skill_runs.id` | 被其他 Skill 调用时的父运行 |
> | `skill_name` | TEXT NOT NULL | 六个本地 Skill 之一 |
> | `operation` | TEXT NOT NULL | 具体操作；精确枚举留给技术合同 3 |
> | `trigger_kind` | TEXT NOT NULL | `cron_daily`、`cron_weekly`、`manual`、`recovery` 或 `skill` |
> | `target_from_date` | TEXT NULL | 有界处理起始日期 |
> | `target_through_date` | TEXT NULL | 有界处理结束日期 |
> | `attempt_no` | INTEGER NOT NULL CHECK >= 1 | 同一去重键的尝试序号 |
> | `input_manifest_json` | TEXT NOT NULL, valid JSON | raw、历史输出、goal/config/AGENTS/Skill 版本摘要清单 |
> | `input_sha256` | TEXT NOT NULL | 规范化输入清单摘要 |
> | `status` | TEXT NOT NULL | `pending`、`running`、`succeeded`、`failed`、`blocked`、`interrupted` 或 `cancelled` |
> | `created_at_utc` | TEXT NOT NULL | 建立时间 |
> | `started_at_utc` | TEXT NULL | 开始时间 |
> | `heartbeat_at_utc` | TEXT NULL | 最近心跳 |
> | `lease_expires_at_utc` | TEXT NULL | 无状态 Cron 的运行租约到期时间 |
> | `finished_at_utc` | TEXT NULL | 终态时间 |
> | `error_code` | TEXT NULL | 稳定、脱敏错误码 |
> | `error_summary` | TEXT NULL | 有界、脱敏错误摘要，不保存隐藏推理或秘密 |
>
> 约束：`UNIQUE(dedupe_key, attempt_no)`；同一 `dedupe_key` 在 `pending`、`running`、
> `succeeded` 中最多一行。失败或中断后才可创建更高 `attempt_no`；过期 `running` 不得直接视为
> 失败，必须先执行恢复判断。
>

### 原定义-L528

来源标题：2. `activity_inventory`：活动发现与文件采集控制状态；原件L528–L557。

> ### 2. `activity_inventory`：活动发现与文件采集控制状态
>
> 该表不保存活动名称、距离、时长、配速、心率或其他运动事实，也不恢复旧系统的
> `suspected_missing/provider_deleted` 生命周期。
>
> | 字段 | 类型/约束 | 作用 |
> | --- | --- | --- |
> | `id` | INTEGER PK | inventory ID |
> | `provider` | TEXT NOT NULL | 首版为 `garmin` |
> | `provider_activity_id` | TEXT NOT NULL | Provider 活动 ID；数据库私有保存 |
> | `activity_hash` | TEXT NOT NULL | `SHA256(provider + NUL + provider_activity_id)` |
> | `activity_hash_version` | TEXT NOT NULL | 哈希算法合同版本 |
> | `activity_date` | TEXT NOT NULL | `Asia/Hong_Kong` 活动日期 |
> | `expected_formats_json` | TEXT NOT NULL, valid JSON | 本次预计取得的 FIT/GPX/TCX 格式清单 |
> | `collection_state` | TEXT NOT NULL | `discovered`、`collecting`、`complete`、`incomplete` 或 `failed` |
> | `weather_state` | TEXT NOT NULL | `not_requested`、`pending`、`complete`、`incomplete` 或 `not_available` |
> | `collection_policy_version` | TEXT NOT NULL | 当时判断完整性的规则版本 |
> | `first_seen_at_utc` | TEXT NOT NULL | 首次发现时间 |
> | `last_seen_at_utc` | TEXT NOT NULL | 最近一次在目标日期 inventory 中出现的时间 |
> | `last_collection_at_utc` | TEXT NULL | 最近采集尝试时间 |
> | `discovered_by_run_id` | INTEGER NOT NULL FK → `skill_runs.id` | 首次发现运行 |
> | `last_collection_run_id` | INTEGER NULL FK → `skill_runs.id` | 最近采集运行 |
> | `last_error_code` | TEXT NULL | 脱敏采集错误码 |
> | `updated_at_utc` | TEXT NOT NULL | 当前控制状态更新时间 |
>
> 约束：`UNIQUE(provider, provider_activity_id)`、`UNIQUE(provider, activity_hash)`。活动文件是否
> 存在以关联的 `raw_files` 为准；`complete` 至少要求一份通过哈希校验且可解析的 FIT、GPX 或
> TCX。天气是辅助证据，不单独阻塞活动完成。inventory 行允许更新，但每次变化必须同时产生
> 不可覆盖的 `garmin-sync` 输出摘要。
>

### 原定义-L558

来源标题：3. `raw_files`：原始文件索引与不可变修订；原件L558–L595。

> ### 3. `raw_files`：原始文件索引与不可变修订
>
> | 字段 | 类型/约束 | 作用 |
> | --- | --- | --- |
> | `id` | INTEGER PK | raw 文件 ID |
> | `provider` | TEXT NOT NULL | 数据来源 |
> | `data_class` | TEXT NOT NULL | `health` 或 `activity`；天气归入 `activity` |
> | `resource_kind` | TEXT NOT NULL | `sleep`、`hrv`、`activity_fit`、`activity_weather` 等 |
> | `logical_key` | TEXT NOT NULL | 同一逻辑证据的稳定身份 |
> | `revision_no` | INTEGER NOT NULL CHECK >= 1 | 修订序号 |
> | `supersedes_raw_file_id` | INTEGER NULL FK → `raw_files.id` | 被新内容替代的旧 raw 记录 |
> | `activity_inventory_id` | INTEGER NULL FK → `activity_inventory.id` | 活动类文件的关联；健康类必须为空 |
> | `activity_binding_state` | TEXT NOT NULL | `not_applicable`、`unresolved` 或 `bound` |
> | `bound_by_run_id` | INTEGER NULL FK → `skill_runs.id` | 后续证明活动身份并完成绑定的运行 |
> | `binding_evidence_json` | TEXT NULL, valid JSON | 只保存确定性身份字段、来源 ID/SHA 和规则版本，不保存 raw 正文 |
> | `data_date` | TEXT NOT NULL | 健康归属日、睡眠醒来日或活动日期 |
> | `relative_path` | TEXT UNIQUE NOT NULL | 相对 `source/state/raw/` 的路径 |
> | `file_format` | TEXT NOT NULL | `json`、`fit`、`gpx` 或 `tcx` |
> | `byte_size` | INTEGER NOT NULL CHECK >= 0 | 文件字节数 |
> | `sha256` | TEXT NOT NULL | 文件实际字节完整摘要 |
> | `registered_by_run_id` | INTEGER NOT NULL FK → `skill_runs.id` | 把文件登记进新库的同步或离线索引运行 |
> | `integrity_state` | TEXT NOT NULL | `verified`、`missing`、`hash_mismatch` 或 `quarantined` |
> | `captured_at_utc` | TEXT NULL | Provider 获取时间；历史 raw 无可靠证据时为空，不从 mtime 猜测 |
> | `registered_at_utc` | TEXT NOT NULL | 登记进本数据库的时间 |
> | `last_verified_at_utc` | TEXT NOT NULL | 最近完整性核验时间 |
>
> 约束：`UNIQUE(logical_key, revision_no)`、`UNIQUE(logical_key, sha256)`、
> `UNIQUE(supersedes_raw_file_id)`。健康文件可因用户明确补数产生新内容哈希与新修订；活动文件
> 若目标路径已存在，同摘要为幂等成功，不同摘要必须停止并记录冲突，禁止覆盖。新文件完成写入、
> fsync、原子改名并复核 SHA-256 后才可插入 `verified` 记录；既有 raw 只在离线索引运行完成
> 文件名、类型和哈希验证后登记；半文件不得登记。旧活动 raw 无法从文件名、日期或活动关联哈希
> 唯一证明 Provider activity ID 时，允许以 `activity_inventory_id=NULL`、
> `activity_binding_state=unresolved` 登记，不能伪造关联。只有后续独立 inventory 观察与解析结果
> 共同唯一匹配时，才能在一个受审计事务中把它一次性改为 `bound`，同时写入
> `activity_inventory_id`、`bound_by_run_id` 与 `binding_evidence_json`；已绑定记录不得自动改绑，
> 冲突时保持原值并进入 blocked。健康 raw 必须为 `not_applicable` 且三个绑定字段为空；活动 raw
> 只有 `unresolved` 或 `bound` 两种状态。该绑定不授权回读历史或调用 Provider。
>

### 原定义-L596

来源标题：4. `skill_outputs`：不可覆盖的 Skill 输出；原件L596–L625。

> ### 4. `skill_outputs`：不可覆盖的 Skill 输出
>
> | 字段 | 类型/约束 | 作用 |
> | --- | --- | --- |
> | `id` | INTEGER PK | 输出 ID |
> | `skill_run_id` | INTEGER NOT NULL FK → `skill_runs.id` | 产生该输出的运行 |
> | `output_kind` | TEXT NOT NULL | sync 摘要、有界证据、日报、周报、课表、报告、邮件渲染、Workout 合同或执行摘要 |
> | `logical_key` | TEXT NOT NULL | 输出的稳定身份 |
> | `revision_no` | INTEGER NOT NULL CHECK >= 1 | 修订序号 |
> | `supersedes_output_id` | INTEGER NULL FK → `skill_outputs.id` | 被替代的旧修订 |
> | `period_start_date` | TEXT NULL | 内容周期起点 |
> | `period_end_date` | TEXT NULL | 内容周期终点 |
> | `schema_name` | TEXT NOT NULL | 结构化合同名称 |
> | `schema_version` | TEXT NOT NULL | 结构化合同版本 |
> | `title_text` | TEXT NULL | 报告标题或邮件主题 |
> | `content_json` | TEXT NULL, valid JSON | 结构化输出 |
> | `content_text` | TEXT NULL | 人类可读纯文本 |
> | `content_html` | TEXT NULL | 邮件或预览 HTML |
> | `lineage_json` | TEXT NOT NULL, valid JSON | raw ID/SHA 与上游 output ID/SHA 清单 |
> | `content_sha256` | TEXT NOT NULL | 标题、JSON、文本、HTML与合同元数据的统一摘要 |
> | `created_at_utc` | TEXT NOT NULL | 建立时间 |
>
> 初始 `output_kind` 为：`sync_summary`、`bounded_evidence`、`daily_summary`、
> `weekly_summary`、`training_plan`、`report_artifact`、`email_render`、
> `garmin_workout_contract`、`execution_summary`。约束：至少一个内容字段非空；
> `UNIQUE(logical_key, revision_no)`、`UNIQUE(logical_key, content_sha256)`、
> `UNIQUE(supersedes_output_id)`。日报、周报至少具有 JSON 与纯文本；`report_artifact` 与
> `email_render` 必须同时具有 JSON、纯文本和 HTML。修订只能新增一行并指向上一版，不覆盖或
> 删除旧内容；当前版本为修订链末端。无效模型原文不保存，只保存脱敏验证错误。
>

### 原定义-L626

来源标题：5. `approvals`：人工批准与定时 AI 授权链；原件L626–L651。

> ### 5. `approvals`：人工批准与定时 AI 授权链
>
> | 字段 | 类型/约束 | 作用 |
> | --- | --- | --- |
> | `id` | INTEGER PK | 批准 ID |
> | `approval_key` | TEXT UNIQUE NOT NULL | 规范化批准内容的稳定唯一键 |
> | `recorded_by_run_id` | INTEGER NULL FK → `skill_runs.id` | 记录决定的运行；人工直接记录时可空 |
> | `candidate_output_id` | INTEGER NULL FK → `skill_outputs.id` | 被审核的确切输出；长期预授权可空 |
> | `candidate_output_sha256` | TEXT NULL | 被审核输出摘要；与 output ID 成对校验 |
> | `authority_approval_id` | INTEGER NULL FK → `approvals.id` | 定时 AI 对具体输出批准时引用的长期人工预授权 |
> | `supersedes_approval_id` | INTEGER NULL FK → `approvals.id` | 修订或撤销的旧决定 |
> | `authority_kind` | TEXT NOT NULL | `user_explicit` 或 `scheduled_ai` |
> | `decision` | TEXT NOT NULL | `approved`、`rejected` 或 `revoked` |
> | `scope_kind` | TEXT NOT NULL | Cron、课表、Garmin 发布、Gmail 发送或 Sites 发布范围 |
> | `scope_json` | TEXT NOT NULL, valid JSON | 日期、动作、对象和预算边界 |
> | `scope_sha256` | TEXT NOT NULL | 规范化范围摘要 |
> | `source_ref` | TEXT NOT NULL | 可审计的规则、计划或人工批准引用，不保存聊天全文 |
> | `reason_code` | TEXT NOT NULL | 简短理由码，不保存隐藏推理 |
> | `decided_at_utc` | TEXT NOT NULL | 决定时间 |
> | `valid_from_utc` | TEXT NOT NULL | 生效时间 |
> | `valid_until_utc` | TEXT NULL | 失效时间；空表示由范围和撤销控制 |
>
> `authority_kind=scheduled_ai` 时，必须同时具有 `candidate_output_id` 和仍有效的
> `authority_approval_id`；外部写入前必须验证长期批准未撤销、未过期且范围覆盖确切动作。
> 撤销只能新增 `revoked` 记录并用 `supersedes_approval_id` 连接，不改写原批准。
>

### 原定义-L652

来源标题：6. `external_actions`：Gmail、Garmin 与 Sites 外部动作；原件L652–L697。

> ### 6. `external_actions`：Gmail、Garmin 与 Sites 外部动作
>
> | 字段 | 类型/约束 | 作用 |
> | --- | --- | --- |
> | `id` | INTEGER PK | 动作 ID |
> | `idempotency_key` | TEXT UNIQUE NOT NULL | 每个外部动作的稳定唯一键 |
> | `skill_run_id` | INTEGER NOT NULL FK → `skill_runs.id` | 执行动作的 sender run |
> | `provider` | TEXT NOT NULL | `gmail`、`garmin` 或 `sites` |
> | `entity_kind` | TEXT NOT NULL | `email`、`workout`、`calendar_entry` 或 `site_snapshot` |
> | `action_kind` | TEXT NOT NULL | 实际 Provider 动作 |
> | `source_output_id` | INTEGER NOT NULL FK → `skill_outputs.id` | 实际发送内容或 Workout 合同 |
> | `source_output_sha256` | TEXT NOT NULL | 外部动作绑定的确切输出摘要 |
> | `approval_id` | INTEGER NOT NULL FK → `approvals.id` | 覆盖本动作和输出的批准 |
> | `related_action_id` | INTEGER NULL FK → `external_actions.id` | Workout 所有权或动作顺序关联 |
> | `target_key` | TEXT NOT NULL | 收件人指纹、课程逻辑键或日历日期 |
> | `target_external_id` | TEXT NULL | 被处理的 Provider 对象 ID |
> | `result_external_id` | TEXT NULL | Gmail Message、Workout 或 Calendar ID |
> | `provider_object_name` | TEXT NULL | Garmin Workout 名称等核验字段 |
> | `provider_marker` | TEXT NULL | Gmail 精确幂等标记等 Provider 可检索标识 |
> | `request_json` | TEXT NOT NULL, valid JSON | 实际发送或写入的有界请求合同 |
> | `request_sha256` | TEXT NOT NULL | 请求合同摘要 |
> | `status` | TEXT NOT NULL | 外部动作状态 |
> | `attempt_count` | INTEGER NOT NULL CHECK >= 0 | 执行尝试数 |
> | `prepared_at_utc` | TEXT NOT NULL | Provider 调用前持久化时间 |
> | `started_at_utc` | TEXT NULL | 调用开始时间 |
> | `finished_at_utc` | TEXT NULL | 终态时间 |
> | `last_reconciled_at_utc` | TEXT NULL | 最近 Provider 对账时间 |
> | `response_summary_json` | TEXT NULL, valid JSON | 有界结果，不保存完整 Provider 响应 |
> | `error_code` | TEXT NULL | 脱敏错误码 |
> | `error_summary` | TEXT NULL | 有界脱敏摘要 |
>
> `action_kind` 首版为：`gmail_send`、`sites_publish`、`garmin_workout_adopt`、`garmin_workout_create`、
> `garmin_workout_verify`、`garmin_calendar_schedule`、`garmin_calendar_unschedule`、
> `garmin_workout_delete`。状态为：`prepared`、`in_progress`、`succeeded`、`already_done`、
> `failed_safe`、`unknown` 或 `cancelled`。
>
> Provider 调用前先提交 `prepared`，原子认领后改为 `in_progress`；若 Provider 可能成功但本地
> 未落账，状态必须为 `unknown`，下次先按 Gmail marker、Garmin Provider ID 或 Sites 项目与
> 快照身份回读，禁止直接重试。只有 `failed_safe` 能自动使用同一幂等键再次尝试。实施时使用复合约束，确保
> `approval_id` 批准的 `candidate_output_id` 与动作的 `source_output_id` 相同。
>
> Garmin 删除还必须同时满足：名称精确以 `-GTS` 结尾；Provider Workout ID 已由本数据库中
> 成功的 `garmin_workout_create` 或明确人工确认的 `garmin_workout_adopt` 建立所有权；未来排期
> 已解除；批准范围覆盖删除。新数据库不得只凭名称自动认领旧 GTS Workout；是否一次性认领
> 现有模板留到技术合同 3 决定。
>

### 原定义-L698

来源标题：六表的写入与保留规则；原件L698–L709。

> ### 六表的写入与保留规则
>
> - `raw_files`、`skill_outputs`、`approvals` 采用新增修订，不删除历史内容。
> - `activity_inventory` 是可变采集缓存；`skill_runs` 和 `external_actions` 只按受控状态机更新，
>   不删除记录。
> - 所有 Provider 写入先有 `skill_outputs`，再有覆盖该确切输出的 `approvals`，最后才创建
>   `external_actions`；外部动作不得引用宽泛或已被撤销的批准。
> - SQLite 无法对 JSON 血缘中的每个 ID 建外键，这是六表限制的明确代价；实现阶段必须用
>   独立一致性检查器补偿，不得静默忽略坏引用。
> - 当前不加入通用事件溯源、任意 Provider 插件、多用户、自动 Provider 删除生命周期、外部
>   响应全文或另一套 `artifacts/receipts` 权威状态。
>

### 原定义-L710

来源标题：技术合同 2：SQLite 备份、恢复与保留 v1（初始设计记录；后续已实施）；原件L710–L715。

> ## 技术合同 2：SQLite 备份、恢复与保留 v1（初始设计记录；后续已实施）
>
> 该合同只保护 `source/state/trainlab.db` 中不能从 raw 重现的 AI 输出、批准和外部动作状态。
> health、FIT、GPX、TCX 和天气 raw 不重复装进 SQLite 备份；恢复时必须验证数据库引用的 raw
> 仍完整存在。
>

### 原定义-L716

来源标题：备份位置与格式；原件L716–L743。

> ### 备份位置与格式
>
> - 当前备份目录固定为 `source/state/backups/sqlite/`，与将被删除的
>   `source/state/raw/backup/` 完全无关；前者是数据库灾难恢复，后者是旧 raw 命名空间。
> - 只保存在 `source/state/` 同一磁盘的备份只能防逻辑损坏和误操作，不能防整盘损坏；在未来
>   明确批准独立加密备份根之前，状态必须标为 `backup_redundancy_degraded`，不得宣称完整灾备。
> - 目录权限 `0700`；数据库快照、manifest 与恢复收据均为 `0600`，属主必须是当前运行用户。
> - 所有相关进程使用 `umask 077`；`source/state/trainlab.lock` 是 cron、备份和恢复共用的本机
>   排他锁。SQLite 单写者不能替代业务锁。
> - 文件名为：
>
> ```text
> trainlab-<UTC timestamp>-<operation-id>-<db-sha-prefix>.db
> trainlab-<UTC timestamp>-<operation-id>-<db-sha-prefix>.manifest.json
> ```
>
> - manifest 只保存：合同版本、operation ID、备份类型、建立时间、数据库完整 SHA-256 与大小、
>   `user_version`、六表行数、最高 run/output/action ID、未终态外部动作计数、raw 索引聚合摘要、
>   代码与 Skill 版本摘要、`raw_validation_level`（`index_only` 或 `full_bytes`）以及验证结果。
>   不得包含健康数值、活动名称、收件地址、凭据、绝对路径或 raw 内容。备份类型只允许
>   `workflow_daily`、`workflow_weekly`、`manual`、`pre_change`、`external_barrier`、
>   `pre_restore` 或 `post_restore`。
> - `-wal` 与 `-shm` 永远不单独复制或视为备份；使用 SQLite Online Backup API 把已提交的
>   WAL 状态合并为一个独立快照，并将备份副本关闭为不依赖 WAL/SHM 的单文件。禁止用普通
>   文件复制替代一致性备份。
> - `goal.md`、`config.json` 和两份凭据不属于 SQLite 备份；未来若要求整机恢复，必须另立
>   owner-only 配置/凭据备份合同，不能声称本合同已经覆盖。
>

### 原定义-L744

来源标题：建立备份；原件L744–L754。

> ### 建立备份
>
> 1. 取得同一数据库写入锁；拒绝符号链接、错误属主或宽松权限。
> 2. 用 Online Backup API 写入同文件系统的临时数据库，设置 `0600`，完成后 fsync。
> 3. 对临时快照执行 `integrity_check`、`foreign_key_check`、`user_version=1`、六表精确清单、
>    JSON/修订链/批准绑定/外部动作状态和数据库内部 raw 索引摘要检查。普通备份不逐字节重读
>    全部 raw；manifest 明确标为 `index_only`。
> 4. 对数据库字节计算完整 SHA-256，写入临时 manifest；fsync 两个文件和父目录。
> 5. 将数据库与 manifest 原子改名为最终名称，再复核一次名称、摘要和权限。任一检查失败时
>    删除临时文件并记录脱敏失败，不产生“可恢复”备份。
>

### 原定义-L755

来源标题：备份触发点；原件L755–L770。

> ### 备份触发点
>
> - 每个顶层每日、每周或人工工作流进入终态后，若数据库发生写入，分别建立
>   `workflow_daily`、`workflow_weekly` 或 `manual` 快照；失败或 blocked 状态也要保留，因为
>   它们是下一次无状态运行的依据。
> - Schema 变化、状态裁剪、批量修订或非恢复型数据库替换前，必须先建立 `pre_change` 快照。
> - 恢复使用专用 `pre_restore`：仅当当前主库仍可读取并能通过 Online Backup API 产生一致快照
>   时建立；主库已损坏或不可读时不得伪造备份，改为把原数据库字节连同 WAL/SHM 原样隔离。
> - 恢复完成并通过最终路径校验后，必须建立一个 `post_restore` 快照。
> - Gmail、Garmin 或 Sites 外部写入前，先在主库提交 `prepared` 动作，再建立
>   `external_barrier` 快照；只有该快照通过验证后才允许调用 Provider。这样即使主库随后丢失，
>   恢复后仍能看到幂等键并先对账，而不是盲目重复外部动作。
> - 只读查询不建立备份；同一数据库最高状态与同一备份类型完全相同时可复用最近已验证快照。
> - 周日两个 cron 同时到达时，每日流程必须先完成并产生当日 summary；周流程取得锁后重新检查
>   该依赖。依赖未成功时周流程进入 `blocked`，不得自行重复同步或跳过日报。
>

### 原定义-L771

来源标题：恢复流程；原件L771–L795。

> ### 恢复流程
>
> 1. 停止两个 cron 与所有数据库写入者，取得独占恢复锁；不得在活动写入时恢复。
> 2. 由操作者指定确切 `.db + manifest.json` 配对，不静默猜测“最新”文件；验证文件名、属主、
>    权限、完整摘要、manifest Schema 和 operation ID。
> 3. 以只读方式检查候选数据库完整性、外键、六表、修订链、批准链和未终态外部动作。
> 4. 按 `raw_files` 逐项验证当前 raw 的路径、普通文件类型、大小与完整 SHA-256；任一缺失或不符
>    都以 `backup_raw_closure_invalid` 停止，禁止为恢复而伪造或补写 raw。
> 5. 若当前主库仍可读取，先建立并验证 `pre_restore` 快照；若已损坏，原字节连同 WAL/SHM
>    只移入 owner-only 隔离，不丢弃。
> 6. 把候选快照复制到同目录临时路径，再次验证后关闭所有连接；将当前 DB/WAL/SHM 移入隔离，
>    原子改名候选为 `trainlab.db`，fsync 父目录，再按运行模式重新启用 WAL。
> 7. 从最终路径再次运行全部校验，并写入 0600 的 `restore-<operation-id>.json` 收据。收据是
>    基础设施恢复证据，不冒充 Skill 输出。
> 8. 恢复后先阻断正常 cron；对 `prepared`、`in_progress` 或 `unknown` 外部动作逐项回读对账。
>    在所有未知结果解决前，不得自动重发邮件、重建 Workout、重新排期或重复发布 Sites。
>
> 恢复副本首次打开后，遗留 `skill_runs.running` 必须改为 `interrupted`；
> `external_actions.prepared/in_progress` 必须改为 `unknown`，原有 `unknown` 保持不变。原因是备份
> 建立之后 Provider 可能已被调用，不能仅凭快照中的旧状态判断“尚未执行”。这些转换和恢复
> operation ID 写入恢复收据，并包含在 `post_restore` 快照中。
>
> 若原子切换后的最终校验失败，立即关闭新库并用 `pre_restore` 快照逆向恢复；不能安全回滚时
> 保持停止状态，保留两边字节和收据，等待人工处理，不尝试猜测正确版本。
>

### 原定义-L796

来源标题：保留规则；原件L796–L810。

> ### 保留规则
>
> - `workflow_daily`：保留最近 14 个已验证快照。
> - `workflow_weekly`：保留最近 8 个已验证快照。
> - `manual` 与已完成变更的 `pre_change`：各保留最近 3 个。
> - `pre_restore` 与对应 `post_restore` 按恢复 operation 成对保留最近 3 组；当前回滚点、尚未生成
>   已验证 `post_restore` 的 `pre_restore`，以及仍有未完成对账的恢复组永不自动删除。
> - `external_barrier`：在对应动作终态且更晚的已验证 workflow 快照已经包含该终态前，永不
>   自动删除；满足条件后按最近 8 个保留。
> - 正在恢复、被标记为当前回滚点或只有一个可用副本的快照不得自动删除。只有新备份验证成功后
>   才能裁剪旧备份；自动裁剪前至少保留两个可独立验证的快照，数据库文件与 manifest 必须成对
>   移除。
> - raw 不属于这些保留数量。任何未来 raw 裁剪都必须先证明所有保留数据库备份的 raw 闭包仍
>   成立，或显式退役受影响备份；禁止产生“数据库可恢复但证据已丢失”的假备份。
>

### 原定义-L811

来源标题：必须验证的故障场景；原件L811–L821。

> ### 必须验证的故障场景
>
> - WAL 有未 checkpoint 的已提交事务时，备份仍可独立打开且内容完整。
> - 临时写入、fsync、manifest、原子改名和备份后校验任一步失败时，不出现可用假快照。
> - 备份摘要错误、manifest 被改、raw 缺失/哈希不符、Schema 版本不兼容时，恢复在切换前停止。
> - 在 Provider 调用后、本地终态落账前崩溃时，恢复后动作保持 unknown 并先对账。
> - 恢复切换前、切换中和切换后故障均能前滚或回滚到一个明确状态；不会自动启动 cron。
> - 保留裁剪不会删除唯一可用备份、未闭合 external barrier 或当前回滚点。
> - 首次启用 cron 前必须在仓库外 owner-only 临时目录完成一次恢复演练；此后每 4 个周日锚点
>   至少演练一次。演练执行 `full_bytes` raw 闭包校验，但不替换正式库，也不调用任何 Provider。
>

### 原定义-L822

来源标题：技术合同 3：六个运行 Skills 输入、输出、失败与幂等 v1（已实施并通过独立验证）；原件L822–L827。

> ## 技术合同 3：六个运行 Skills 输入、输出、失败与幂等 v1（已实施并通过独立验证）
>
> 六个项目 Skill、公共脚本、Schema、SQLite 和两套模板均已建立为最小可验证骨架；本合同仍不
> 表示已启用 Provider、Gmail、Sites 或 cron。正式切换前必须由独立 Validator 检查每个 Skill
> 的输入、输出、失败码、幂等和无外部调用边界。
>

### 原定义-L828

来源标题：公共调用信封；原件L828–L860。

> ### 公共调用信封
>
> 每次 Skill 调用先形成 `skill_request_v1`，只包含有界结构化字段：
>
> | 字段 | 必需内容 |
> | --- | --- |
> | `schema_version` | 固定 `1` |
> | `request_id` | 本次请求唯一 ID |
> | `workflow_key` | 同一日报、周报或人工操作的关联键 |
> | `parent_run_id` | 上游 Skill run；顶层调用为空 |
> | `skill_name`、`operation` | 必须匹配下述精确枚举 |
> | `trigger_kind` | `cron_daily`、`cron_weekly`、`manual`、`recovery` 或 `skill` |
> | `target_period` | `Asia/Hong_Kong` 日期或日期范围 |
> | `input_refs` | 按角色列出的 raw/output ID、完整 SHA-256、Schema 与版本；不得嵌入大型 raw |
> | `instruction` | 可选的有界自然语言要求及来源 `user` 或 `scheduled_ai`；不得保存隐藏推理 |
> | `goal_sha256`、`config_sha256` | 本次实际读取版本；不把私有文件全文写进请求日志 |
> | `harness_sha256`、`skill_sha256` | 本次规则和 Skill 版本 |
> | `approval_ids` | 仅外部动作需要；必须能覆盖确切输出和动作 |
> | `options` | 经过对应 Schema 允许的有限选项；未知字段拒绝 |
>
> 规范化请求摘要决定 `dedupe_key`：
>
> ```text
> SHA256(skill_name + NUL + operation + NUL + target_period + NUL + canonical_request)
> ```
>
> 同一摘要已有成功 run 时直接返回既有 output/action 引用，不建立新修订。输入摘要变化时允许新
> run；输出使用不变的 `logical_key` 和递增 `revision_no` 表达修订。
>
> 每次调用返回 `skill_result_v1`：`run_key`、`status`、`output_refs`、`external_action_refs`、
> `warnings`、`error_code` 和 `next_action`。成功必须以 SQLite 事务落账为完成边界；模型输出、
> 临时 HTML、MCP 返回或聊天文本都不能单独证明成功。
>

### 原定义-L861

来源标题：公共状态与失败规则；原件L861–L873。

> ### 公共状态与失败规则
>
> - `pending → running → succeeded|failed|blocked|interrupted|cancelled` 是唯一 run 状态机。
> - `blocked` 表示缺输入、缺批准、认证无效、依赖不可用或需要人工决定；不得自动扩大范围。
> - `failed` 表示已确定没有外部副作用的校验、解析、渲染或持久化失败；可用相同请求建立更高
>   attempt，但不得覆盖旧 run。
> - 进程消失或租约过期标为 `interrupted`，恢复判断完成前不得重试。
> - 外部动作只有 `failed_safe` 可自动重试；`unknown` 必须先对账，禁止换幂等键绕过。
> - 所有错误只保存稳定错误码和有界脱敏摘要；不保存模型原文、凭据、Provider 完整响应或隐藏
>   推理。
> - 公共 canonical JSON、SQLite 事务/备份、hash、权限和血缘检查只能有一份受测实现。实现时
>   可放在 `source/skills/_shared/`；该目录没有 `SKILL.md`，不是第七个 Skill，也不得直接触发。
>

### 原定义-L874

来源标题：稳定失败码白名单；原件L874–L903。

> ### 稳定失败码白名单
>
> 首版 `error_code` 只能取下列公共集合与对应 Skill 专属集合的并集；成功时必须为空，未知错误码
> 按 `input_contract_invalid` 拒绝，不能临时拼接 Provider 文本。`unknown` 不是 run 状态：当外部
> 动作结果不明时，run 返回 `blocked`，对应 `external_actions` 保持 `unknown`，并要求先对账。
>
> | 适用范围 | result status | 精确错误码 |
> | --- | --- | --- |
> | 全部 Skill | `blocked` | `runtime_harness_unavailable`、`runtime_state_contract_unavailable`、`input_hash_mismatch`、`dependency_output_missing`、`state_lock_unavailable`、`dependency_outcome_unknown` |
> | 全部 Skill | `failed` | `input_contract_invalid`、`state_persistence_failed` |
> | 全部 Skill | `interrupted` | `run_interrupted` |
> | 全部 Skill | `cancelled` | `run_cancelled` |
> | `garmin-sync` | `blocked` | `garmin_mcp_unavailable`、`garmin_cached_auth_unavailable`、`garmin_identity_mismatch`、`garmin_backfill_not_approved`、`garmin_budget_exhausted`、`raw_identity_ambiguous`、`raw_path_conflict`、`sync_reconciliation_required` |
> | `garmin-sync` | `failed` | `garmin_window_invalid`、`garmin_budget_invalid`、`garmin_provider_response_invalid`、`garmin_provider_read_failed_safe`、`raw_write_failed`、`raw_hash_mismatch`、`inventory_state_invalid` |
> | `training-coach` | `blocked` | `coach_evidence_missing`、`coach_history_incomplete`、`coach_goal_unavailable`、`coach_model_unavailable`、`coach_lifecycle_unresolved` |
> | `training-coach` | `failed` | `coach_output_invalid`、`coach_lineage_invalid`、`coach_safety_rejected` |
> | `weekly-fitness-summary` | `blocked` | `weekly_evidence_incomplete`、`weekly_evidence_conflict` |
> | `weekly-fitness-summary` | `failed` | `weekly_review_invalid`、`weekly_review_safety_rejected` |
> | `garmin-training-sender` | `blocked` | `garmin_sender_mcp_unavailable`、`garmin_sender_auth_unavailable`、`garmin_plan_not_approved`、`garmin_approval_invalid`、`garmin_ownership_unproven`、`garmin_target_ambiguous`、`garmin_adoption_not_approved`、`garmin_reconciliation_required`、`garmin_verification_mismatch`、`garmin_action_outcome_unknown` |
> | `garmin-training-sender` | `failed` | `garmin_contract_invalid`、`garmin_action_failed_safe` |
> | `training-report-publisher` | `blocked` | `report_builder_unavailable`、`fixed_template_unavailable`、`sites_not_authorized`、`sites_outcome_unknown` |
> | `training-report-publisher` | `failed` | `report_validation_failed`、`fixed_template_invalid`、`email_render_unsafe`、`output_persistence_failed`、`sites_publish_failed_safe` |
> | `gmail-sender` | `blocked` | `gmail_mcp_unavailable`、`gmail_auth_unavailable`、`gmail_send_not_approved`、`gmail_query_not_authorized`、`gmail_marker_conflict`、`gmail_reconciliation_required`、`gmail_send_outcome_unknown` |
> | `gmail-sender` | `failed` | `email_render_invalid`、`gmail_recipient_invalid`、`gmail_query_invalid`、`gmail_query_failed_safe`、`gmail_action_failed_safe` |
>
> `garmin_action_failed_safe`、`sites_publish_failed_safe` 与 `gmail_action_failed_safe` 只允许在
> Provider 已明确拒绝且证明没有产生外部副作用时使用；否则必须使用对应的 outcome-unknown 码。
> 读取型 Garmin/Gmail 操作若尚未产生写副作用，可以使用各自 `*_failed_safe`。实现可在未来
> Schema 升级中新增错误码，但必须显式升版本合同并补回归，不能在 v1 中自由扩展。
>

### 原定义-L904

来源标题：1. `garmin-sync`；原件L904–L931。

> ### 1. `garmin-sync`
>
> **Operations**：`index_existing_raw`、`daily_sync`、`manual_backfill`、`reconcile_sync`。
>
> **输入**：
>
> - `daily_sync` 只接受执行日 `D`，由 Host 确定 `D-1` 完整健康/活动和醒来日为 `D` 的已结束
>   主睡眠；不接受自定义回看天数。
> - `manual_backfill` 必须具有用户明确批准的日期、资源、Provider entry、返回 ID、raw 字节和
>   wall-time 预算；不能继承普通 cron 的自动权限。
> - `index_existing_raw` 只在新库初始化或明确修复时扫描已保留 raw，验证文件名、完整字节 SHA
>   与资源类型后建立索引；它不清洗健康/活动事实，也不调用 Provider。无法唯一绑定的活动文件
>   以 `unresolved` 登记并在 summary 中列出 `raw_activity_binding_unresolved` warning，不制造
>   Provider activity ID。后续 `reconcile_sync` 试图完成绑定但仍无法唯一证明时，才返回
>   `raw_identity_ambiguous` 并保持原记录不变。
> - 读取 SQLite inventory/raw 索引和精确 Garmin MCP 绑定；请求不携带 token、密码或 MFA。
>
> **写入/输出**：原子写 raw 后更新 `raw_files` 与 `activity_inventory`；输出一个
> `sync_summary`，只含窗口、资源、Provider 调用计数、文件 ID/SHA、inventory 状态、缺口和
> 错误码，不含 raw 正文或健康值。Garmin 读取不是 `external_actions` 写动作，但其预算与结果
> 必须由 run 和 sync summary 留痕。
>
> **失败与幂等**：同一 daily request 成功后再次调用返回既有 summary，零 Provider 请求。
> 文件同路径同 SHA 为已完成；同路径不同 SHA 停止为 `raw_path_conflict`。临时文件、解析失败或
> 哈希失败不登记为 verified。身份不匹配、认证不可用或 MCP 绑定缺失为 blocked；日期窗口或
> 预算合同本身非法为 failed；合法预算在执行中耗尽为 blocked。禁止自动登录、MFA、token
> refresh、历史扩窗或回退到 `activity_summary`。
>

### 原定义-L932

来源标题：2. `training-coach`；原件L932–L956。

> ### 2. `training-coach`
>
> **Operations**：`daily_coach`、`weekly_coach`、`validate_plan`。
>
> **每日输入**：本次 `sync_summary`、脚本从当前 raw 产生的 `bounded_evidence`、此前最多 14 份
> 有效 `daily_summary`、当前 goal/config/rules 摘要，以及可选用户或定时 AI 指令。历史总结
> 足够时禁止重读其对应 raw；仅在摘要缺失、矛盾、缺少必要细节或用户明确要求时定向解析。
>
> **每周输入**：本周期 7 份有效 `daily_summary`、此前最多 4 份有效 `weekly_summary`、
> `weekly-fitness-summary` 输出、goal/config/rules 摘要和可选指令。若本周日报缺失，不得把更早
> raw 无条件重算成替代品。
>
> **输出**：
>
> - 每日产生 `bounded_evidence` 与 `daily_summary`，包含昨日健康/活动、昨夜主睡眠、判断、
>   来源 ID/SHA 和必要安全提示；不产生课表修订。
> - 每周产生 `weekly_summary` 与 `training_plan`；计划只含跑步、攀岩和休息，采用严格课程
>   合同、单日单主课、硬负荷间隔、降级和停止条件。
> - JSON 与纯文本必须通过确定性 Schema、安全和负荷门后才能落库；表现层 HTML 交给
>   `training-report-publisher`。
>
> **失败与幂等**：相同输入摘要返回既有修订。模型输出结构错误、无来源主张或越过安全门时
> 返回 `coach_output_invalid`/`coach_safety_rejected`，不保存无效原文。必要 evidence、日报或
> goal 缺失时 blocked，不猜测。该 Skill 不写 Garmin/Gmail/Sites，也不自行修改 `goal.md`。
>

### 原定义-L957

来源标题：3. `weekly-fitness-summary`；原件L957–L971。

> ### 3. `weekly-fitness-summary`
>
> **Operation**：`summarize_week`。
>
> **输入**：本周期 7 份日报、此前 4 份周报和由 `training-coach` 解析脚本提前生成的定向
> `bounded_evidence`；不得自行调用 Garmin、读取数据库外未知文件或重建完整历史窗口。
>
> **输出**：一个 Schema 为 `weekly_fitness_review_v1` 的 `bounded_evidence`，包含跑步、攀岩、
> 恢复趋势、证据质量和下周约束建议；它是 `weekly_coach` 的证据输入，不直接形成正式课表。
>
> **失败与幂等**：按周期与全部输入 SHA 去重。摘要缺失时返回
> `weekly_evidence_incomplete` 并列出确切缺项；输入均存在但内容或 lineage 相互冲突时返回
> `weekly_evidence_conflict`。两者都不联网补齐、不生成推测结论。本地 Skill 适配现有全局参考
> 能力，但不复制、修改或调用全局文件作为运行状态。
>

### 原定义-L972

来源标题：4. `garmin-training-sender`；原件L972–L992。

> ### 4. `garmin-training-sender`
>
> **Operations**：`apply_weekly_plan`、`reconcile_garmin`、`adopt_existing_workout`。
>
> **输入**：确切 `training_plan` ID/SHA、确定性课程合同、目标日历范围、有效批准链，以及本库
> 既有 Garmin ownership/action 记录。定时 AI 批准必须引用仍有效的人工预授权并绑定本次计划
> SHA；普通 AI 无权批准。
>
> **写入/输出**：先保存 `garmin_workout_contract`，再按顺序为解除排期、删除、创建、验证、
> 排期各建一个 `external_actions`；每一步依赖前一步已验证终态。最后输出有界
> `execution_summary`，列出每门课的状态和 Provider ID，不保存完整 Provider 响应。
>
> **安全与幂等**：
>
> - 只管理数据库已记录 create/adopt ownership 且名称精确以 `-GTS` 结尾的 My Workouts；不触碰
>   已完成 Activity 或非 GTS Workout。
> - 新数据库不得自动认领历史 GTS。`adopt_existing_workout` 只允许用户显式批准，不能由普通
>   周期预授权替代。
> - 创建键绑定 `plan_sha + course_key`；排期键绑定 `workout_id + date`；删除键绑定精确
>   `workout_id`。Provider 结果未知时先回读 ID、名称、结构和日历，禁止直接重做。
>

### 原定义-L993

来源标题：5. `training-report-publisher`；原件L993–L1017。

> ### 5. `training-report-publisher`
>
> **Operations**：`render_daily`、`render_weekly`、`publish_sites`、`reconcile_sites`。
>
> **输入**：
>
> - 日报：确切 `daily_summary` ID/SHA。
> - 周报：确切 `weekly_summary`、`training_plan` 与 Garmin `execution_summary` ID/SHA；若 Garmin
>   流程按批准被跳过，也要有明确 skipped 结果。
> - `mode` 默认为 `open_report`；`fixed_email` 只能由请求指定或获准 fallback。输入还必须绑定
>   renderer/template 版本和全部 lineage。
>
> **输出**：先建立 `report_artifact`，再建立 `email_render`；二者都含结构化 JSON、纯文本、
> 自包含/邮件安全 HTML 与完整摘要。`open_report` 使用 `$data-analytics:build-report` 的 portable
> HTML 路径和本地 open-report 邮件外壳；`fixed_email` 使用固定模板。该 Skill 只改变表现，不能
> 修改来源事实或课程。
>
> **Sites**：只有独立批准覆盖 exact report SHA、`sites_publish`、访问范围与有效期时，才在
> report 与 email render 之间调用 `$data-analytics:publish-artifact-to-sites`。发布前建立
> external barrier；成功 URL 可进入邮件，正文仍必须独立可读。未授权时 `sites_snapshot` 缺席；
> unknown 时先按项目/版本对账。除非授权明确允许“无 Sites 继续邮件”，发布失败不得静默降级。
>
> **幂等**：渲染键绑定全部 source SHA、mode、renderer/template SHA；同输入复用既有输出，任一
> 来源变化产生同 logical key 的新修订。稳定错误码采用项目 Skill 中列出的初始集合。
>

### 原定义-L1018

来源标题：6. `gmail-sender`；原件L1018–L1034。

> ### 6. `gmail-sender`
>
> **Operations**：`send_email`、`query_email`、`reconcile_gmail`。
>
> **输入**：发送时只接受确切 `email_render` ID/SHA、从私有配置解析的固定目标、有效批准和
> 唯一 marker；禁止发送前修改主题或正文。查询/接收时只接受有界 query、时间范围和结果上限，
> 不得因此恢复 raw/gmail 目录。
>
> **写入/输出**：发送前建立 `gmail_send` external action 和 external barrier；成功或对账后输出
> `execution_summary`。有界查询结果保存为 `bounded_evidence`，可包含任务需要的邮件正文，但
> 数据库始终按私有 0600 处理，不把地址或内容写入日志、公开报告或 marker。
>
> **失败与幂等**：只使用当前启用的精确 `gmail` MCP 绑定，不安装、认证或回退到其他传输。
> 发送键绑定 `email_render_sha + recipient_fingerprint`；Provider 调用前先精确搜索 marker，零条
> 才发送，一条为 `already_done`，多条为冲突。调用结果未知时再次搜索，不直接重发。草稿、标签、
> 回复、转发或删除必须各有单独操作合同和批准；首版定时报告只授权 `send_email`。
>

### 原定义-L1035

来源标题：每日与每周串行关系；原件L1035–L1057。

> ### 每日与每周串行关系
>
> ```text
> 每日：garmin-sync
>    → training-coach.daily_coach
>    → training-report-publisher.render_daily
>    → gmail-sender.send_email
>
> 周日：先等待当日每日流程成功
>    → garmin-sync（同请求应幂等复用）
>    → training-coach 的定向解析
>    → weekly-fitness-summary.summarize_week
>    → training-coach.weekly_coach + validate_plan
>    → 用户或预授权定时 AI 对 exact plan SHA 留下 approval
>    → garmin-training-sender.apply_weekly_plan
>    → training-report-publisher.render_weekly（Sites 仅可选授权）
>    → gmail-sender.send_email
> ```
>
> 任一上游输出缺失、哈希改变、未通过门禁或外部动作 unknown，下游不得使用旧聊天、旧临时文件
> 或相似内容继续。周邮件必须引用实际 Garmin execution summary；若 Garmin 未获批准或失败，
> 邮件只能在合同明确允许时如实显示该状态，不能宣称已经建立或排期。
>

### 原定义-L1058

来源标题：目标结构草图；原件L1058–L1106。

> ## 目标结构草图
>
> 当前已确认的完整顶层目标为：
>
> ```text
> source/
> ├── AGENTS.md
> ├── requirements.txt
> ├── config.json
> ├── goal.module.md
> ├── goal.md
> ├── credentials.json
> ├── gcp-oauth.keys.json
> ├── templates/
> │   ├── fixed/
> │   │   ├── daily_report.html
> │   │   └── weekly_report.html
> │   └── open-report/
> │       ├── daily_report.html
> │       └── weekly_report.html
> ├── skills/
> │   ├── README.md
> │   ├── _shared/                 # 内部公共状态/校验库，不是 Skill
> │   ├── garmin-sync/
> │   ├── training-coach/
> │   ├── garmin-training-sender/
> │   ├── weekly-fitness-summary/
> │   ├── gmail-sender/
> │   └── training-report-publisher/
> └── state/
>     ├── trainlab.db
>     ├── trainlab.lock
>     ├── backups/sqlite/
>     ├── recovery-quarantine/
>     └── raw/
>     │   └── garmin/
>     │       ├── health/
>     │       │   ├── .gitkeep
>     │       │   └── <YYYYMMDD>-<resource>-<content-hash>.json
>     │       └── activities/
>     │           ├── .gitkeep
>     │           ├── <YYYYMMDD>-<activity-hash>.fit
>     │           ├── <YYYYMMDD>-<activity-hash>.gpx
>     │           ├── <YYYYMMDD>-<activity-hash>.tcx
>     │           └── <YYYYMMDD>-<activity-hash>.weather.json
> ```
>
> 未来 Provider 使用相同的“Provider 平级”原则，但不要求拥有与 Garmin 相同的子目录。
>

### 原定义-L1107

来源标题：数据保护要求；原件L1107–L1116。

> ## 数据保护要求
>
> - 目录整理不得改变 Garmin raw 的原始字节。
> - 不得因为重命名或分类而丢失数据库中的来源、版本或活动关联。
> - 分析所需的健康证据必须能从 `health/` 按需解析；活动证据必须能从 `activities/` 按需解析；
>   不以此要求在 SQLite 建立健康或活动业务事实表。
> - inventory 等程序控制状态不得冒充健康或活动事实，也不得作为删除已归档活动的依据。
> - 私有数据继续被 Git 忽略，不得进入提交、日志或公开文档。
> - 正式实施前必须先完成只读影响分析并由用户确认具体开发范围。
>

### 原定义-L1117

来源标题：已执行与最终结果；原件L1117–L1127。

> ## 已执行与最终结果
>
> 以下内容属于实现后的收尾门禁，均已完成：
>
> - candidate 与正式 state 的最终原子切换及回滚收据；
> - 独立 Validator 对六 Skills、备份配对、raw 闭包和删除清单的最终复核；
> - 旧 `source/src`、`source/tests`、`source/scripts`、`source/tools`、`source/typings`、旧
>   `source/docs`、`source/index.py`、`source/pyproject.toml` 和 `source/requirements.lock` 的
>   精确退役；
> - cron 配置只保留文件，不安装、不启用、不调用外部服务。
>

### 原定义-L1128

来源标题：旧运行层退役清单（切换后执行）；原件L1128–L1144。

> ### 旧运行层退役清单（切换后执行）
>
> 只有 candidate、成对备份、原子切换和独立 Validator 全部通过后，才按以下精确清单退役；
> 切换前不删除任何一项：
>
> | 退役对象 | 新替代 | 处理方式 |
> | --- | --- | --- |
> | `source/src/` | `source/skills/*/scripts/`、`source/skills/_shared/` | 精确删除已跟踪旧包 |
> | `source/tests/` | `source/skills/_tests/` 与各 Skill 自测 | 精确删除旧产品测试，不删除新合同测试 |
> | `source/scripts/`、`source/tools/`、`source/typings/` | 各 Skill 的确定性脚本与 `_shared/scripts/` | 精确删除旧开发/运行工具 |
> | `source/index.py`、`source/pyproject.toml` | `codex exec -C source`、`requirements.txt` | 精确删除旧统一 CLI/项目描述 |
> | `source/requirements.lock` | `source/requirements.txt` | 新依赖环境验证后删除 |
> | 旧 `source/docs/`、旧 `source/config/`、旧 `source/logs/` | `source/AGENTS.md`、`source/skills/README.md`、`config.json`、模板 | 旧配置/日志随旧 state 归档，不覆盖新运行文件 |
>
> 切换后必须从仓库根和 `source/` 两个位置检查：旧路径无残留、六个 Skill 可独立读取 SQLite、
> 两个 cron 仍是未安装配置，且旧 state 只存在于 `data-backup/<operation-id>/` 的可恢复归档中。
>

### 原定义-L1145

来源标题：依赖与隔离；原件L1145–L1153。

> ## 依赖与隔离
>
> - 显式依赖：M6 已取消/被本计划替代；0001 保护提交、0002/0003 验证、0004 state 切换和最终
>   独立复核均已完成。
> - 当前允许写入：后续经批准的新 exec plan 和新运行层需求；`source/state` 仅由正式 Skill 按
>   SQLite 合同写入，旧归档只读。
> - 当前禁止写入：Garmin/Gmail/Sites、未安装的 cron、远端 Git；不得删除 data-backup 归档，
>   不得把退役源码或旧 state 当作新系统数据源。
>

### 原定义-L1154

来源标题：当前只读审计；原件L1154–L1179。

> ## 当前只读审计
>
> - 目标：盘点 Garmin JSON 资源、请求粒度和当前分析端实际用途，为用户决定保留、降采样或
>   停止采集哪些资源提供证据。
> - 边界：只读代码、catalog 和 immutable SQLite 元数据；不输出健康数值，不读取 raw 正文，
>   不调用 Provider，不修改 state 或产品。
>
> | 角色 | 档位 | 只读范围 | 返回内容 |
> | --- | --- | --- | --- |
> | JSON 资源盘点 | high/high | catalog、revision/raw 元数据 | 资源、粒度、数量、字节与采集形态 |
> | 分析消费映射 | high/high | projection、stable views、analysis | 教练/健康用途与当前实际消费者 |
> | 请求优化审计 | high/high | collector、Provider method、预算合同 | 可停采、可降频、需保留及心率粒度建议 |
> | 独立数据价值复核 | high/high | 当前代码和 immutable 汇总证据 | 核对分类、请求成本和删除边界 |
>
> 以下内容保留为此前只读审计证据；后续 R-001 至 R-020 的已确认需求是当前权威决定：
>
> - 历史 raw 有 53 种 JSON 语义资源；当前普通同步只使用较窄白名单。
> - 只排除 FIT/GPX/TCX 原始文件下载时，当前所谓 14 日 incremental 在每日首次推进时，
>   健康窗口通常实际覆盖 15 个自然日；成功路径业务调用约为
>   `103 + 设备数 + 2 × 14日活动数`。新单日需求约为
>   `17 + 设备数 + 2 × 昨日活动数`；两式均不含认证内部调用和失败重试。
> - 单看健康请求，当前每日推进通常为 94 次，新单日边界为 8 次，减少 86 次，约
>   `91.49%`。活动列表请求仍为 1 次；活动摘要与天气各按范围内每项活动请求 1 次。
> - 全天心率是每日一次响应包含多个点，不是每点一次请求；只保留 min/max 信息不足。
> - 停止未来采集、降低采集频率和删除历史 raw 是三个不同决定。
>

### 原定义-L1180

来源标题：当前检查点；原件L1180–L1194。

> ## 当前检查点
>
> - 当前 Loop：六个 Skills、两套模板、SQLite v1、goal/module 校验、raw-first candidate、
>   两个 cron 配置和旧运行层退役均已落地；r22 candidate、切换后 state 和最终运行树均通过独立
>   Validator。ADHOC-0011 全部任务完成。
> - 最近完成：training-coach 的 raw 解析现在输出结构化形状/FIT/XML 统计而不输出 raw 值；
>   training-report-publisher 会先把 `report_artifact` 再把 `email_render` 写入 SQLite；新增
>   成对备份与只读恢复校验脚本。所有当前脚本测试、Ruff、format 和 goal 校验通过。
> - 已完成的三个技术合同：
>   1. 六张 SQLite 表的字段、关系、约束、触发器和状态枚举；
>   2. SQLite Online Backup、manifest、恢复前只读校验和保留规则；
>   3. 六个本地 Skill 的输入、输出、失败和幂等骨架。
> - 当前禁止事项：本计划未调用 Provider、未发送邮件、未发布 Sites、未启用 cron；旧 state、旧
>   配置和退役源码仅保留在本次 data-backup 归档中，不作为新系统数据源。
>

### 原定义-L1195

来源标题：迭代日志；原件L1195–L1220。

> ## 迭代日志
>
> | 日期/上下文 | 已确认需求 | 下一动作 |
> | --- | --- | --- |
> | 2026-08-15 / provider-layout | 删除 backup/gmail/legacy，保留 raw/garmin 和 Provider 分层 | 继续收集需求 |
> | 2026-08-15 / activity-files | FIT、GPX、TCX 统一规划到 `raw/garmin/activities/` | 后续再分析关联影响 |
> | 2026-08-15 / activity-filenames | 三种活动文件不建格式子目录，统一使用日期与活动关联哈希命名 | 后续定义关联哈希合同 |
> | 2026-08-15 / json-value-audit | 只读盘点 JSON 资源、分析消费者与请求粒度；未读 raw 正文或调用 Provider | 用户决定采集与保留需求 |
> | 2026-08-15 / daily-sync-window | 每日 12:00 仅取昨日完整数据和今日早晨主睡眠；取消 14 日回读，补数须用户明确批准 | 继续收集需求，暂不分析实现 |
> | 2026-08-15 / non-original-request-audit | 只排除 FIT/GPX/TCX 下载，重算 health、account/device 与 activity JSON 请求和分析影响 | 用户决定各资源保留、降频或停采 |
> | 2026-08-15 / non-raw-state-reset | 未来删除 state 下除 raw 外的全部旧状态和数据库；新数据库只从保留 raw 重建 | 继续收集需求，暂不分析实施条件 |
> | 2026-08-15 / ai-skills-runtime | source 改为 AI+Skills 驱动；当时确认最小顶层、私有 goal/state、五个 Skill 与日报/周计划模板；training-coach 接受用户或 AI 输入并输出课表，批准可来自用户或预授权定时 AI | 后续增加报告发布 Skill |
> | 2026-08-15 / skill-catalog-finalization | 当时提议新增 gmail-sender，并将 state-rebuild 更名为 data-build；该 data-build 方案已被后续 `raw-on-demand-output-db` 决定废止；garmin-sync 仍以 SQLite 状态驱动 Garmin MCP 增量采集；所有 Skill 采用脚本优先 | 进入 SQLite 设计 |
> | 2026-08-15 / stateless-cron-workflows | 确认无状态落地原则、每日/每周两个 cron Prompt、training-coach 双模式及 My Workouts 的 GTS 模板替换规则 | 进入 SQLite 设计 |
> | 2026-08-15 / sqlite-state-boundary | 当时提议单一 trainlab.db、独立 artifacts/receipts、可重建索引原则及六类状态域；独立 artifacts/receipts 已被后续 `raw-on-demand-output-db` 决定废止，输出统一进入 SQLite | 设计精确字段与状态表 |
> | 2026-08-15 / raw-on-demand-output-db | 删除 data-build；training-coach 脚本按需解析 raw；SQLite 改为保存全部 Skill 输出、邮件内容和外部状态 | 设计六张表字段与备份 |
> | 2026-08-15 / summary-history-window | 日报复用前14份日报；周报复用当前7份日报与前4份周报；仅在缺失、矛盾或需细节时定向读取历史 raw | 需求稳定，进入技术设计 |
> | 2026-08-15 / requirements-final-validation | 修正旧方案残留表述；独立 Validator 确认现行需求、历史废止项、零实施边界和下一阶段三项合同一致，结论 PASS | 等待用户启动技术设计 |
> | 2026-08-15 / sqlite-schema-v1-candidate | 写入六表精确字段、约束、状态机、血缘与外部幂等候选；未创建数据库或修改 state | 独立验证后交用户确认 |
> | 2026-08-15 / data-analytics-report-skill | 新增本地 `training-report-publisher` 骨架与索引；默认 open report，固定模板兼容，Sites 单独授权；Skill 校验与无数据前向测试通过 | 纳入六 Skill 合同 |
> | 2026-08-15 / sqlite-backup-contract-v1 | 完成 SQLite Online Backup、external barrier、恢复、对账、保留与演练合同 | 与六表共同验证 |
> | 2026-08-15 / runtime-skill-contracts-v1 | 完成六个 Skill 的公共信封、精确操作、输入输出、失败、幂等及每日/周日串行关系 | 全新 Validator |
> | 2026-08-15 / contract-validation | 修正模板职责、备份类型、raw unresolved 绑定、失败码和两阶段报告落库歧义；第三位全新高风险 Validator 最终 PASS | 等待用户批准实施分解 |
> | 2026-08-15 / runtime-implementation | 落地六 Skills、模板、SQLite v1、raw-first candidate、report/email 双输出落库、结构化 raw 解析和只读恢复校验；同文件系统 candidate r11 已通过本地门禁 | 等待独立 Validator 后执行切换 |
> | 2026-08-16 / fixed-template-sanitization | 修复固定邮件模板的示例课程与默认训练值残留；固定渲染会将未提供字段安全替换为占位符；新增零未解析占位符、零示例课程回归；重建 r22 candidate | 已并入 r22 candidate；后续由 final-cutover-and-retirement 统一收口 |
> | 2026-08-16 / final-cutover-and-retirement | r22 candidate 通过独立 Validator；旧 state/config/logs 与集中式源码可恢复归档；新 state 原子切换；旧入口、源码、测试和旧配置从 source 精确退役；最终树与治理独立 Validator PASS | ADHOC-0011 完成并归档 |

## 历史来源与证据

- [不可变原件快照](../evidence/ADHOC-0029/history.zip)，条目`docs/exec-plans/completed/ADHOC-0011-state-raw-retention-and-tuning.md`，原SHA-256：`8a72efbbecc4169959b15380bb5d1d760cf05d01193407d1c286663ec9d7e933`。
- [来源清单](../evidence/ADHOC-0029/history-manifest.json)、[迁移/编号映射](../evidence/ADHOC-0029/migration-manifest.json)、[原问题与失败计数索引](../evidence/ADHOC-0029/failure-index.json)。原记录中的绝对路径和失效外部证据只说明当时事实，不据此复建旧路径。
- 历史快照仅用于保真审查，不作为现行规范、产品导入、Schema、AI输入或CI运行依赖。当前实际迁移验收见[ADHOC-0029](../completed/ADHOC-0029-agentsmd-upgrade.md)。
