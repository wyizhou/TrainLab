# ADHOC-0034 首次规划

仅升级协作规范、模板及项目技能，不升级调度器，不恢复ADHOC-0033。依据`../materials/requirements.md`的H34-01～07；固定官方提交`37520a5132bb5f84064e04f18d7a4467ebdc9116`。本方案待主Agent审核；以下是实施安排，不表示已经升级或验收通过。

已实核本worktree：`work/adhoc-0034-agentsmd-parallel`，HEAD `af09e3f4b7522e9826eb1655bc8a0cf58a79ba4d`，工作树及暂存区干净。原工作区`work/adhoc-0033-ai-coach`、HEAD `ab43cc4`及38项source差异只依据提供材料，未访问原目录。

## 逐文件处理与唯一归属

下表路径均相对项目根；Developer只负责允许的规则/模板/技能文件及本轮静态检查证据。PLAN、MEMORY和业务执行计划始终由主Agent独占。

| 文件 | 采用方式与检查预期 |
| --- | --- |
| `AGENTS.md` | 原字节采用固定上游；旧全局单Developer限制换成每独立目录最多一名，并包含全部并行、冻结、交接及组合验收条款。 |
| `README.md` | 原字节采用，保留完整MIT版权/许可；不据此重新许可历史产品。 |
| `exec-plans/template.md` | 原字节采用，增加九项“流水线与并行开发安排”。 |
| `subagent-templates/planner.md` | 原字节采用；阶段输入就绪、共享归属及组合要求进入派发材料。 |
| `subagent-templates/developer.md` | 原字节采用；审核依据、写入/资源范围和禁止触碰的受审内容明确。 |
| `subagent-templates/validator.md` | 原字节采用；固定未提交差异和相关依赖，内容变化不能沿用旧证据。 |
| `skills/web-browser-acceptance/SKILL.md` | 新增上游原字节完整文档；已确认技能仅此一文件，无脚本安装依赖。 |
| `skills/README.md` | 最小合并：采用上游说明和技能相对链接，删除“当前没有SKILL包”；保留项目不安装到仓库外、无全局改动及PLAN边界链接。 |
| `references/README.md` | 原样保留：现有开头已完整包含上游两行说明；保留两篇资料索引及保护说明，技术正文不动。 |
| `PLAN.md` | 不采用空模板。主Agent仅登记0034目标/H34/状态/执行计划链接和当前范围，明确0033继续暂停；保留各自原业务记录。 |
| `MEMORY.md` | 不采用空模板。主Agent仅更新“当前脚手架”版本、适用条件、日期与0034证据，保留768a3143原升级来源及其余事实。 |

主Agent创建`exec-plans/active/ADHOC-0034-agentsmd-parallel.md`，采用新模板完整字段；0033原工作区已有的`exec-plans/active/ADHOC-0033-ai-coach.md`只补必要的新安排/暂停说明：当前无Developer、输入不代表开发恢复、源码/证据固定、资源不启用、恢复须用户明确。旧任务编号、失败次数、证据及已完成的规划保留，不迁移或重写全部历史计划。0033记录不整份搬入升级PR。

## 稳定拆解与顺序

阶段：S1准备，S2落地候选，S3验证交付。本次串行单Writer，不为演示并行规则制造并行开发；主Agent承担组合及冲突处理责任。

