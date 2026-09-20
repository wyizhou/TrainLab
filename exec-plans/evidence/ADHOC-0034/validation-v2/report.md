# ADHOC-0034/T04 独立复验

**结论：通过，仅适用于当前两个固定组合及交接材料。** H34-V1-001/002的客观缺口本轮均已闭合，未发现阻断问题。原用户工作区尚未实际落地；主亲验与Git交付不在本报告通过范围。

## 受审版本与完整性

- manifest SHA256：`17c0becf800d820b02d5ac824a05891b4379b0070cdbf0d660397a0063b36f1d`。
- 前后逐项核对7315文件：C34 397、Cuse 6760、inputs 155、根入口3；全部匹配、无外链、固定文件均无写权限。
- C34：`af09e3f4b7522e9826eb1655bc8a0cf58a79ba4d` / `work/adhoc-0034-agentsmd-parallel`。
- Cuse：`ab43cc4df231ad61aa7ab30793645dcc59d4d8c2` / `work/adhoc-0033-ai-coach`，包含实际15修改/23新增source字节。
- 物理review根无Git；未操作原工作区、平台、全局、私有states或真实服务。旧报告/脚本仅核SHA，不作为本轮结论输入。

## 逐项结果

| 要求/问题 | 本轮证据与结论 |
|---|---|
| H34-V1-001 | 125份实际before逐项匹配清单，唯一null为新技能。当前PLAN before/after均为`278206b7…`；历史比较PLAN为`6efc8402…`，目录及handoff明确分离。通过。 |
| H34-V1-002 | 126目标严格等于8H＋PLAN/MEMORY＋0033/0034计划＋114份现有0034证据；10 install、116 retain，全部after对应真实Cuse。重建patch与landing-delta逐字一致，无目录覆盖。通过。 |
| H34-01～03 | 固定官方`37520a5132bb5f84064e04f18d7a4467ebdc9116`的11份来源SHA吻合；两组合各7份采用原字节、8H一致，完整MIT许可保留。技能单文件自包含，索引仅替换旧空目录说明，references原样保全。通过固定版本核验。 |
| H34-04 | 两MEMORY只替换当前脚手架行并保留旧来源；C34 PLAN仅加0034行及关注说明；Cuse当前PLAN retain，0033计划仅增加隔离说明，其余全文及失败/暂停历史保留。0034计划两组同版；T03/T04仍exec、T05/T06仍plan，未预写成功。通过。 |
| H34-05～06 | Cuse175 source＋4 references全部匹配；15项修改的实际diff后置片段、23项新增字节均核实。6231普通旧证据SHA保持，3历史解释器链接只核固定身份声明且不跟随。C34产品保持116份基线source，无0033源码或计划导入。通过固定材料保护核验。 |
| H34-07 | 九项并行字段、三角色材料字段完整；502个本地链接及锚点无失效；15个正常/禁止/边界场景逐条人工判读符合要求。当前两组guard/handoff/location/0034计划同字节。通过本轮独立复验。 |

## 正常、错误与边界验证

- **规则场景15项**：允许输入齐备时规划B、冻结A后验证A并开发已审B、隔离功能并行；拒绝同目录双Writer、共享测试资源冲突、未审核或接口未就绪开工、共享项各改一份、只凭分支名冻结、以单体通过替代组合验收。共享项变化需交接重核，依赖变化使旧证据失效，只停受影响链但不清零停止线。纯文档不启动浏览器。
- **受审guard主场景394项**：125目标逐项错误before、125逐项缺失before、新技能碰到同名文件/目录、126逐项污染来源、漏0034计划/漏证据/错误摘要/retain改install等清单污染、分支HEAD暂存source状态异常及保护项异常，均在任何install前拒绝且不产生安装写入。
- **正常集成**：在隔离样本中实际执行受审`main --apply`，安装恰好10项，116 retain保持字节及文件对象，126 after全部回读一致；重复用旧before安装被拒绝。
- **相邻19项**：另测已签合成错误before/after/action/retain、越界来源/目标、目标符号链接及旧链接身份；并对8个允许追加位置演练文档要求的`xb`排他新建，同名存在即拒绝、不覆盖。
- guard集成采用实际126组before/after载荷，保护项使用合成source/reference/旧证据，Git仅用固定输出适配器；真实文件读写未模拟。它不等同于真实Git或原区落地。未来追加证据的`xb`属于交接协议演练，不是已生成未来结果。

## 命令与证据

