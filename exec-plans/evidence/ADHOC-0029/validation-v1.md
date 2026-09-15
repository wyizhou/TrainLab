# ADHOC-0029 首次独立验证

## 结论：失败

**AC-02未满足：既有执行计划的原阶段/任务没有完整迁入新版结构。** 44份既有计划均有新模板表头，但其中38份仅使用一个`HISTORY`阶段和一个功能级任务。独立复现确认ADHOC-0018、M12原有明确分解在当前执行计划中缺失；历史ZIP原字节完整，不能替代新版计划迁移。

来源原文、历史保全、当前五份FIT/报告设计、索引链接、命名和可观察保护边界检查未发现其他阻塞。本结论只针对当前冻结的本地脚手架迁移，不裁决旧产品，也不代替主Agent最终验收。

## 受审版本与冻结

- Git根与指定工作目录一致；分支`work/adhoc-0029-agentsmd-upgrade`；HEAD为`ec36ce7bbdf9d70a509238dd771b155eb6f84261`。
- 开始及结束均独立核对：77个公开文件的SHA-256、大小、模式全部一致；326个tracked缺失路径一致；公开路径集合无多项/漏项。
- Git索引逻辑SHA-256：`ca081c39357d158a043573e2a2d8bcf0e4a8ed6249cd4b56d9cadfb06343068c`，前后不变；暂存差异为空。
- 快照SHA-256：`b49d7f667c4e9cf92039dbb22a701083e534091e00d7881f886b5077292545a4`。
- VC-001 SHA-256：`70c53a81071fd43833d032dc514a359c939bf4cdf2c36c1e518fc1bc29da34c3`。
- 实际根目录项只有`MEMORY.md`。索引仍含原小写路径，本轮没有暂存大小写改名。
- 仓库及协调记录未写入。隔离证据目录0700、其中全部文件0600。

## 场景与实际结果

下表证据均相对本报告同级`validator-checks/`目录；它是本次实际运行证据位置，不是通用项目路径约定。

