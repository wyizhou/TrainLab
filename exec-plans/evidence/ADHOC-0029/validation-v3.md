# ADHOC-0029 V3 独立复验

## 结论

**通过，限本次冻结V3的脚手架迁移及Validator职责范围。** 稳定问题 **ADHOC-0029-V001（AC-02）本次复验通过**，未发现新的阻塞项。原非表格定义已进入当前计划同页引用，并由任务输入/错误边界和检查字段关联；不是仅保留表头、结果摘要或压缩包。

这不代表旧产品、私人数据保全或远端CI通过，也不代替主Agent最终验收。AC-09中主Agent亲自收口的后续部分尚未由本报告证明。

## 冻结与工作区

- 实际Git根为任务指定TrainLab仓库，当前分支 `work/adhoc-0029-agentsmd-upgrade`；HEAD `ec36ce7bbdf9d70a509238dd771b155eb6f84261`。
- `review-snapshot-v3.json` SHA-256：`33081f66b3fd604f19dab07b11fb99408c074b12749a78eb0d07cd9ddb79b68f`；VC-001 SHA-256：`70c53a81071fd43833d032dc514a359c939bf4cdf2c36c1e518fc1bc29da34c3`。
- 开始及结束独立复算：**96个公开文件的字节/大小/模式一致，326个tracked缺失路径一致**；非states公开Git路径清单与快照闭合，无额外或遗漏文件。
- Git索引逻辑摘要始终为 `ca081c39357d158a043573e2a2d8bcf0e4a8ed6249cd4b56d9cadfb06343068c`；`git diff --cached --name-only`为空。未改变分支、索引或受审文件。
- 实际目录项为 `MEMORY.md`，没有小写目录项；索引仍记录 `memory.md`，**不是已暂存的大小写改名**。

以下证据目录是本次实际仓库外定位，不是通用规范路径：
`/private/var/tmp/trainlab-agentsmd-upgrade-tciokw12/validator-v3-checks/`，下文简称证据目录。

## 逐项场景