| 任务/阶段 | 要求及责任 | 输入→输出、依赖 | 检查与错误边界 |
| --- | --- | --- | --- |
| 0034-T01 / S1 | H34-01/04/05/06；主Agent | 本方案、固定材料、两区基线→审核记录、允许路径、保护清单、0034执行计划；开发前完成 | 核官方来源/11文件SHA、分支与实际差异。原179项保护清单含175项source及4项references；保存38项source差异的路径/状态/内容摘要及旧证据摘要，不读取私有states。 |
| 0034-T02 / S2 | H34-02/03；Developer | T01批准→上表非协调文件及自查证据，固定候选H | 七个原样文件逐字节匹配；索引最小差异、许可/链接/字段、并行语义自查。禁止改产品、协调记录、旧证据或全局设置；不安装、不启动服务。 |
| 0034-T03 / S2 | H34-04/05/07；主Agent | T02交回核实→业务记录最小适配、两套组合清单及固定副本；T01时先建计划，此时完善实际版本 | 各区记录以各自真实基线增量修改，不整份相互覆盖。按下述C34/Cuse冻结，保护项变动即停，不用“分支名相同”代替冻结。 |
| 0034-T04 / S3 | H34-01～07；全新Validator | T03固定组合＋客观要求/审核拆解→两套组合的独立结论、场景/版本/证据 | 独立设计正常、禁止及边界场景，核链接、记录保真、产品保护和目标落地清单；不得修改受审材料，开发自查不作为通过依据。 |
| 0034-T05 / S3 | H34-05/06/07；主Agent | T04通过→亲验两组合、原用户工作区受控落地及一致性收据 | 亲自复跑静态/语义检查；按清单仅落地已受验文件，再核原区179项、38项差异、HEAD/分支/暂存区及旧证据不变。任一前提变动停止覆盖并重新固定。 |
| 0034-T06 / S3 | H34-01/06/07；主Agent | T05通过→仅0034分支提交、适用推送/PR、真实状态记录 | 交付前只读重查官方main与目标远端基准，检查实际自动触发规则/合并条件；差异仅允许路径，无0033源码/历史搬迁或私有数据。不得触发远端CI、直接推main或自动合并。阻塞如实记录。 |

证据按角色分开保存于`exec-plans/evidence/ADHOC-0034/`，只含公开、必要材料。任务结果核实后由主Agent先更新执行计划、再更新总计划；完成全部适用验收和交付才归档，不能先写成功。

## 两套固定组合：既交付独立分支，也升级实际工作区

**H**为上表九个非PLAN/MEMORY文件的最终确定内容（其中references保持原样）。唯一修改责任方为0034；其他目录只消费同一H，不各自修一份。

1. **C34（PR组合）**：`af09e3f`基线＋H＋主Agent在该基线上的0034协调增量与公开证据。保持原产品树不变，不合并0033分支或导入其未交付文件，不使用陈旧本地main `9db8bb1`。此处没有的0033计划不能硬加失效链接，可在0034记录说明原工作区暂停保护。
2. **Cuse（用户实际组合）**：原区`ab43cc4`＋实际38项source差异及原公开记录/必要依赖＋同一H＋主Agent针对原记录的最小协调增量。由主Agent在隔离位置先组装，不动原区产品；179项保护内容含未跟踪文件及清单中的构建文件，不能仅靠Git导出遗漏它们。原0033历史和失败不是本次升级通过的证据。
3. 两组合都记录提交、实际未提交差异、文件集合/SHA、必要公开链接依赖、固定位置及核对方式；受审副本与可写目录隔离，不能链接到可变原件。验证前后核清单。协调文件因基线不同可有明确列出的差异，但0034事实一致，H必须同字节；不要求两棵产品树相同，也不把Cuse当0033产品验收。
4. 全新Validator检查**两套实际组合**，主Agent随后亲验。原区落地前再次核目标文件前置SHA；仅复制H中的改动文件并应用已受验的协调增量/0034证据，不切分支、不stash/reset/clean、不整目录覆盖、不暂存提交0033。核落地内容等于Cuse，原区仍保留0033脏源码和空暂存区；独立Git交付只发生在0034分支。
5. 验证后规则、内容或影响结果的依赖变动，停止受影响链，重新冻结并全新独立复验；仅补真实结果/状态由主核差异。公开PR须说明“0034提交已交付”与“原工作区为同版Harness本地落地”的区别，不能只升级临时worktree便宣称完成。

## 验证场景与停止条件