所有证据位于review根的`validation-evidence/`，脚本位于`validation-tests/`。

| 命令 | 退出/结果 | 主要证据 |
|---|---|---|
| `python3 -B validation-tests/integrity.py` | 首版1；检查器校正后0，末次0 | `integrity-start.json`、`integrity-start-corrected.json`、`integrity-final.json` |
| `python3 -B validation-tests/audit.py` | 0；84项通过 | `audit.json`、`audit.log`、`generated-landing.patch`、`record-deltas.patch` |
| `python3 -B validation-tests/docs.py` | 0；17项检查、502链接、15语义场景 | `docs.json`、`docs.log` |
| `python3 -B validation-tests/guard_cases.py` | 0；394项通过 | `guard-cases.json`、`guard-cases.log` |
| `python3 -B validation-tests/guard_adjacent.py` | 0；19项通过 | `guard-adjacent.json`、`guard-adjacent.log` |

首版完整性检查器误按basename排除所有manifest，造成两个嵌套manifest集合误报；逐项SHA本身没有失败。仅修自身过滤条件，受审输入未改；原错误证据完整保留。详细命令、人工说明及汇总另见`commands.json`、`manual-notes.md`、`summary.json`、`handoff-equality.json`。

## 未执行与剩余边界

- 未亲验或落地原用户工作区；真实分支/HEAD/空暂存、179保护项、38源码差异、全部旧证据及3个历史链接须由主在安装前后重新核对，不能重算before迎合变化。
- 未实时查询远端上游/目标基准或外部链接；交付前的最新版本、CI触发与合并条件、提交/PR/交付由主执行。本报告不能证明私有states或平台的实时状态。
- 当前126目标只针对本次固定前提；后续报告按追加范围排他新建。仅真实状态结果补写由主核精确差异，语义或依赖变化仍须重新固定并交全新Validator。
- 未运行业务、浏览器或多Writer调度器；不把文档规则核验称为业务/运行器实测。

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "完成双组合及126项目标独立复验；7315固定文件前后一致，84项审计、17项文档检查、394项guard及19项相邻场景通过，残余边界已列明。"
    }
  ],
  "changedFiles": [
    "validation-tests/",
    "validation-evidence/",
    "validator-v2.md"
  ],
  "testsAddedOrUpdated": [
    "validation-tests/integrity.py",
    "validation-tests/audit.py",
    "validation-tests/docs.py",
    "validation-tests/guard_cases.py",
    "validation-tests/guard_adjacent.py"
  ],
  "commandsRun": [
    {"command":"python3 -B validation-tests/integrity.py（首版）","result":"failed","summary":"自写集合过滤误排两个嵌套manifest；原错误保留，不是受审内容失败。"},
    {"command":"python3 -B validation-tests/integrity.py（校正及末次）","result":"passed","summary":"7315固定文件全部匹配，前后相同。"},
    {"command":"python3 -B validation-tests/audit.py","result":"passed","summary":"84项；完整落地映射、精确增量、来源及保护。"},
    {"command":"python3 -B validation-tests/docs.py","result":"passed","summary":"17项检查、502本地链接、15人工语义场景。"},
    {"command":"python3 -B validation-tests/guard_cases.py","result":"passed","summary":"394项；完整126目标及真实隔离安装。"},
    {"command":"python3 -B validation-tests/guard_adjacent.py","result":"passed","summary":"19项guard相邻和排他新建协议场景。"}
  ],
  "validationOutput": [
    "T04复验通过；H34-V1-001/002当前缺口闭合。",
    "受审C34/Cuse/inputs及根固定文件零修改。"
  ],
  "residualRisks": [
    "主亲验、原工作区真实落地及前后保护检查未运行。",
    "实时上游/远端基准、CI触发规则和Git交付未核；交付前须由主确认。",
    "3历史解释器链接仅核声明身份，未跟随；未访问私人states或平台。",
    "guard隔离测试使用Git适配器及合成保护样本，不等同真实Git或业务运行。"
  ],
  "noStagedFiles": true,
  "diffSummary": "仅新增Validator隔离脚本、样本、证据及报告；物理review根无Git，无受审文件修改。",
  "reviewFindings": ["无阻断问题；通过仅限当前固定组合及交接复验，不宣称用户目录已升级。"],
  "manualNotes": "全新独立判读当前要求及受审内容；旧报告与脚本只核SHA，不作为结论输入。检查器首错、校正及全部真实输出均保留。"
}
```
