# ADHOC-0034 / 0034-T02：更新已批准Harness候选

## 本次任务材料

- 类型/角色：正常开发，全新Developer，本worktree唯一Writer；不自调度、不继承旧聊天。目标是规则/文档升级，不是产品修复。
- 目标/验收/来源：H34-01～07，当前`exec-plans/evidence/ADHOC-0034/requirements.md`、`planner.md`及`plan-review.md`。官方固定37520a5132bb5f84064e04f18d7a4467ebdc9116；仅本轮T02，由主处理T03组合和后续验收/实际用户目录落地/Git交付。
- 规则与读取：PLAN→本功能执行计划→AGENTS、Developer模板、本任务及规划主审。skills项目当前无包；待引入技能自包含，不需要全局技能或安装。新规则是本次待更新内容，本次仍只一名Writer。
- cwd/分支/版本：工具配置的真实worktree，work/adhoc-0034-agentsmd-parallel，HEAD af09e3f4b7522e9826eb1655bc8a0cf58a79ba4d；主已增量更新本区PLAN、本功能执行计划及公开材料，这些非Developer改动须保留。基线/允许清单在../materials/developer-baseline.json。禁止访问或写原主工作区、旧worktree和私有states。
- 材料：固定上游在../materials/upstream/，上游SHA见../materials/upstream.json；29原规划材料manifest仍固定。当前正式批准材料以本worktree对应ADHOC-0034路径为准，不用旧current/PLAN时点覆盖现记录。
- 就绪依据：全新规划及主审核完成，T01保护/来源/分支已核。当前只开发候选H，不承诺独立通过或用户原目录已升级。
- 并行/写入：本区仅你一名Developer，无并行产品工作；原0033暂停。主不与你并发写本区，其他角色未启动。
- 共享归属/版本交接：H由本功能唯一修改；references/产品/旧证据不改；PLAN/MEMORY/执行计划由主独占。输出同一H给两组合消费，不各自修两份。
- 固定受审与资源：当前尚未启动本轮Validator；原输入/旧证据仍固定。只做标准库静态/文本/链接/规则情景检查，无产品依赖、网络业务、数据库、账号、端口或Chrome。
- 组合责任：主Agent在你交回后构造C34/Cuse及精确SHA，再新Validator及主验收。你不改原区、不自行组合旧业务记录。
- 输入→输出：已批准8文件列表→相应内容、最小diff、可复跑静态检查及安全证据、最终文件SHA和实际未提交差异。

## 唯一可写范围

以下7文件逐字节复制上游同路径，不进行润色或自创规则：

1. AGENTS.md
2. README.md
3. exec-plans/template.md
4. subagent-templates/planner.md
5. subagent-templates/developer.md
6. subagent-templates/validator.md
7. skills/web-browser-acceptance/SKILL.md（新增完整技能，仅此Markdown）

第8文件`skills/README.md`最小整合上游说明与新技能链接，删除过期“无SKILL包”表述，保留原“不复制到仓库外/不改全局/PLAN边界”说明，避免新增进度或绝对路径。

可新增本轮公开证据及检查脚本：`exec-plans/evidence/ADHOC-0034/developer/`。最终报告由output绑定。其他全部只读，尤其PLAN/MEMORY/执行计划、references、source、旧证据、.gitignore/CI/平台配置/依赖。不得Git add/commit/push、PR或清理旧目录；主负责适用Git交付。不可将上游空PLAN/MEMORY覆盖项目记录。

## 自查及预期

- 前置核真实cwd/branch/HEAD、已有差异、提供基线SHA；任何不符先保全并停报。
- 7文件与固定上游原字节及SHA一致，MIT许可完整；新增技能无缺脚本/依赖，索引可定位；references索引及技术正文未变。
- 精确diff只有8允许文件＋本轮developer/证据；主已写的协调记录、源/参考与其他tracked文件内容均不变。新/未跟踪项目文件也须枚举，不能只查git diff。
- 静态检查Markdown有效本地链接/必要锚点、模板新增九字段及角色派发字段、相对路径/通用AI表述。历史证据不作为当前规范入口；不要为了无关旧链接改旧档。
- 人工给出条款位置与情景结论：允许输入已齐时开发A并规划B；冻结A和依赖后验证A并开发已审B；独立功能隔离目录/分支与资源/共享归属齐备可并行。禁止同目录双Developer、未审/缺接口开工、独立目录却抢同数据库/端口/账号、共享项各改一份、只写分支名当冻结、分别通过代替组合验收。边界：不等无关后续依赖；依赖变化证据失效；仅暂停受影响链但不绕过累计停止线。
- 可用标准库脚本及git diff --check；不安装/运行产品或浏览器，不宣称实际测试了多Writer运行器。本次是语义规则核对，不是调度器实现。
- 首错如实保留；明确检查器/材料/实现原因，正常、错误及边界覆盖不能只数关键词。规则含义不一致应报告而非改上游规范。

## 错误边界、停止与返回

任何需清单外修改、产品/业务/授权歧义、源保护不符、环境/调度故障即停受影响项并报主；不切执行协议或自动扩大。保持本功能问题号和原失败，不能借0033旧失败额度跳过验证。修复补充字段不适用（正常升级）；H34-CHECK-001是此前规划检查器行数误设，非本次产品失败，原件保留。

返回实际8文件差异、上游/本地SHA、命令/退出/证据路径、语义情景及未运行项、任何失败/残余风险。不要代写协调记录，不把自查或临时分支更新称整个升级完成。宜15分钟内完成这项有界复制/索引/静态检查；若阻塞准确交回，不无限扩检查工程。
