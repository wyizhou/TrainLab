# ADHOC-0029 修复后独立复验

## 结论

**失败：AC-02 尚未完整满足，沿用问题编号 ADHOC-0029-V001。**

38份历史计划已补入实际任务行，ADHOC-0018、M12、ADHOC-0017等工作表的编号、状态和结果迁移可核对；但非表格任务定义仍有遗漏。M4的新任务表只搬入原“当前状态”摘要，没有承接原“串行任务与验收”中的任务级输入、排除范围及错误处理。原件在ZIP中完整保存，不能据此判定新格式的逐项迁移已经完整。

其余下表已运行的来源、保真、当前设计、格式、链接和保护回归通过。本结论仅针对当前本地脚手架候选，不是旧产品复验，也不代替主Agent最终验收。

## 冻结与检查边界

- 实际Git根与任务材料一致；分支为 `work/adhoc-0029-agentsmd-upgrade`，HEAD为 `ec36ce7bbdf9d70a509238dd771b155eb6f84261`。
- 开始、结束均逐项核对V2快照：**86个公开文件SHA-256、字节数及模式一致；326个tracked缺失路径一致；索引逻辑摘要一致**。
- V2快照自身SHA-256为 `8fc8b677bb1c95193ccd5b70c0195f638dcc57ad892923cb36db03de2124e9fa`；VC-001合同摘要与材料指定值一致。
- 索引摘要为 `ca081c39357d158a043573e2a2d8bcf0e4a8ed6249cd4b56d9cadfb06343068c`；`git diff --cached --quiet`退出0，未暂存。
- 实际根目录项为 `MEMORY.md`，没有第二个小写目录项。大小写不敏感文件系统上的Git状态仍显示 `memory.md` 修改；**未宣称已暂存大小写改名**。
- 仓库完全只读；没有运行旧检查脚本、旧source或上游程序，没有读取被忽略的私人数据。旧裁决仅作为ZIP内迁移数据核对；没有读取此前本轮Validator报告或开发辩护。

本次实际外部证据目录（仅运行定位，不是项目模板路径）：
`/private/var/tmp/trainlab-agentsmd-upgrade-tciokw12/validator-v2-checks/`。
下文证据文件名均相对此目录。目录0700，脚本及证据0600。

## 场景与实际结果