| 要求 | 类型及步骤/输入 | 预期 | 实际结果及退出 | 证据 |
| --- | --- | --- | --- | --- |
| AC-01 固定上游 | 正常：核十文件缓存Git blob、上游树与来源摘要；六个直接采用文件逐字比较 | 同一固定提交、六文件原字节、完整许可 | 全部一致；根README完整MIT保留；检查退出0 | `results.json` 的upstream各项 |
| AC-02 全部计划 | 正常：从原件先找工作表与非表格分解，再核当前结构、任务关联、状态及定义投射 | 44份计划完整；原任务不由功能级HISTORY替代 | 44份结构通过；38份历史计划的228个源工作表行唯一映射，连同Roadmap/非表格收尾/后置Git共237任务；575段连续定义逐行一致；退出0 | `source-inventory.json`、`source-headings.md`、两组results、`manual-notes.md` |
| AC-02 非表格复现 | 边界：沿M4当前L21–24的任务链接回原L34/46/58/70；核输入、排除项、错误、依赖、验收 | 原定义完整，精确关联各任务 | 输入并集、禁止迁移项、legacy FIT绑定歧义、课程合同、unsupported_skip、睡眠歧义、缺周日延期均保留，依赖进入字段；通过 | `final-results.json`、M4当前文件及`manual-notes.md` |
| AC-02 错误反例 | 错误：内存副本删除legacy绑定边界/睡眠歧义、错换任务锚点、移除全部定义；另测坏状态/摘要/丢文件 | 检查应拒绝，不能只看旧包或表头 | 四个M4实质变异均拒绝；正常原件接受；其他五个检查谓词反例通过；退出0 | `final_checks.py`、`final-results.json`、`results.json` |
| AC-03 编号/历史 | 正常及边界：58源文件对迁移前基准逐字核；失败索引回原行；复核取消与局部结果 | 不丢历史、次数不清零、不改判 | 58原件全部保真；79条失败索引回源吻合。ADHOC-0018保持INCONCLUSIVE；ADHOC-0017 D/C范围分离；M11多版本、M12局部/后置交付与未执行项不混套；退出0及人工通过 | `results.json`、`final-results.json`、`manual-notes.md` |
| AC-04 总计划 | 正常：从原PLANS表头独立解析全部叶子及依赖，核新PLAN登记与状态 | 66叶子、依赖/成果和暂停取消保留，登记当前五计划 | 66叶子及依赖全部对应；当前五计划仍[plan]；24→25→26及报告依赖24保留，不强迫28依赖27；退出0及人工通过 | `regression-results.json`、`five-plan-diff.md` |
| AC-04/03 当前设计回归 | 正常/边界：完整读取五份候选及源差异，核ADHOC-0023、PLAN、MEMORY的一致性 | 四表、唯一工具、UTC、滚动七天、全文及权限语义不变 | 12/4/3/3列、records联合键/原顺序、仅activity_id查询全部running记录、超限整体失败、同一T往前7天、全文summary均保持；未实施不冒充通过；人工通过 | `five-plan-diff.md`、`manual-notes.md` |
| AC-05 记忆 | 正常/边界：旧memory全文对新MEMORY，核实际目录项 | 保留决定/事实/经验，进度归计划，无第二入口 | 关键事实和历史限制保留，旧进度定位到计划/原件；实际大写名称确认，未动索引；人工及自动通过 | `manual-notes.md`、`results.json` |
| AC-06 参考与技能 | 正常：原两资料逐字差异、两README前缀及实际目录 | 仅同步链接，真实索引，无假技能 | Garmin仅一处rules链接换为PLAN项目边界，龙豆原字节不变；两README含上游基础说明；skills只有README；退出0 | `regression-results.json`、`results.json` |
| AC-07 旧入口退出 | 正常/错误边界：核实际旧目录、Markdown链接/锚点/表列/围栏/JSON/空白 | docs及旧入口不存在，有效本地链接可定位；历史旧路径不重新激活 | docs、PLANS、rules、CLAUDE不存在；1197个本地链接/锚点检查无坏链；格式/JSON与diff检查通过；退出0 | `results.json`、`regression-results.json` |
| AC-08 保护边界 | 正常/边界：对照迁移前公开基准；只用四公开states文件与虚构路径测ignore | 保留既有成果、删除、CI及隐私忽略 | 原281个缺失基准除获准新增README外没有恢复；CI、.gitignore、四states摘要不变；四公开项放行，五虚构私人路径忽略；退出0 | `results.json`、`regression-results.json` |
| AC-09/10 本地检查及授权 | 正常：独立标准库检查、人工审查、最终冻结、Git索引与HEAD核对 | 只读本地，无产品/远端动作，真实报告结果 | 三组最终检查425/425、361/361、90/90；末次冻结3/3。无暂存、提交、推送、PR、CI、Provider或旧产品运行；主最终收口待其执行 | `freeze-end.json`、`git-end.json`、各运行日志 |

上述876项是本次文档检查断言，**不是876项产品测试**。

## 稳定问题与复现结果

| 编号 | 要求 | 复现路径、预期与实际 | 影响/结论 |
| --- | --- | --- | --- |
| ADHOC-0029-V001 | AC-02 | 从history.zip读取M4原L32–77及其他37份源任务分解，再从当前任务输入/检查列定位同页原定义。预期任务定义完整且可关联；实际237任务均关联完整公共定义，源有同编号标题的10项另外精确指向其段落，原连续文本投射无缺行。M4删定义/错关联合成反例均被拒绝 | 本次修复后复验通过；未发现剩余阻塞，不要求恢复历史产品 |

特别核查：ADHOC-0011非表格需求及技术合同、M8设计合同、M9分期合同、M11多版合同均已在对应计划同页完整引用；引文外明确“非当前流程/非新授权”，没有以旧命令、旧角色或旧裁决驱动本次工作。详细定位与判断见 `manual-notes.md`。

## 实际命令与异常处理

全部脚本由本Validator在证据目录新建，使用系统Python标准库，不运行旧检查器。

