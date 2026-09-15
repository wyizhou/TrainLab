# ADHOC-0030 T4 独立复验

**结论：通过，限当前冻结磁盘公开候选及本地交付前提。** AC-06实际暂存、提交、推送、PR及即时远端条件未验证，不能据此宣布整体交付完成。未发现当前有效阻断问题。

## 版本与冻结

- 根目录：`/Volumes/DiskOther/Code/TrainLab`；分支：`work/adhoc-0029-agentsmd-upgrade`；HEAD：`ec36ce7bbdf9d70a509238dd771b155eb6f84261`。
- 完整读取AGENTS、Validator模板及RC-0030-01/审核拆解/载荷定义；判断依据为当前合同、实际文件及独立检查，不采用归档报告的通过/失败结论，也未执行载荷中的脚本。
- 固定快照SHA-256：`71e0537431f3e3f49d9cf27935b73c97cd27b8ebff84557359bce34838858183`。
- 前后118公开路径、各文件SHA/bytes/lstat模式、327 tracked缺失、HEAD、分支均一致。候选树按公开且未被忽略的磁盘路径核对，states不遍历，只核四个指定文件。
- `git ls-files --stage -z`原始stdout（含NUL）的SHA-256为`ca081c39357d158a043573e2a2d8bcf0e4a8ed6249cd4b56d9cadfb06343068c`，与快照及原baseline同口径一致。
- `.git/index`容器SHA-256另观测为`f14c937ccdcc50daae2bc6ad038ed4d4e3f21e50eae70b6732e39cd1b225c2a7`，前后亦一致。没有将两个不同载荷互比。F-0030-V01对应的当前摘要核验入口通过。
- 暂存为空；索引仍是`memory.md`，磁盘候选是`MEMORY.md`。大写索引落实和完整暂存树比对仍属T5前提，未宣称Git已完成改名。

## 场景与证据

隔离证据目录：`/private/var/tmp/trainlab-ci-pr-fydlv9x0/validator-v2-checks/`，目录0700、文件0600。下表文件名均相对此目录。

| 要求/场景 | 独立方法、预期及实际结果 | 命令/退出结果与证据 |
| --- | --- | --- |
| AC-01 正常 | 唯一新增配置删除为ci.yml；118候选中无workflow，无替代可执行CI配置 | `python3 …/check.py`退出0；`results.json` |
| AC-02/03 正常、保护边界 | 原110文件中101文件原字节不变，8协调文件变化，1个ci.yml删除；新增9个本任务计划/证据；原326缺失全部保留 | 同上；`baseline`字段、`coordination.diff` |
| AC-02 人工语义核对 | 亲自逐段读完8文件完整差异：新增授权/交付衔接、旧CI退役与适用本地检查说明；未更改产品字段、接口、时间、权限、行为或五项产品未实施状态。ADHOC-0029及更早文件原字节不变 | 人工完成；`coordination.diff`；五项状态自动断言见`boundaries.json` |
| AC-04 正常、隐私边界 | 核全部118候选；6个ZIP共172成员逐项路径/类型检查并读取扫描，均为Markdown、Python、JSON、diff、log或txt；无链接文件、路径逃逸、加密成员或非UTF-8内容。仅作为载荷，不执行或采用其结论 | `check.py`退出0；`results.json`中成员清单；独立补充扫描退出0，`privacy-extra.json` |
| AC-04 秘密线索 | 私钥、常见Git令牌、AWS键、Bearer及秘密赋值；补扫签名URL、JWT、精确经纬度JSON线索，均无命中 | 同上。此为有限模式扫描，不证明绝对无秘密或无任何个人信息 |
| AC-03/04 正常/错误 | 大小写候选无碰撞；四个states骨架允许；13个合成私人路径（Goal/FIT/health/token/sidecar等）被实际gitignore拒绝；白名单拒绝12种越界/旧入口/替代CI/符号链接输入 | `python3 …/boundaries.py`退出0；`boundaries.json`。合成路径仅传入检查，不读取私人文件 |
| AC-05 正常 | 39个JSON成功解析；67个Markdown围栏闭合、2个JSON围栏成功解析；显式相对Markdown链接的文件目标均存在；111个普通文本无空白诊断 | `check.py`及`boundaries.py`退出0；`results.json`、`boundaries.json` |
| AC-05 补丁边界 | 对旧closeout-status.diff执行no-index空白检查，实际退出3，准确复现19处；19行全部是单空格的合法空行上下文标记。只解析`git apply --numstat --`退出0，涉及4文件；原字节SHA保持`da43fed94af46c16777a65bc7183879c614d8b8f17ac7e2012cc2ddc636739f9` | 完整命令、行号及stdout见`boundaries.json`，未应用补丁 |
| AC-05 错误拒绝 | 合成损坏hunk计数，解析退出128并报corrupt patch；普通文本合成行尾空格，no-index检查退出3。没有全局放宽空白规则 | `boundaries.json`。普通无诊断文本no-index退出0（空文件）或1（存在差异），不把1误报成空白错误 |
| AC-03/05 最终冻结 | 再核118文件全部字段、缺失集合、版本、NUL索引条目、容器及空暂存 | 独立末次Python命令退出0；`final-freeze.json` |