- **正常**：七文件匹配上游；资料索引/许可/业务历史保留；技能可由索引定位；新执行计划九字段及角色字段齐全。规则应允许输入就绪时边开发A边规划B；A和依赖冻结后验证A、开发已审核B；独立功能隔离目录/分支且资源与归属明确时并行。
- **禁止**：同目录两名Developer即使分文件也拒绝；独立目录却共用数据库/账号/端口不能认作隔离；未审核、必要接口未就绪、共享项无唯一归属/版本交接不能开工；分支名或可变目录不能当冻结；分别通过或无文本冲突不能替代最终组合验收。
- **边界/回归**：无关后续依赖不阻塞当前规划；共享项更新须责任方交接、消费方重核；受审依赖变化使旧证据失效；只暂停受影响链但不绕过失败停止线；仅文档升级不运行Chrome，不宣称实测了多Writer运行器。验收同时检查两组合的有效本地链接/锚点、相对路径、通用AI表述及允许差异；历史失效链接与本轮新增失效链接分开，不借机改旧档。

来源变化、SHA/保护清单不符、需要产品修改/覆盖业务记录/安装或授权扩围时停止受影响工作并报主Agent；环境未恢复不重试。同类新问题沿稳定编号累计，0033失败历史既不清零，也不移作0034失败额度。交付前上游变动须主Agent处理重新定版/复验，不能静默追新或仍称旧版本为最新。

## 实际检查及未验项

- 完整读当前PLAN/AGENTS/Planner模板、任务/要求、11份上游、逐文件差异及提供的业务记录。人工确认规范、README、模板的并行条款一致；references无需修改，技能自包含且明确纯文档免浏览器。
- `python3 ../materials/planner-evidence/check_materials.py`最终退出0：manifest SHA与给定值一致，29文件、11上游文件、15个上游相对链接通过；worktree干净。`git diff --check`退出0、暂存空。
- 发现`file-comparison.json`的PLAN SHA早于`current/PLAN.md`：重构旧版SHA相符，差别仅新增0034功能行和当前任务切换行；采用manifest绑定的当前记录，不倒退。检查器首次误预期新增三行，实际两行，已纠正；原失败保存在`../materials/planner-evidence/first-check-failure.md`，最终结果见`check-results.json`。
- 未执行升级、独立验收、实际工作区保全复核/落地、远端最新性复查或Git交付；未读私有数据、运行产品/浏览器、安装、调用真实服务或Git写入。本规划无目标歧义阻塞，主Agent可审核后按T01推进；上述未验项仍是实施交付门槛。

```acceptance-report
{
  "criteriaSatisfied": [{"id": "criterion-1", "status": "satisfied", "evidence": "返回逐文件采用清单、S1～S3及0034-T01～T06、主独占记录边界、C34/Cuse固定组合验证与实际工作区落地方案。"}],
  "changedFiles": ["../materials/planner-evidence/check_materials.py", "../materials/planner-evidence/check-results.json", "../materials/planner-evidence/first-check-failure.md", "planner.md（指定输出位置）"],
  "testsAddedOrUpdated": ["../materials/planner-evidence/check_materials.py（仅静态材料检查）"],
  "commandsRun": [
    {"command": "git rev-parse --show-toplevel; git branch --show-current; git rev-parse HEAD; git status --short; git diff --cached --name-only", "result": "passed", "summary": "确认指定独立分支、af09e3f和干净工作树/暂存区。"},
    {"command": "python3 ../materials/planner-evidence/check_materials.py（首次）", "result": "failed", "summary": "检查器误预期PLAN新增三行；实际两行，无删除。原失败保留。"},
    {"command": "python3 ../materials/planner-evidence/check_materials.py && git diff --check && git status --short && git diff --cached --name-only（修正后）", "result": "passed", "summary": "29材料、11上游、15相对链接通过；worktree无改动。"}
  ],
  "validationOutput": ["manifest=e4466ad36bafcf3b839d0212e0af251c218043b601f5084491ab9982e0645885", "保护基线179项为175项source及4项references，未访问原脏工作区。"],
  "residualRisks": ["远端最新性、两套实施后组合及原工作区实际落地尚未验证；不得将规划检查称为升级完成。"],
  "noStagedFiles": true,
  "diffSummary": "只新增规划报告和静态证据；未改worktree、输入材料、产品或协调记录。",
  "reviewFindings": ["无规划阻塞；PLAN材料时点差异已精确解释。"],
  "manualNotes": "0033继续暂停；报告内的实施、验证与交付安排均待主Agent审核执行。"
}
```