| 要求 | 类型 | 输入/步骤 | 预期 | 实际与结论 | 退出结果/证据 |
| --- | --- | --- | --- | --- | --- |
| AC-01 | 正常 | 对指定commit/tree缓存十文件计算Git blob；比较六个要求原样采用的文件；人工核README | 固定来源、六文件原字节、MIT完整 | 十blob匹配；六文件逐字相同，README完整版权及许可保留。通过 | `check.py`最终0；`results.json` upstream；`manual-notes.md` |
| AC-02 | 正常 | 全量读取44份既有计划，核模板字段、当前状态、归档位置 | 结构及实际分解完成迁移 | 表头齐全、状态及目录对应合法；但38份是功能级HISTORY汇总，不能据此判完整迁移。失败见V001 | `results.json` plans；`plan-structure.json` |
| AC-02 | 边界 | 比较原ADHOC-0018 S1/S2/S3、M12 0003n-1等与当前阶段/任务表 | 保留原分解、稳定编号、各项状态/结果；暂停另记 | 两份原分解全部未进入新表，仅一个功能级任务。失败 | `semantic-check.py`退出1；`semantic-results.json` |
| AC-02、AC-07 | 错误 | 隔离内存副本将功能状态改为`[blocked]`，检查坏摘要、缺失文件与不存在链接目标 | 反例被识别，不污染受审内容 | 状态、摘要、缺文件、缺链接目标反例均被识别；不替代语义验收 | `results.json` negative_fixtures；最终命令0 |
| AC-03 | 正常/边界 | 对58份ZIP原件、历史manifest及迁移前公开副本逐字比较；逐条核失败索引源行/表行 | 原内容、历史裁决和尝试不被篡改 | 58份全部匹配，ZIP完整；44来源的79条索引记录与原件一致。完整原文保留，通过原件保真检查；不推断全部失败已结构化迁入 | `results.json` history/failure_index；`manual-notes.md` |
| AC-04 | 正常/边界 | 独立对照旧PLANS全部66叶子的名称/结果/依赖/原状态及当前PLAN；人工核取消和当前功能登记 | 目标/依赖不变，取消不复活、未实施不假完成 | 66项全部对应；五份当前计划登记，M6/M11取消及M12暂停明示，M11-0019仍为[plan]。通过 | `results.json` roadmap errors为空；`manual-notes.md` |
| AC-03、AC-04 | 正常/错误/边界 | 全文阅读ADHOC-0023至0028及636行迁移差异，核四表、唯一工具、时间和报告全文语义 | 已确认业务设计、拒绝边界、依赖保持 | activities十二列、records四列/联合键、默认123、仅running授权全量查询、UTC、实际T往前七天、两报告三列与全文文本一致；未新增工具/真实调用。通过迁移语义检查 | 人工完成，无进程退出码；`current-design.diff`、`manual-notes.md` |
| AC-05 | 正常/边界 | 实际目录项核大小写；原memory与当前MEMORY人工对照 | 真正更名、决定/事实保留，进度不再重复维护 | 仅实际MEMORY.md；来源/日期/条件与重要安全事实保留，历史进度转由计划/原件承接；未声称已暂存改名。通过 | `results.json` freeze；`manual-notes.md` |
| AC-06 | 正常 | 两份参考资料与迁移前副本逐行比较；README基础说明及真实索引检查 | 技术正文/数据/示例不改，只同步相关链接；不造技能包 | FIT资料仅旧rules链接及标签改为PLAN项目边界，龙豆原字节不变；两README保留上游基础说明；两资料索引准确，skills无SKILL.md。通过 | `reference.diff`；`results.json` references/upstream |
| AC-07 | 正常/错误边界 | 实际路径及60份Markdown、478个本地链接/锚点、182张表、JSON核对 | docs/旧入口退出，当前链接可达，格式可解析 | docs/source及旧入口不在；链接/锚点、表列数和代码围栏无异常；10个JSON文件及2个JSON代码块解析成功。通过 | `results.json` markdown；`semantic-results.json` table_errors为空 |
| AC-08 | 正常/边界 | 281项原删除基准、ignore/CI及四个公开states文件比对；仅用虚构路径探测ignore | 除授权README外不恢复删除；保护公开骨架、CI及私人忽略 | 仅README获恢复；ignore/CI及四项states内容/模式符合基准；三个.gitkeep及虚构Goal放行，FIT/DB/真实Goal等模拟路径忽略。通过可观察范围 | `results.json` protection/ignore_synthetic_paths；`git diff --check`退出0 |
| AC-09 | 流程/边界 | 全新只读独立设计并运行上述检查，不采用自检结论 | 真实记录检查，产品未运行不写通过；之后主Agent最终验收 | 本次独立验证已完成且发现失败；主Agent最终验收尚未运行，整体验收条件未闭合 | 本报告及隔离命令日志；主验收未运行 |
| AC-10 | 正常/授权边界 | 前后核分支/HEAD/索引和暂存差异；核本实例操作 | 批准本地分支、无暂存/提交/推送/PR/CI | 本实例无上述写操作；分支/HEAD/索引不变、暂存为空。通过本次可观察范围 | `results.json` freeze、`freeze-end.json` |

## 问题表

| 稳定编号 | 要求/级别 | 复现步骤 | 预期与实际 | 影响与证据 |
| --- | --- | --- | --- | --- |
| ADHOC-0029-V001 | AC-02；阻塞 | 读取`history.zip`中原ADHOC-0018第35–37行及M12第55–63行；对照当前同名计划第11–19行 | 预期原S1/S2/S3及0003n-1、0003n-2、0003n-3、0004A–D、0005、0006按新结构保留各项状态/成果/依赖/证据。实际均未迁入，表中只有HISTORY与功能级任务；当前问题表第35行也只是泛化的*-HISTORY说明 | 新文件只是历史入口摘要，无法作为已迁移的详细执行计划；总计划66叶子登记和完整ZIP均不能替代此项。`semantic-results.json`保存原/现行行号及全文片段；`plan-structure.json`显示38份采用同一汇总方式 |

