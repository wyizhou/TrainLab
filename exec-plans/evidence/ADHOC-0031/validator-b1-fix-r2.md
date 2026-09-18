# B0相关前置与B1固定版本独立复验

**结论：无法判断。V31-B1-001～006均不能判通过，本次未完成FIT/SQLite独立复验。**

原因是验证器设置的外层200秒命令超时打断了Python依赖安装；不是产品测试失败，也没有证据证明是网络或依赖自身故障。按首次材料的停止边界，没有重试安装、复用其他环境、临时改导入路径或切换执行模式。仅完成不依赖该安装的前端检查、语法编译及快照核对。

## 固定版本与只读边界

- 来源：`work/adhoc-0031-local-web-system`，HEAD `9db8bb1dda5922e85fe42581e27d2428dbc9f195` **加材料列出的未提交产品**。副本无Git元数据，不能另行核实来源工作区状态；未访问原仓库。
- 清单声明聚合SHA：`5cb22a1f1950c1e73c0624c2ac2981f090c246738dc53f62eb13f9a5996149d8`。**56文件的SHA-256、大小、权限在验证前后均逐项匹配**，没有受审文件变化。聚合编码算法未提供，未自行猜算法；逐文件一致性已验证。
- 两份公开协议正文SHA均匹配材料。完整阅读了指定六份首次材料；人工查看实际打包映射、默认解析/仓储/Schema校验调用链、架构门、最小Web和前端入口，没有把实现说明当成需求来源。
- 只在`evidence/`写独立检查、日志与环境，以及工具允许的构建/编译生成物；没有修改产品、原测试或协调记录，没有读取真实业务数据、调用真实服务、Git交付或远端CI。

证据根目录：`/var/folders/dh/4th4rwbd7xlg8qslxz62hbjc0000gn/T/trainlab-0031-b1-fix-r2-review-npe5w0e9/evidence/`。下文路径均相对本次固定副本。

## 安装阻塞

实际命令：

```text
cwd: 本副本根目录
UV_PROJECT_ENVIRONMENT=<本副本>/evidence/venv
UV_CACHE_DIR=<本副本>/evidence/uv-cache
/opt/homebrew/bin/uv sync --project source --python 3.12 --locked --extra dev --no-editable
```

原始日志显示选用了 **CPython 3.12.13**，解析41个包，已构建本副本的`trainlab-source`，随后仍在下载依赖。外层工具返回`Command timed out after 200 seconds`，没有取得uv进程最终退出码。只读观察确认没有该副本的安装进程继续运行，独立环境已安装分发清单为`[]`。

因此不能验证“安装的模块/Schema与受审文件一致”或“已安装发行版本与锁文件一致”，也没有可用的完整Python测试环境。详见：

- `evidence/02-install.log`：原始安装输出。
- `evidence/install-blocker.json`：超时、停止范围、未重试记录。
- `evidence/03-install-process-observation.log`：环境分发清单及进程观察。
- `evidence/commands.jsonl`：逐命令参数、实际cwd、退出结果及日志定位；超时项如实记录`exit_code: null`，不伪造退出码。

另有一次**验证器日志包装脚本**因系统`python3`不支持`datetime.UTC`启动失败，在任何受审命令启动前发生；仅修正evidence脚本兼容写法。记录在`evidence/bootstrap-note.txt`，与产品无关。

## 实际场景与结果

| 范围/入口 | 预期 | 实际结果 | 结论/证据 |
|---|---|---|---|
| 56文件及公开资料前后核对 | SHA/大小/权限不漂移 | 两次均匹配，exit 0 | 通过；`snapshot-before.json`、`snapshot-after.json`及01/12日志 |
| 前端`npm ci` | 按锁文件完整安装 | exit 0；137包；npm报告0漏洞，另有fsevents安装脚本未获allowScripts覆盖警告 | 通过，仅安装范围；04日志 |
| 前端lint / typecheck | 无静态检查错误 | 均exit 0 | 通过；05/06日志 |
| 前端原有`npm test` | 现有3测试成功 | 1文件、3测试通过，exit 0 | 通过，仅原有前端测试；07日志 |
| 前端生产构建 | 输出批准的`source/skills/local-web/web` | index、JS、CSS成功生成，exit 0 | 通过；08日志 |
| 独立生产资产检查 | React挂载点存在；实际引用的资源均在/assets/，文件非空；无额外非Web文件/符号链接产物 | 2引用、3产物匹配，exit 0 | 通过，仅产物范围；`check_frontend_artifacts.py`、10日志、`frontend-artifacts.json` |
| `npm ls --depth=0` | 顶层包无缺失错误并留实际版本证据 | exit 0 | 通过；11日志 |
| Python3.12 `compileall -q skills schemas tests` | 语法编译成功 | exit 0；不需要第三方分发，不导入产品包 | 通过，仅语法；09日志 |
| pytest / Ruff / mypy / `trainlab.check_architecture` | 完整适用检查成功 | 安装前置未完成，未运行 | 无法判断 |
| V31-B1-001 | 实际FIT字节全链解析、计数/单位/累计/未知/时间及错误拒绝 | 没有运行默认解析入口；没有生成或导入独立FIT | 无法判断 |
| V31-B1-002 | 正常安装离根导入、Schema一致；目录/导入正负向 | 仅读代码和打包映射；未运行架构违规副本 | 无法判断 |
| V31-B1-003 | 合法DTO先成功，单因素非法变异拒绝且五表不变 | 没有合法仓储基线或变异执行 | 无法判断 |
| V31-B1-004～006 | 默认123闭包、同字节整行幂等、维护SHA/冲突/事务保旧 | 未运行实际SQLite入口，不能确认无退化 | 无法判断 |
| 其余B0/B1前置 | read_view/写门、表键与列数、只读不造库、FastAPI和静态根安全 | 未运行对应包入口 | 无法判断 |