| 要求 | 类型 | 输入及独立步骤 | 预期 | 实际、退出结果 | 证据 |
| --- | --- | --- | --- | --- | --- |
| AC-01 | 正常 | 固定提交缓存与GitHub树记录；重算Git blob，对比六个目标文件字节，人工读根README许可 | 六文件原字节、MIT全文保留 | 六文件全部一致；MIT版权、授权、免责全文存在；脚本0 | `upstream.json`、`check-output.txt` |
| AC-02 | 正常 | 从ZIP原工作表独立枚举，再核38份候选的任务字段及源行；对其余六份当前设计检查结构 | 44份原计划均迁移，实际任务不能被功能级占位替代 | 44份原计划＋本次新计划共45份；必填字段无缺失；237个任务行（含19个已替代任务）字段核对通过；脚本0 | `audit.json`、`work-tables.txt`、`format-links.json` |
| AC-02 | 边界 | 比较原非表格任务定义与新任务表，重点核M4原L32–77及当前L21–24 | 非表格中的任务目标、输入输出、错误边界和检查要求亦进入新结构 | **失败**：只承接原L83–86状态摘要；人工语义结论失败，证据脚本1 | `non-table-review.json`、`non-table-output.txt` |
| AC-02/03 | 边界 | 对照原ADHOC-0018 S1/S2/S3、M12的0003n-1/2/3及0004A–D/0005/0006；核ADHOC-0017 D/C范围及M6、M10、M11状态 | 保留已有编号、明确依赖；区分局部验证、完整交付、取消和未执行 | S3仍未完成；M12未实施项为[plan]且保留0003n-3历史已发生结果；D与已替代C范围分开；M6局部validated未扩大；M10按原最终Roadmap状态映射；M11未执行项不冒称通过；人工通过 | `work-tables.txt`、`current-mapping-review.txt`、`audit.json` |
| AC-03 | 正常/边界 | ZIP每个成员与迁移前公开基准及history-manifest交叉重哈希；核源行、问题与计数文字 | 原Markdown、许可、历史结论/失败不丢失、不改判、不凭索引条数重计失败 | 58个原件完整匹配；241条当前问题引用及79条failure-index记录与源文相符；三份旧docs非执行资料及许可亦在原件集合；脚本0 | `history.json`、`audit.json` |
| AC-04 | 正常/边界 | 不使用映射数量作为预期，从原PLANS表枚举叶子；逐项比名称、结果、依赖，再查当前总览 | 原66叶子与当前FIT/报告登记完整；不恢复取消任务 | 66叶子的名称、结果、依赖一致；五个产品计划为[plan]；取消/暂停另记，非当前执行队列；脚本0、人工通过 | `audit.json`、当前 `PLAN.md` |
| AC-05 | 正常/边界 | 完整读取原memory与当前MEMORY，核文件系统目录项、决定/经验与进度分离 | 保留确认事实，旧协议退出；不新增第二记忆入口 | 当前方向、四表/UTC/完整records、隐私、历史SHM与备份观测限制保留；进度转至计划；真实大写名称唯一；人工通过 | `freeze-start.json`、`freeze-end.json`、原件与当前MEMORY |
| AC-06 | 正常 | 两份技术参考逐行diff；README前缀对比固定上游；核实际references/skills索引 | 技术正文不变，失效rules链接更新；不造技能 | 龙豆资料不变；FIT资料仅项目边界链接从rules改指PLAN；两个README保留上游基础说明；没有SKILL.md包，也没有占位条目；脚本0、人工通过 | `reference-diff.txt`、`upstream.json` |
| AC-03/04 | 正常/错误/边界设计回归 | 全文读ADHOC-0023–0028，并审阅与原件的完整diff | 四业务表、唯一ID工具、UTC、滚动七天和全文语义不变；错误范围不放宽 | activities十二列、records四列及联合键；仅running的get_running_records(activity_id)、无分页/裁剪、超限整体失败；报告各三列，保留activties_report拼写；统一实际T、非自然周、全文不转结构化摘要；未实施不记通过；人工通过 | `design-diff.txt`、当前六份计划 |
| AC-07 | 正常/边界 | 核旧目录/文件退出、有效Markdown链接及锚点，历史引用与有效入口分开 | docs与旧入口退出，当前链接可定位 | docs/source/PLANS/rules/CLAUDE不存在；有效本地链接及锚点无失败；45份计划必填结构、表宽检查通过；脚本0 | `protection.json`、`format-links.json`、`audit.json` |
| AC-08 | 正常/错误边界 | 对照preflight已确认删除；四个states公开文件仅按精确白名单核SHA/模式；对虚构路径运行check-ignore | 不恢复用户删除；四公开文件不变，其余私人路径仍忽略；CI不变 | 无额外恢复；四公开文件完全一致；六种虚构私人路径全部忽略、四公开路径均放行；.gitignore及CI与迁移前基准字节相同；脚本0 | `protection.json`、`audit.json` |
| AC-09 | 正常/错误控制 | 独立标准库检查；内存合成丢文件、坏摘要/链接、非法状态、漏任务/改编号等反例；查JSON及空白 | 检查能识别反例，不能将静态成功当完整语义通过 | 合成控制均按预期拒绝；2个当前JSON代码块可解析，无表宽/锚点/尾空白错误；独立结构检查0，但非表格语义检查失败；主Agent最终验收未执行 | `audit-summary.json`、`non-table-review.json` |
| AC-10 | 正常/边界 | 前后核HEAD/分支/索引，git diff --check、cached --quiet | 只在批准分支；无暂存/提交 | 前后绑定一致，diff退出0，暂存为空；本Validator未执行任何远端/提交动作；人工及命令通过 | `freeze-start.json`、`freeze-end.json` |

## 问题表

| 编号 | 要求 | 复现、预期与实际 | 影响 |
| --- | --- | --- | --- |
| **ADHOC-0029-V001（未完全解决）** | **AC-02**；新版AGENTS“阶段和任务写清对应目标、输入输出、错误边界、依赖和检查方法”；本次完整材料明确要求核非表格分解 | 打开history.zip内 `docs/exec-plans/completed/M4-source-root-0001-product-consolidation.md` L32–77，再对照当前同名计划L21–24。原M4-0002（L48–56）限定输入集合、SHA去重与revision重放、禁止迁移旧AI报告/邮件/运行历史，以及不能唯一绑定legacy FIT时只归档登记、不猜测；当前M4-0002仅复制原状态表L84的数量和“检查通过”，输入输出/错误边界以通用“不超出原目标/授权”代替。原M4-0003（L58–68）的任务名、合同版本、攀岩unsupported_skip、睡眠歧义处理及缺周日延期，也未进入新任务结构；当前仅原L85的已接入/PASS摘要。预期为在原编号下承接这些任务定义，不是重做产品或增加要求。 | 工作表和编号覆盖已改善，但新格式仍不能呈现原非表格任务的具体范围与错误边界；状态摘要被当作任务定义。原ZIP完整满足保全，不自动满足逐项结构迁移。不能宣布AC-02整体通过。 |

