# 执行计划：升级agentsmd并行开发Harness

## 对应目标

- 功能编号：ADHOC-0034
- 功能状态：[completed]
- 总计划对应条目：[PLAN.md](../../PLAN.md)的ADHOC-0034。
- 目标及范围和验收要求的引用：用户2026-09-20明确更新最新版agentsmd；[H34-01～07](../evidence/ADHOC-0034/requirements.md)、[Planner拆解](../evidence/ADHOC-0034/planner.md)、[主审核](../evidence/ADHOC-0034/plan-review.md)。固定官方37520a5132bb5f84064e04f18d7a4467ebdc9116，更新规则/模板/技能，保护业务记录；不恢复0033、不升级调度器或运行产品。

## 阶段与任务

| 阶段编号 | 状态 | 预期成果 | 依赖 |
| --- | --- | --- | --- |
| S1 | [completed] | 来源、保护、隔离分支及方案主审 | 用户授权 |
| S2 | [completed] | 唯一Harness候选及两套固定组合 | S1 |
| S3 | [completed] | 独立验证、主验收、原区落地及适用交付 | S2 |

| 任务编号 | 所属阶段 | 状态 | 输入输出及错误边界 | 依赖 | 检查方法 | 结果与证据（检查命令或人工方式、退出结果及关键证据） |
| --- | --- | --- | --- | --- | --- | --- |
| 0034-T01 | S1 | [completed] | 固定上游/本地差异→来源、保护清单、分支及方案；不读私有数据 | 用户要求 | ls-remote/11文件SHA、分支/差异、全新规划及主核 | 官方37520a5；origin/main af09e3f；29规划材料不变，175source＋4 references、38项差异保全；6234旧证据记录。主preserve_planning.py退出0，[保全](../evidence/ADHOC-0034/planning-preservation.json) |
| 0034-T02 | S2 | [completed] | 批准清单→8文件更新、静态自查和候选H；不改协调/产品/私有内容 | T01 | 七文件原字节、索引/许可/字段/规则情景、精确diff与保护 | workflow/child正式complete；主核33工具调用无报错并亲跑检查器退出0，374基线367项未变、7份原字节、8文件差异，候选H接收。[接收核对](../evidence/ADHOC-0034/developer-intake.md)；不代表独立或整个升级通过 |
| 0034-T03 | S2 | [completed] | H＋两区各自记录→主最小协调增量、C34/Cuse固定副本及SHA；不整份互盖记录 | T02主核 | 实际未提交差异/必要链接依赖、H一致、保护项不变 | 两物理组合已建立，主脚本恢复后退出0；同版H，各自保留业务记录、Memory只换脚手架行、Cuse0033只加隔离节；179资源及6234旧证据原件核同。首次位置/材料留存；当前按[修正后的交接定义](../evidence/ADHOC-0034/handoff-v2.md)重新提供完整before及landing清单。上游/目标最近复查仍37520a5/af09e3f |
| 0034-T04 | S3 | [completed] | 固定两组合/客观要求→全新Validator独立结论；不改受审内容 | T03 | 独立正常/禁止/边界、链接/锚点/记录保真/语义检查 | 首次独立失败：H34-V1-001/002交接前置材料不闭合；规则/技能及已提供保护通过，7130项不变；[报告](../evidence/ADHOC-0034/validation-v1/report.md)、[主复核](../evidence/ADHOC-0034/validation-v1/parent-review.md)。方法A修正后，全新V2已通过并主核7315项不变；84审计、17文档/502链接/15语义、394主guard和19相邻均通过。[V2报告](../evidence/ADHOC-0034/validation-v2/report.md)；该独立报告不涵盖主亲验与实际落地，见T05 |
| 0034-T05 | S3 | [completed] | 独立通过→主亲验、原区按前置SHA落地、最终一致性收据 | T04 | 亲跑检查，H/协调增量等于Cuse，179保护项/38差异/原HEAD分支空暂存保留 | 主新副本六命令全0；实际--apply退出0仅10项安装，126 after一致、315实际链接通过；179资源/6234旧证据/38源码差异、ab43cc4/原分支/空暂存均保留。[主验收与安装](../evidence/ADHOC-0034/parent-acceptance/report.md) |
| 0034-T06 | S3 | [completed] | 受验版→0034分支适用提交/PR交付；不夹带0033、不推main/自动合并/触发CI | T05 | 重查上游/远端基准、自动触发与合并条件、精确交付树 | 已核远端37520a5/af09e3f，Actions/rules/webhooks均空；首次暂存全文件空白扫描指出7份原始diff/log格式空格，原字节与原件同，其他暂存内容适用扫描0；原收据保留。仅0034独立分支已提交ec479be、推送并创建[PR #22](https://github.com/wyizhou/TrainLab/pull/22)，实核OPEN/CLEAN/MERGEABLE、checks空、autoMerge=null；未合并。后续只补真实归档状态 |

## 流水线与并行开发安排

- 当前环节所需输入及就绪依据：官方11文件固定源、当前规则和定制记录、保护清单、规划及主审核已齐；详情见本功能证据。
- 规划审核情况及依据：T01完成，主批准上列范围/职责与C34/Cuse方案，不扩业务目标。
- 并行任务、角色、各功能独立目录与分支、各Developer写入范围（每目录最多一名）：本功能单Developer、串行；独立worktree/分支work/adhoc-0034-agentsmd-parallel，实际目录在[worktree.json](../evidence/ADHOC-0034/worktree.json)。只写8个Harness文件及本轮证据。0033原目录/分支无Developer，继续暂停。
- 共享文件、接口及重要数据规则的修改归属、消费方固定版本与交接条件：Harness H由0034唯一修改，两区消费同一已验H；主Agent独占PLAN/MEMORY/执行计划；references与source不改。Developer交回并主核后才能冻结组合。
- 受审内容、未提交差异及相关依赖的固定位置与核对方法：见当前handoff-v2.md、combination-v2-location.json及本轮交接manifest.json；C34/Cuse为实际字节物理副本，含源码差异、记录及必要公开依赖，前后逐项核SHA。历史环境3个解释器符号链接仅记原对象不跟随/复制，非本轮依赖；6231普通旧证据已复制，原6234项保持不变。受审副本无可变原件链接，变化则重新固定并新独立复验。
- 写入隔离与测试资源安排（含数据库、账号、端口等）：只有文档/规则静态检查，不使用产品、真实服务、账号或端口；环境无需安装。写入区与冻结副本分离，私有states/全局设置不访问。
- 冲突或暂停影响的任务及依赖链、恢复条件：材料/版本/保护冲突暂停T02及其后依赖，查明后按流程恢复；0033自身保持用户暂停，不因新并行规则恢复。
- 组合与冲突处理责任方、实际组合版本及相关依赖：主Agent；C34=af09e3f＋H＋分支最小协调记录，Cuse=ab43cc4＋38项原source差异/原记录＋同一H＋原区最小协调增量；实际逐文件SHA绑定交接manifest.json，不以分支名冒充版本。
- 最终组合版本的适用集成检查、独立验证和主Agent验收安排（版本变化影响结果时补查和复验）：同一全新Validator独立审两组合；主亲跑来源/链接/模板/规则语义和保护，原区落地与受验Cuse逐字一致。纯文档不启动Chrome/产品，不宣称实际多Writer运行器验收。

## 当前检查点

- 工作目录与分支：原用户工作区保留work/adhoc-0033-ai-coach/ab43cc4和脏源码；本功能独立worktree work/adhoc-0034-agentsmd-parallel，基准af09e3f，初始交付ec479be；归档状态提交不改受验H，实际PR头以最终交付收据为准。
- 验收要求与受验版本及未提交改动：H34-01～07；上游37520a5；规划29材料及当前179保护资源/38项source差异，不能用陈旧本地main9db8bb1替代origin/main。
- 最近完成：V2及主亲验通过，用户原目录同版H已实际安装并保护核对；独立0034分支已交付PR #22，未合并、无CI运行。初次失败及全部检查器首错保留；现归档本执行计划。
- 下一动作：等待用户确认是否合并PR #22或提供新需求；不自动恢复0033，不继续扩展本功能。
- 暂停原因：本功能无阻塞；0033暂停，不属于本功能待办。
- 恢复条件：本功能若发生来源/范围/保护变化先核实并按既有流程；0033只由用户明确新的恢复范围。
- PR与交付情况：当前实际目录安装、本地验收和[PR #22交付](https://github.com/wyizhou/TrainLab/pull/22)已完成。PR保持OPEN、未合并；最终只补真实状态、归档及交付收据，主核差异。

## 问题记录

| 稳定问题编号 | 对应要求与实际问题 | 已尝试修法 | 累计失败次数 | 证据及处理结果 |
| --- | --- | --- | --- | --- |
| H34-V1-001 | PLAN前置SHA与所附前置字节属不同记录时点，未分清累计比较基线/当前落地before | 方法A：独立当前before逐项匹配；V2通过并主核，闭合 | 1 | [首次报告](../evidence/ADHOC-0034/validation-v1/report.md)；旧版冻结保留 |
| H34-V1-002 | 11项prelanding未涵盖0034执行计划/证据全部目标 | 方法A：126精确目标/保留对象、before/不存在与after及追加新建；V2通过并主核，闭合 | 1 | 首验时尚未落地；现在见T05受控安装与保护收据 |
| H34-CHECK-006 | 归档提交检查误以为name-only会同时列重命名旧/新路径，实际默认仅列新路径 | --no-renames已核D/A；后续重复add已暂存删除旧路径报128，保持原删除、只暂存现存批准文件 | 2（发布暂存交接；不属Harness修复轮） | [首次定位](../evidence/ADHOC-0034/parent-acceptance/closeout-staging-recovery.json)、[暂存状态与后续处理](../evidence/ADHOC-0034/parent-acceptance/closeout-staging-step2.json) |
| H34-CHECK-005 | 发布暂存全文件空白扫描将7份原始patch/log格式空格报错 | 保留原件并逐字节核同，仅这7份做原始格式分类，其余全部暂存内容空白扫描0；未改配置或证据 | 1（发布检查适用范围） | [原报及适用复核](../evidence/ADHOC-0034/parent-acceptance/publication-whitespace.json) |
| H34-CHECK-003 | V1检查器误要求技能索引连续以前缀匹配 | 修自身检查器为批准的最小合并精确核对，受审不变 | 1（检查器） | V1报告及checker-correction保留 |
| H34-CHECK-004 | V2检查器误按basename排除嵌套manifest | 仅改为排除根manifest，7315项前后同SHA | 1（检查器） | V2首版/校正/最终integrity收据保留 |
| H34-EDIT-001 | 主更新S2状态的首次文本匹配不唯一，edit拒绝且未修改文件 | 增加行首换行锚，精确匹配后完成；要求未变 | 1（编辑工具定位） | 工具原报Found 2 occurrences；仅定位修正，无受审版本变化 |
| H34-CHECK-002 | 主组合脚本文件入口解析失败，严格UTF-8解码及bytes/text编译却成功，原因未定论 | 仅折行长字面量，AST相同；原解释器入口恢复退出0 | 1（主协调工具，不是Harness或0033产品失败） | [首错及恢复](../evidence/ADHOC-0034/prepare-first-failure.md) |
| H34-CHECK-001 | 规划检查器假定两个时点PLAN新增3行，实际2行 | 静态重构旧SHA/查完整差异后修正检查器，受审输入不改 | 1（检查器，不是升级产品失败） | [首错](../evidence/ADHOC-0034/planner-evidence/first-check-failure.md)与[复核](../evidence/ADHOC-0034/planner-evidence/check-results.json)保留 |