## 检查过程中的自检纠正

两次隔离验证脚本的自身断言错误均已明确定位，不属于受审候选失败或环境故障：

1. 首次`check.py`退出1，错误地将受忽略的缓存/DS_Store也算入公开树；文件摘要、327缺失、HEAD/分支/索引均匹配。检查器改用实际`git check-ignore --stdin -z`排除忽略项后公开集合恰为118。未读取这些缓存/数据库内容，也未把它们加入候选。
2. 首次`boundaries.py`退出1，错误地要求无空白诊断的no-index命令必须返回0；实际`.gitignore`返回1但stdout/stderr为空（只有文件差异）。修正退出语义，仍保留严格空白配置及坏普通文本退出3的反例。未改变受审文件或标准。

## 未验证事项与交付条件

- 主Agent仍须亲验、精确暂存118候选与明确删除、落实MEMORY大小写，并逐路径核暂存/提交树；禁止宽泛暂存把忽略数据或其他路径带入。
- 未联网，未读原始remote-preflight/API凭据响应；远端自动触发、规则集/保护条件、推送及PR真实状态无法判断，须交付前即时核对；不要求绿色CI。
- 链接检查覆盖显式Markdown相对链接文件存在性，不包括远端URL可达性及所有渲染器的锚点规则。
- 只核四个公开states文件；未读取或遍历私人states、FIT/GPS/真实Goal/健康/报告/凭据，未调用业务、安装依赖、运行旧产品测试、写Git或执行归档脚本。旧产品功能未验证。
- 冻结检查是前后观测，不是持续文件系统审计；秘密扫描无命中不构成绝对隐私保证。

```acceptance-report
{
  "criteriaSatisfied": [
    {"id": "criterion-1", "status": "satisfied", "evidence": "完成T4独立磁盘候选复验，记录正常、错误、边界、前后冻结和未验证交付条件。"}
  ],
  "changedFiles": [],
  "testsAddedOrUpdated": [],
  "commandsRun": [
    {"command": "python3 validator-v2-checks/check.py", "result": "passed", "summary": "纠正检查器公开集合口径后退出0；118文件冻结、101原字节保护、完整候选及ZIP扫描"},
    {"command": "python3 validator-v2-checks/boundaries.py", "result": "passed", "summary": "纠正no-index退出语义后退出0；19处合法补丁标记、坏补丁/普通空白拒绝、白名单及状态检查"},
    {"command": "git diff --no-index --check /dev/null exec-plans/evidence/ADHOC-0029/closeout-status.diff", "result": "failed", "summary": "预期复现退出3与19处诊断；只解析确认是合法上下文标记，未修改历史字节"},
    {"command": "git apply --numstat -- < closeout-status.diff", "result": "passed", "summary": "退出0，只解析4文件补丁，不应用"},
    {"command": "独立补充隐私扫描及末次冻结Python命令", "result": "passed", "summary": "均退出0；无新增秘密线索命中，118文件/327缺失/版本/条目不变"},
    {"command": "远端预检、暂存、提交、push及PR", "result": "not-run", "summary": "本角色未授权；须主Agent完成"}
  ],
  "validationOutput": ["当前冻结磁盘候选与本地交付前提通过；整体Git/PR交付尚未验证"],
  "residualRisks": ["秘密模式扫描不是绝对隐私证明", "需主验收后落实MEMORY索引改名及精确暂存树核对", "即时远端条件和实际Git/PR交付未验证"],
  "noStagedFiles": true,
  "diffSummary": "未修改受审内容；只写隔离检查证据和指定报告。",
  "reviewFindings": ["无当前有效阻断问题；F-0030-V01按同一载荷独立核验通过"],
  "manualNotes": "亲自核对8文件完整差异；不采用归档结论，不执行旧脚本；两次检查器自身断言纠正及原退出结果已如实记录。"
}
```