证据：`non-table-review.json`保存逐行原文及当前任务行。此问题不主张旧M4产品失败，也不要求恢复旧source、原技术方案或旧运行环境。

## 命令、检查器校准及未验证事项

实际主检查命令在项目根执行，脚本路径位于上述外部证据目录：

- `python3 …/check.py start` → 0；结束 `python3 …/check.py end` → 0。
- `python3 …/audit.py` 最终 → 0；输出 `audit-output.txt`、`audit-summary.json`、`audit.json`。
- `python3 …/non-table-review.py` → **1**，记录人工语义失败；它不是产品测试，也不是以固定措辞替代语义验收。
- `git diff --check` → 0；`git diff --cached --quiet` → 0。
- `git check-ignore --no-index --stdin` 对虚构路径 → 0，详细放行/忽略结果见 `audit.json`。

检查器开发过程如实说明：初次探测报8个源行不匹配、12个未映射状态行。复核发现分别为ADHOC-0011引用PLANS/多行列表，以及派发记录表而非工作任务表；不是候选缺陷。随后独立audit脚本先后因failure-index存在另一种row结构、M12原Roadmap为五列表而退出1；修正隔离脚本的解析后继续。其首次汇总又将总览同名行、状态说明后缀、历史包内两份参考资料误列异常；按实际源格式校正后全部结构核对通过。没有修改候选、删弱有效产品断言或把这些检查器异常称为环境故障。**结构通过仍未覆盖的M4语义缺口单独报告，没有用绿灯掩盖。**

未验证及限制：

- 不运行已删除产品的pytest、Ruff、mypy、SQLite/Provider集成、真实FIT/Goal/报告或旧产品验收；五项设计仅验证迁移语义，不是实现能力通过。
- 不读取历史外部私人证据位置，不证明删除source后的私人备份仍完整，不用前后SHA观测冒充连续OS审计。
- 来源固定到材料指定提交及缓存树；本轮没有重新请求网络确认检查结束时远端是否又有新提交。
- 既有CI仍引用缺失source，仅核保留未改；没有触发远端CI，也未核实远端部署/PR/合并状态。
- AC-09要求的主Agent最终验收尚待其本人执行，本报告不预写完成；AC-02失败应先处理。

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "已返回真实失败结论、逐AC场景、V2前后冻结证据、稳定问题ADHOC-0029-V001及未验证范围。"
    }
  ],
  "changedFiles": [],
  "testsAddedOrUpdated": [],
  "commandsRun": [
    {"command": "python3 validator-v2-checks/check.py start/end（外部实际路径见正文）", "result": "passed", "summary": "86文件、326缺失路径、HEAD/分支及索引前后均匹配V2"},
    {"command": "python3 validator-v2-checks/audit.py（外部实际路径见正文）", "result": "passed", "summary": "最终237任务行、241问题引用、79失败索引、66叶子及格式/保护核对通过；检查器早期解析错误已披露"},
    {"command": "python3 validator-v2-checks/non-table-review.py（外部实际路径见正文）", "result": "failed", "summary": "记录M4非表格任务定义未完整进入新任务结构，AC-02失败"},
    {"command": "git diff --check", "result": "passed", "summary": "退出0"},
    {"command": "git diff --cached --quiet", "result": "passed", "summary": "退出0，暂存为空"}
  ],
  "validationOutput": [
    "失败：ADHOC-0029-V001仍有非表格任务语义迁移缺口",
    "正常结构、来源、历史保全、当前设计及保护边界回归已运行并通过"
  ],
  "residualRisks": [
    "M4原任务具体输入、排除范围及错误处理仅留在ZIP，尚未完整展示于新结构",
    "旧产品、私人备份、远端CI未验证；主Agent最终验收未执行"
  ],
  "noStagedFiles": true,
  "diffSummary": "受审仓库零写入；仅生成仓库外检查脚本、证据和本报告。",
  "reviewFindings": [
    "blocker: exec-plans/completed/M4-source-root-0001-product-consolidation.md:21-24 - ADHOC-0029-V001：原非表格任务定义被状态摘要替代，AC-02未完整满足"
  ],
  "manualNotes": "独立核对原件而非沿用历史裁决；原件保全通过与新格式完整性失败分开评价。未恢复旧产品，也未重新裁决其历史结果。"
}
```
