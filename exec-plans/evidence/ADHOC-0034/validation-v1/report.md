# ADHOC-0034 / 0034-T04 首次独立验证

**结论：失败，限于两组合的落地交接材料；Harness规则、模板、技能及已提供副本的保护检查通过。当前不能据此进入受控落地或宣布升级完成。**

发现2项交接问题。未修改受审文件，未访问原工作区、私有数据或全局目录；未运行Git、安装、产品、浏览器、真实服务或CI。未把Developer自查、主裁决或历史通过状态作为本轮结论依据。

## 受审版本与范围

- 官方固定来源：`https://github.com/wyizhou/agentsmd.git`，main提交`37520a5132bb5f84064e04f18d7a4467ebdc9116`；11份上游文件SHA全部匹配。
- C34：`af09e3f4b7522e9826eb1655bc8a0cf58a79ba4d` / `work/adhoc-0034-agentsmd-parallel`，387文件。
- Cuse：`ab43cc4df231ad61aa7ab30793645dcc59d4d8c2` / `work/adhoc-0033-ai-coach`，包含15修改+23新增source及原业务记录，6712文件。
- `inputs`28文件，根入口/规则/任务3文件，共7130固定文件。这里不是Git工作树，分支和原状态依据所提供的冻结材料，不冒充现场实时查询。
- `manifest.json`前后SHA均为`150e6644e2cc2301fb6a801d616679c0a06dc461f028ed0d95a7d66f8318660c`；全部7130项前后逐文件SHA无漂移，固定目录无额外文件、缺失文件或可变符号链接。
- 先读根PLAN、AGENTS、完整任务；已覆盖Validator模板18项材料所需的目标/来源、规则、版本/实际差异、冻结依赖、归属/资源、当前输入、组合责任、写入/停止边界及返回要求；实际审阅两区PLAN、0034执行计划、AGENTS、角色模板和当前技能入口。

## 问题与复现

### H34-V1-001：PLAN落地前置SHA与提供的前置字节不一致

- 对应要求：H34-04/05/07；批准拆解“两套固定组合”第4项；`validator-task.md`检查方法6。
- 位置：`inputs/combination-location.json:33`；两组合内`exec-plans/evidence/ADHOC-0034/combination-location.json:33`同样存在。
- 操作：对`inputs/baseline-Cuse/PLAN.md`计算SHA256，与`prelanding.PLAN.md`比较。
- 预期：落地保护条件能对应当前提供的原区前置字节及协调增量。
- 实际：清单值为`92fe513d84e15c6303ca1c6a22a17b0772e74b7431939ad79d3ec8ee92e28015`；提供原件值为`6efc84028652251772ab49ccb9aa425ab9f2fa3c467d4fa18e566d3af062a986`。后者自身与manifest一致，不是验证期间文件漂移。
- 影响：现有交接材料不能共同证明一个一致的落地前提；严格按清单执行应停止，而不是忽略不符后覆盖PLAN。未访问原区，不能判断两个值中哪个对应其当前状态。

### H34-V1-002：落地前置清单未覆盖本轮协调计划及证据目标

- 对应要求：H34-04/05/07；批准拆解明确落地内容包括H、已受验协调增量和0034证据；任务检查方法6要求核实际目标落地清单。
- 位置：`inputs/combination-location.json:24-36`及两组合内同名文件。
- 操作：核`prelanding`的完整键集合，与批准落地内容以及`inputs/Cuse-git-status.txt`比较。
- 预期：拟更新/新增目标有可核的前置SHA或明确“不存在”断言，不能只保护H和部分记录。
- 实际：仅列11项目标；没有`exec-plans/active/ADHOC-0034-agentsmd-parallel.md`，原状态明确该文件已存在且未跟踪；也没有任何`exec-plans/evidence/ADHOC-0034/`目标项，例如`requirements.md`。缺少这些目标的前置值/不存在断言或等价逐项交接材料。
- 影响：无法独立核对完整落地范围的防覆盖前提。未发生实际覆盖，不推断已经损坏记录；该缺口不能仅以“主以后会检查”记为本次清单通过。

**统一复现命令：** `python3 validation-tests/reproduce_handoff.py`，实际退出1；原始结果：`validation-evidence/handoff-reproduction.json`。两问题均首次发现，未修复，不涉及清零或挪用0033历史失败次数。已停止将落地前提判为通过；不受影响的只读规则/保护检查完成。