1. `python3 <证据目录>/check.py`：最终退出0，425/425；`run.log`、`results.json`。
2. `python3 <证据目录>/regression.py`：最终退出0，361/361；`regression.log`、`regression-results.json`。其中实际执行 `git diff --check` 和仅虚构路径的 `git check-ignore --no-index --stdin`，均退出0。
3. `python3 <证据目录>/final_checks.py`：最终退出0，90/90；`final.log`、`final-results.json`。
4. `python3 <证据目录>/check.py --freeze-only`：退出0，3/3；`freeze-end.log`、`freeze-end.json`。
5. `git rev-parse --show-toplevel`、`git branch --show-current`、`git rev-parse HEAD`、`git ls-files --stage -z`、`git diff --cached --name-only`：退出0，末次原始输出见 `git-end.json`；起始另执行只读status/worktree核对。

没有隐藏初次检查器异常：第一组初跑3个结构解析误报、第二组初跑6个M12依赖列误读，原结果均保留；第三组首次Python因failure-index部分条目使用row结构而KeyError退出1。经原件与实际字段证明后，仅修正仓库外检查器并重新运行，候选未改、验收未降低。详见 `manual-notes.md`，不把首次失败记为通过。

## 未验证范围及残余风险

- 主Agent最终验收与后续真实交付尚未执行；此轮按授权不暂存、提交或进行远端动作。
- 没有运行已删除旧产品或产品pytest/Ruff/mypy、数据库、模型、API、Provider、邮件或CI；既有CI仍引用缺失source，后续实施须处理，不能宣传产品通过。
- 不读取/枚举私人states、真实Goal/FIT/凭据/报告或历史私人备份。公开摘要前后相同不等于连续OS审计，也不证明被删私人副本可恢复。
- 上游按冻结提交和缓存Git树/blob核对，未再次联网查询实时最新版；未安装浏览器/Markdown渲染器，版式采用结构检查与人工阅读。

```acceptance-report
{
  "criteriaSatisfied": [
    {"id":"criterion-1","status":"satisfied","evidence":"已给出V3只读复验通过结论、ADHOC-0029-V001复验结果、逐AC场景、876项最终文档检查与未验证范围；证据见validator-v3-checks。"}
  ],
  "changedFiles": [],
  "testsAddedOrUpdated": ["仓库外validator-v3-checks/check.py","仓库外validator-v3-checks/regression.py","仓库外validator-v3-checks/final_checks.py"],
  "commandsRun": [
    {"command":"python3 <证据目录>/check.py","result":"passed","summary":"最终425/425；初次3项检查器误报及修正保留"},
    {"command":"python3 <证据目录>/regression.py","result":"passed","summary":"最终361/361；初次6项表列解析误报保留"},
    {"command":"python3 <证据目录>/final_checks.py（首次）","result":"failed","summary":"Python退出1：部分失败索引采用row而非line结构；仅修正隔离检查器"},
    {"command":"python3 <证据目录>/final_checks.py（修正检查器后）","result":"passed","summary":"退出0，90/90"},
    {"command":"python3 <证据目录>/check.py --freeze-only","result":"passed","summary":"96文件、326缺失、HEAD/分支/索引及两摘要末次一致"},
    {"command":"git diff --check; git diff --cached --name-only","result":"passed","summary":"空白检查无错误；无暂存文件"}
  ],
  "validationOutput": ["44份迁移计划格式通过；38份历史计划237任务和575段原定义关联完整","58份原件字节保真、66个Roadmap叶子与依赖保留、1197本地链接无坏链","五项未实施设计及保护边界回归通过"],
  "residualRisks": ["主Agent最终验收尚待执行","未验证旧产品、远端CI或私人数据/备份；前后公开摘要不是连续审计","未联网刷新上游HEAD或进行浏览器渲染测试"],
  "noStagedFiles": true,
  "diffSummary": "受审仓库零写入；仅仓库外独立检查脚本、证据与报告。",
  "reviewFindings": ["无阻塞项；ADHOC-0029-V001本次复验通过"],
  "manualNotes": "人工核查M4及其他非表格定义、全源分解、历史版本隔离、五计划全文差异与MEMORY职责；检查器初次异常和校正依据完整保存在validator-v3-checks/manual-notes.md。"
}
```