独立正常/错误/边界的具体输入设计及逐例状态在`evidence/scenarios.md`。其中所有FIT/SQLite方案明确为**未执行**；没有用DTO替身、现有fixture或口头审查冒充真实解码证据。

## 问题与剩余风险

- **未确认产品缺陷；这不等于没有缺陷。** 本次没有足够动态证据为V31-B1-001～006作修复裁决，也不另立产品007问题来代替安装阻塞。
- Python安装、逐模块/Schema字节对应、FIT协议独立构造及默认入口、SQL五表前后快照、事务与维护、架构负例、FastAPI安全回归均缺证据。已有代码防护分支的存在不能替代验证。
- 前端3测试是原有测试；独立新增检查仅证明生产资产形状与引用存在，不证明HTTP服务、浏览器交互、路径隔离或整个B1功能正确。
- npm脚本警告未通过批准额外脚本消除；已执行构建不受其阻塞。没有主动运行npm修复或升级。
- 不据此推进功能验收或声称修复完成。停止的是依赖未就绪的受影响检查，不是调整原要求。

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "如实返回无法判断结论、安装超时证据、已通过的有限范围及未验证事项；未声称B1验收通过。"
    }
  ],
  "changedFiles": [
    "evidence/run_command.py",
    "evidence/verify_snapshot.py",
    "evidence/check_frontend_artifacts.py",
    "evidence/scenarios.md",
    "evidence/install-blocker.json",
    "evidence/commands.jsonl",
    "evidence/bootstrap-note.txt"
  ],
  "testsAddedOrUpdated": [
    "evidence/verify_snapshot.py",
    "evidence/check_frontend_artifacts.py"
  ],
  "commandsRun": [
    {
      "command": "uv sync --project source --python 3.12 --locked --extra dev --no-editable",
      "result": "failed",
      "summary": "外层200秒超时中断安装；uv退出码未知，非产品测试失败；没有重试。"
    },
    {
      "command": "npm ci; npm run lint; npm run typecheck; npm test; npm run build; npm ls --depth=0",
      "result": "passed",
      "summary": "各命令exit 0，3个现有前端测试通过。"
    },
    {
      "command": "Python3.12 -m compileall -q skills schemas tests",
      "result": "passed",
      "summary": "exit 0；仅语法编译。"
    },
    {
      "command": "evidence/verify_snapshot.py before/after; evidence/check_frontend_artifacts.py",
      "result": "passed",
      "summary": "前后56文件逐项匹配；生产资产引用存在且限定于批准生成目录。"
    },
    {
      "command": "pytest / Ruff / mypy / architecture / 独立FIT与SQLite及FastAPI测试",
      "result": "not-run",
      "summary": "完整Python依赖环境未就绪，按停止条件终止受影响检查。"
    }
  ],
  "validationOutput": [
    "总体无法判断；V31-B1-001～006未完成独立动态复验。",
    "逐命令记录在evidence/commands.jsonl；全部原始输出在evidence编号日志。",
    "56文件前后SHA、大小、权限匹配；受审文件未修改。"
  ],
  "residualRisks": [
    "缺少已安装模块/Schema与固定副本逐字节一致性证明。",
    "缺少真实解码至数据库及默认事实输出、错误拒绝和五表保旧证据。",
    "前端/compileall通过不能替代B0/B1完整验收。"
  ],
  "noStagedFiles": true,
  "diffSummary": "受审56文件无变更；仅evidence证据、独立环境和允许的工具生成物。副本无Git元数据，未执行Git操作。",
  "reviewFindings": [
    "阻塞：验证器外层200秒超时打断依赖安装，未取得完整Python环境。",
    "未确认产品缺陷；V31-B1-001～006结论均为无法判断，不是通过。"
  ],
  "manualNotes": "已按停止边界终止受影响检查，未重试、未补读历史材料、未复用其他环境或补丁导入；所有证据留在本副本evidence。本报告不代替主Agent最终验收。"
}
```