## 逐要求结果

| 要求 | 本轮结论 | 关键证据与限制 |
| --- | --- | --- |
| H34-01 来源/版本 | 固定输入范围通过 | 官方URL、提交、11文件SHA一致；冻结的复查记录仍为37520a5/af09e3f。未亲自联网查询交付时最新值，T06仍需实际复查。 |
| H34-02 并行规则/模板/MIT | 通过 | 7份原字节文件分别匹配上游；AGENTS、README、角色与执行计划模板语义一致；MIT版权/授权/保留义务/完整免责保留。 |
| H34-03 技能/资料 | 通过 | 单Markdown技能完整、索引可发现且最小合并；保留项目不外装/不改全局边界；4份references原字节保全。 |
| H34-04 业务记录保真 | 内容通过；交接失败 | C34 PLAN只新增2行；Cuse PLAN只替换本轮检查点；MEMORY各只改脚手架行；0033只追加隔离节，原编号/失败/暂停/证据正文不变。前置PLAN不一致见001。 |
| H34-05 保护 | 提供副本通过；落地前提未通过 | Cuse175source+4references及6231普通旧证据全匹配；38项source差异完整；不能推断原区、私有对象及最终落地保护已通过。 |
| H34-06 分支/隔离/范围 | 固定材料范围通过 | C34独立分支基准正确，无0033产品混入；C34 116份source与基线同SHA。所给状态无暂存项。未执行Git交付或触发CI。 |
| H34-07 独立两组合/交接 | 失败 | 两组合H同字节，记录/入口/字段/规则通过；001/002使完整落地交接未闭合。主亲验、原区落地和Git交付均未运行。 |

### 保护核对的精确边界

C34开发前374项清单中，370项存在于受审副本：360项未变，10项变化恰好是7份原有Harness文件及PLAN/MEMORY/0034执行计划；新增17项仅为新技能及本轮公开证据。未提供的4项为`states/Goal-example.md`和`states/{activities,health,verification}/.gitkeep`，与任务禁止访问states的边界区分记录：**不认定原区删除，也不声称已核其原件SHA**。

Cuse的3个旧解释器链接只核清单中的链接身份，未复制、跟随或执行；不作为本次依赖。6231普通旧证据只核字节，未读取旧裁决用于本轮结论。私有states、平台配置及原用户目录的保护，需主在后续授权范围内实际核实。

## 场景与实际检查

完整输入、操作、预期、实际条款和结果在`validation-evidence/manual-scenarios.md`，共22场景：

- 正常：开发A时规划输入就绪的B；冻结A及依赖后验证A同时开发已审核B；独立功能在目录/分支/接口/资源/共享归属齐备时并行。
- 禁止：同目录双Developer即使分文件；独立目录争抢数据库/端口/账号；未审核或必要接口未就绪；共享项重复修改；只给分支名、遗漏未提交差异或使用可变副本；依赖变化继续用旧证据；单功能分别通过代替组合独立/主验收。
- 边界：无关后置依赖不阻塞规划；共享变更先交接再重核；只暂停受影响链但保留累计停止线和用户决定；子功能不擅改功能分支；纯文档不启动浏览器/产品。
- 实际组合：两区入口、同版H、业务保真、暂停边界、落地SHA/范围、检查器反例。

实际结果：规则情景全部符合预期；落地交接两项失败。未把文字情景判断描述成并行运行器实测。

| 检查/命令 | 实际退出与结果 | 原始证据 |
| --- | --- | --- |
| 初始标准库逐项SHA/清单核对 | 0；7130项一致 | `validation-evidence/initial-integrity.json` |
| `python3 validation-tests/verify_snapshot.py`首轮 | 1；61通过/3失败，其中2项为检查器错误假设 | `validation-evidence/first-static-*` |
| 同命令，修正检查器后复跑 | 1；63通过/2有效失败；stderr空 | `validation-evidence/static-stdout.txt`、`static-stderr.txt`、`static-exit.txt`、`static-results.json` |
| `python3 validation-tests/reproduce_handoff.py` | 1；独立最小复现001/002 | `validation-evidence/handoff-reproduction.json`、`handoff-exit.txt` |
| 人工规则/记录复核 | 已执行，非进程命令；见22场景 | `validation-evidence/manual-scenarios.md`、`record-diffs.patch` |
| 最终标准库逐项SHA复核 | 0；manifest与7130项全不变 | `validation-evidence/final-integrity.json` |