这是**新版结构迁移不完整**，不是“历史原文丢失”或“旧产品验证失败”。保留原件是正确的，但仍须完成受影响计划的实际分解迁移；不要求恢复旧产品、重新运行历史验收或改变取消/暂停事实。本次未实施修复，也不推断历史累计修复次数。

## 命令与检查器自身异常

实际脚本均位于本报告同级`validator-checks/`：

- `PYTHONDONTWRITEBYTECODE=1 python3 .../check.py`：最终退出0，证据`run-3.log`、`results.json`。机械检查成功不等于功能整体通过。
- `PYTHONDONTWRITEBYTECODE=1 python3 .../semantic-check.py`：退出1，复现V001；`semantic-run.log`、`semantic-results.json`。
- `PYTHONDONTWRITEBYTECODE=1 python3 .../check.py freeze`：退出0，结束冻结复核一致；`freeze-end.log`、`freeze-end.json`。
- Git只读检查包括根/分支/HEAD/worktree、`ls-files --stage -z`、公开路径集合、`diff --cached --name-only`、`diff --check`与虚构路径`check-ignore --no-index`。后续Git命令设置`GIT_OPTIONAL_LOCKS=0`。
- 首次自编检查器因错误假设失败索引仅有line/text而退出1；实际还存在table_header/row，补充核原件后继续。第二次Roadmap解析把依赖列误当任务行，已改为第一列精确ID比较，未降低保真要求。原错误/旧输出保留于`run.log`、`run-2.log`、`results-parser-v1.json`；详情见`manual-notes.md`。这些不是仓库修改或环境恢复重试。

## 未验证事项与剩余风险

- 未运行已删除source的产品测试、业务Provider、真实FIT/Goal/数据库/凭据检查或远端CI；本次不应也没有宣称产品通过。
- 固定来源验证基于指定commit/tree和十文件缓存；未重新联网裁定此后是否出现新上游提交。
- 未读取私人states或仓库外私人备份；公开前后摘要及索引一致不构成连续OS审计，不证明全部历史外部操作或私人备份完整。
- 现有CI仍依赖已删除source。这是已知受保护现状，本轮未修改/禁用；未来进入产品或远端交付前仍需处理。
- V001未修复；主Agent最终验收和本地交付收口尚未完成。影响规则含义的修订后须重新独立验证。

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "返回独立失败结论、逐AC场景、ADHOC-0029-V001复现证据及未验证风险；已保存本报告和隔离检查证据。"
    }
  ],
  "changedFiles": [],
  "testsAddedOrUpdated": [],
  "commandsRun": [
    {"command": "python3 validator-checks/check.py（实际从仓库外完整路径运行）", "result": "passed", "summary": "最终机械检查完成；原检查器错误与修正日志保留"},
    {"command": "python3 validator-checks/semantic-check.py（实际从仓库外完整路径运行）", "result": "failed", "summary": "退出1：原执行分解未迁入当前计划，复现V001"},
    {"command": "python3 validator-checks/check.py freeze（实际从仓库外完整路径运行）", "result": "passed", "summary": "77文件、326缺失路径、HEAD/分支/索引及合同快照摘要结束复核一致"}
  ],
  "validationOutput": ["迁移验收失败：AC-02未满足；未发现其他已复现阻塞"],
  "residualRisks": ["V001尚未修复", "主Agent最终验收未运行", "产品、私人数据保全及远端CI不在本次验证范围"],
  "noStagedFiles": true,
  "diffSummary": "受审仓库零修改；仅在授权仓库外生成报告、临时检查脚本及证据。",
  "reviewFindings": ["blocker: exec-plans/active/ADHOC-0018-data-fit-year-cleanup.md:15、exec-plans/active/M12-fit-weekly-0001-rebuild.md:15 - 原分解被HISTORY汇总替代，AC-02迁移不完整"],
  "manualNotes": "完整读取冻结合同与现行角色材料，独立核当前设计和原件保真；历史裁决只作为迁移数据。人工笔记见validator-checks/manual-notes.md。"
}
```