附加实测结果：379处当前入口/规范/记录的本地Markdown链接存在，4处锚点有效；新执行计划9字段均非空，3阶段/6任务编号和状态一致。15个修改source文件的63个Git差异hunk与物理Cuse后置字节逐段一致，23个未跟踪source文件由保护SHA核实。4类隔离变异样本（规则污染、空业务模板覆盖、缺技能、空字段）均被相应静态检查检测。

首轮索引失败原因及校正依据完整保留于`validation-evidence/checker-correction.md`：批准最小合并保留本地标题，不能要求整个上游索引在文件开头连续原样出现；改为精确验证“上游说明/链接+原标题/边界”。仅改独立检查脚本，未改受审内容或放宽要求；PLAN有效失败始终保留。

## 未验证事项与残余风险

1. 当前失败仅证明交接材料不闭合，不证明原区已被破坏；原区实时前置状态和全部目标落地一致性尚未验证，不能直接覆盖。
2. 本轮排除的states、平台配置、3个历史链接原件未访问；旧产品功能正确性不在本次范围。
3. 上游最新性、目标分支基准及Git自动触发规则在实际交付前仍需核实；未提交、推送、创建PR或合并。
4. 主Agent亲验、原区受控落地及最终收据尚未执行；语义或相关依赖改变后，本报告不能自动用于新版。
5. 检查约10分钟完成主要证据收集，无环境故障。除隔离检查与证据外，只写本次绑定报告；无受审源码、规则或协调记录修改。

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "已返回限定范围的失败结论、H34-V1-001/002客观复现、逐要求结果和未验证风险；最终7130项SHA无漂移。"
    }
  ],
  "changedFiles": [
    "validation-tests/verify_snapshot.py",
    "validation-tests/reproduce_handoff.py",
    "validation-tests/mutations/",
    "validation-evidence/"
  ],
  "testsAddedOrUpdated": [
    "validation-tests/verify_snapshot.py",
    "validation-tests/reproduce_handoff.py"
  ],
  "commandsRun": [
    {
      "command": "初始标准库manifest及7130文件SHA核对",
      "result": "passed",
      "summary": "清单SHA匹配派发值，文件无漂移。"
    },
    {
      "command": "python3 validation-tests/verify_snapshot.py（首轮）",
      "result": "failed",
      "summary": "退出1，61通过/3失败；2项检查器索引假设错误，原日志保留。"
    },
    {
      "command": "python3 validation-tests/verify_snapshot.py（校正后）",
      "result": "failed",
      "summary": "退出1，63通过/2有效失败：PLAN前置SHA不一致及落地目标前置清单不完整。"
    },
    {
      "command": "python3 validation-tests/reproduce_handoff.py",
      "result": "failed",
      "summary": "退出1，复现两项交接问题。"
    },
    {
      "command": "最终标准库manifest及7130文件SHA核对",
      "result": "passed",
      "summary": "清单及全部受审文件仍不变。"
    }
  ],
  "validationOutput": [
    "7份上游原字节文件、同版H、完整MIT、技能/资料、9字段及379链接/4锚点通过。",
    "Cuse179保护项、6231普通旧证据、38项source差异通过；C34 116份source保持原基线。",
    "落地交接失败，不能宣布当前用户目录已升级。"
  ],
  "residualRisks": [
    "原区真实前置状态及最终落地/主亲验/Git交付未运行。",
    "4个states公开占位对象未在review中提供；私有对象及3个历史链接原件未访问。",
    "交付前上游最新性、基准与自动触发规则需实际复查。"
  ],
  "noStagedFiles": true,
  "diffSummary": "只新增独立检查脚本、隔离变异样本与证据；受审7130文件无变化。",
  "reviewFindings": [
    "blocker: H34-V1-001 inputs/combination-location.json:33 - PLAN前置SHA与所给前置字节不一致。",
    "blocker: H34-V1-002 inputs/combination-location.json:24-36 - 缺0034执行计划及证据目标前置保护项。"
  ],
  "manualNotes": "中文人工22场景记录在validation-evidence/manual-scenarios.md；历史状态仅作保真对象，不作本轮通过依据。noStagedFiles表示本review非Git目录且无Git动作，所给原状态暂存空，不声称查询了原区当前暂存。"
}
```
