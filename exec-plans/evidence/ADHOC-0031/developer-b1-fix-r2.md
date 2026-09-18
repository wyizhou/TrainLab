# B1 第二轮有界修复：开发结果

**本轮实现与自查完成，尚未独立验收。** 原91项反例回归现为91通过；产品测试157通过（原92项覆盖＋新增65项）。没有推进B2～B7、修改协调记录、Git交付或访问真实业务数据/服务。本轮到此结束，不自动续轮。

## 版本、授权及证据

- 分支：`work/adhoc-0031-local-web-system`；HEAD仍为`9db8bb1dda5922e85fe42581e27d2428dbc9f195`，产品仍未提交、未暂存。
- 入场核对原53文件SHA、大小、权限和产品集合完全匹配，聚合SHA为`25f7f11d0e31787bddde584f7103de90c7a95522e5b7379521c6ef9affaa8d0f`；历史zip SHA/CRC匹配。
- 最终56文件清单包含`.gitignore`及55个source文件；相对基线修改10、新增3、删除0。聚合SHA：`5cb22a1f1950c1e73c0624c2ac2981f090c246738dc53f62eb13f9a5996149d8`。161个受保护仓库文件字节未变；前端、工具索引、依赖锁、仓储/事务实现均未改。
- 已按材料读取当前计划、原合同及主审核、授权、历史裁决/反例、固定实现与公开协议资料；项目及所查全局技能位置未发现适用SKILL.md，没有引入技能或全局配置。
- **累计历史不清零**：B1首次验收失败1、首轮修复/复验失败1，本轮为修复尝试2；关联V31-B0-006此前两种方法未闭合，本轮为公共合同累计尝试3。旧通过和失败材料均保留，没有将本轮自查记作独立复验。

全部证据根：`/tmp/trainlab-b1-r2-0vQR45`（macOS正规路径为`/private/tmp/trainlab-b1-r2-0vQR45`）。

- `pre-implementation-analysis.md`：实现前原因分析及不同方法。
- `baseline.json`、`red/`：53文件旧固定实现、旧包独立安装与原脚本。
- `final-snapshot.json`、`green/review-snapshot.json`、`green/source/`：最终固定实现。
- `product.diff`、`diff-summary.json`、`protected.json`、`final-audit.json`：完整逐路径差异与边界核对。
- `commands.jsonl`、`commands.md`：每次实际命令的完整参数、cwd、环境、退出码、耗时及日志路径。
- `fixture-and-check-notes.md`：夹具同步理由、检查脚本路径适配及所有中途失败。
- 归档：`/tmp/trainlab-b1-r2-0vQR45/evidence.zip`，737文件、1,421,803字节，SHA-256 `4af8ba7576f0e192433adfd85c2b2e80d75b810095b2e92269714dc08c302ba1`，zip CRC通过。包含红/绿源码、脚本、日志、XML、公开资料和小型合成FIT/SQLite；环境/缓存/构建中间文件及超过1MiB的合成库不入归档，原目录仍保留且可由脚本重建。

## 逐问题方法与实测

| 问题 | 根因与本轮不同方法 | 已测结果 |
|---|---|---|
| V31-B1-001 | 不再仅数消息存在：协议层拒绝字段号255，session/lap检查四个必需时间字段的存在和编码；空activity、空record及仅timestamp的record拒绝。区分字段未定义、invalid和有效0，允许有采样字段的missing/relative时间。 | 原4个结构反例拒绝；新增逐一缺必需字段、空消息、非法字段及首次不建库/已有五表保旧通过；合法null、Developer-only采样及0未退化。 |
| V31-B1-001 | 累积器按直接数组序列建立基点，invalid不重置；同消息先读取直接基点再展开，避免Definition字段次序影响结果；跨链隔离。date_time/local_date_time按数值域处理，不把min边界当枚举。 | 原HR数组得到12/13秒；数组→压缩→直接→压缩、invalid尾项、同消息两种字段顺序及跨链通过。0、下界前/等于/后、最大有效时间及local时间下界保持raw整数。 |
| V31-B1-002 | 从仅枚举几个目录名/AST形态改为目录职责检查、脚本后缀/shebang/执行权限识别和sys.path写操作分析；覆盖赋值、切片/下标、别名和原地修改，允许只读路径访问。 | 原3个漏检均拒绝；新增12类违规与合法文档/前端/测试/Schema资源、只读sys.path通过。未重新迁移包，也无路径补丁。 |
| V31-B1-003 | 共享模块直接引用同一固定SDK Profile，对Message和Definition执行规范编号/名称/单位/形式及父组件对应；再核chain/definition/source和实际时间字段→time_evidence→SQL的逐值一致性。不是只补某个名称if，也没有复制影子Profile或导入私有解析器。 | 原3个仓储反例拒绝；新增18种完整合法基线单因素变异，包括同时改名、字段改号、定义碰撞、时间字段缺失/重复/单位/形式矛盾，均拒绝且五表内容不变。未知消息null身份正常保存。 |
| 004/005/006 | 不改默认123、普通幂等或维护实现，只回归。 | 原91项中的最小字典/组件闭包、同SHA异名五表与库字节不变、真实维护SHA/报告冲突/无报告更新/失败回滚均通过。 |

原顺序、重复/逆序时间、30,007条全量采样、多session/链、标准/Developer重定义、未知消息/bytes/大整数、原生分段、事务失败、read_view写入门、公开Schema及真实ASGI静态产物回归均通过。

**原测试同步没有删除或降低断言。** 两个测试文件的原夹具存在四类不实表示：session字段3被叫heart_rate、虚构derived组件、多session缺必需摘要时间、绝对时间DTO缺实际timestamp字段。已分别换成Profile真实身份/组件及补齐必要证据；原默认123/闭包、30秒多session、25,001条逐行原序等断言保留。新增对应负向测试验证原缺陷确实被拒绝。三份历史独立脚本及独立编码器逐字节未变。

## 红绿与实际命令

下面`E=/tmp/trainlab-b1-r2-0vQR45`，`G=$E/green`，`P=$G/evidence/venv/bin/python`；完整展开命令和所有中间检查见`commands.md/jsonl`。

| cwd | 命令 | 退出/关键输出 |
|---|---|---|
| `$E/red` | `UV_PROJECT_ENVIRONMENT=$E/red/evidence/venv UV_CACHE_DIR=$E/uv-cache uv sync --project source --python 3.12 --locked --extra dev --no-editable` | 0；Python3.12.13、正常非editable安装40包 |
| `$E/red/evidence` | 旧环境Python运行三份历史脚本`-m pytest test_independent.py test_followup.py test_final_boundaries.py -q -p no:cacheprovider --basetemp red-complete-temp --junitxml red-complete.xml --tb=short` | **1；12失败/79通过**，精确复现全部原反例 |
| 工作区`source` | 旧环境Python运行`-m pytest tests/fit/test_b1_r2.py -q -p no:cacheprovider`，完整参数见日志 | 实现前61项：**1；48失败/13通过**；最终65项对旧固定安装作控制重放：**1；52失败/13通过** |
| `$G` | `UV_PROJECT_ENVIRONMENT=$G/evidence/venv UV_CACHE_DIR=$E/uv-cache uv sync --project source --python 3.12 --locked --extra dev --no-editable --reinstall-package trainlab-source` | 0；强制重建安装最终包，不使用旧wheel |
| `$G/evidence` | `$P check_install.py` | 0；**28份安装模块/Schema逐字节匹配，40包版本匹配锁文件** |
| `$G/source` | `$P -m pytest tests -q -p no:cacheprovider --basetemp $G/evidence/product-final-temp --junitxml $G/evidence/product-final.xml --tb=short` | 0；**157通过、2警告** |
| `$G/evidence` | `$P -m pytest test_independent.py test_followup.py test_final_boundaries.py -q -p no:cacheprovider --basetemp green-final-temp --junitxml green-final.xml --tb=short` | 0；**91通过、2警告** |
| `$G/source` | `$P -m ruff check --no-cache .` | 0；All checks passed |
| `$G/source` | `$P -m mypy -p trainlab -p tests --no-incremental` | 0；34文件无问题 |
| `$G/source` | `$P -m compileall -q skills schemas tests` | 0 |
| `$G/source` | `$P -m trainlab.check_architecture` | 0；架构和公开Schema通过 |
| `$G/source/frontend` | `npm ci --cache $E/npm-cache`；`npm run lint`；`npm run typecheck`；`npm run test`；`npm run build` | 各0；0 vulnerabilities、3测试通过、React生产构建输出既定web目录 |
| `$G` | `$P evidence/check_snapshot.py after` | 0；56文件无差异，聚合SHA一致 |
| 工作区根 | `git diff --check`；`git diff --cached --exit-code`；`git status --short` | 各0；索引为空，既有未提交状态保留 |
| 工作区根 | `python3 $E/final_audit.py` | 0；工作区/绿副本匹配、旧基线未变、独立脚本未变、161保护文件未变 |

关键原始日志：`red-historical-91-complete-materials.log`、`red-new-boundaries-executable.log`、`red-final-65-baseline-control.log`、`green-install-final.log`、`green-parity-final.log`、`green-product-final.log`、`green-historical-91-final.log`、`green-{ruff,mypy,compile,architecture}-final.log`、`green-frontend-*.log`。

合成原件/库：`red/evidence/red-complete-temp/`、`red-final65-temp/`、`green/evidence/product-final-temp/`、`green/evidence/green-final-temp/`；长集合原始库仍在相应测试目录中。

## 未通过历史与残余风险

- 全部中途失败保留：安装身份脚本曾把`/tmp`与`/private/tmp`误当不同目录；仅在副本中正规化路径后通过。参考文件最初复制层级错误使第一次历史重放多1个失败，修正资源位置后精确复现12项。新增测试最初有一个多余括号导致收集退出2，修正语法后才取得有效红灯。首次实现mypy有1处字典类型推断错误，补显式类型后重装、完整回归通过。没有环境故障盲目重试，也没有把这些命令记作通过。
- Starlette/httpx、anyio弃用警告和npm的fsevents脚本提示未隐藏；未因提示升级依赖或改全局配置。
- 尚未由全新Validator独立复验，也未由主Agent最终验收；不能据本报告完成B0/B1或清零历史失败。
- 未穷举所有124种Profile消息、设备、未知厂商语义或随机协议组合；未知内容只证明可解码结构保留。实测长集合为30,007条，不承诺无限容量。
- 架构门是静态常见形态检查，不是任意动态反射/混淆代码的安全证明；正常包安装不靠sys.path。
- 没有私人FIT、Garmin/AI真实请求、真实浏览器或8080监听验收；ASGI与前端生产产物实测不能替代后续完整业务功能。

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "仅001/002/003及同类边界，修改10新增3删除0且全部在允许路径；final-audit.json证明161个保护文件未变、HEAD/分支/索引保持；B1尝试2及公共合同累计尝试3历史明确保留。"
    },
    {
      "id": "criterion-2",
      "status": "satisfied",
      "evidence": "提供53/56文件快照、逐路径diff、12失败/79通过红灯与91通过绿灯、新65项旧包控制52失败/13通过及最终157通过、正常安装28文件匹配、逐命令日志和全部未通过历史；明确自查不是独立验收。"
    }
  ],
  "changedFiles": [
    "source/README.md",
    "source/schemas/contracts.schema.json",
    "source/skills/_shared/scripts/trainlab/check_architecture.py",
    "source/skills/_shared/scripts/trainlab/contracts/json_validation.py",
    "source/skills/_shared/scripts/trainlab/contracts/fit_profile.py",
    "source/skills/_shared/scripts/trainlab/contracts/fit_consistency.py",
    "source/skills/fit-store/README.md",
    "source/skills/fit-store/scripts/parser.py",
    "source/skills/fit-store/scripts/profile_fields.py",
    "source/skills/fit-store/scripts/wire.py",
    "source/tests/fit/test_additional_boundaries.py",
    "source/tests/fit/test_b1_regressions.py",
    "source/tests/fit/test_b1_r2.py"
  ],
  "testsAddedOrUpdated": [
    "source/tests/fit/test_b1_r2.py：新增65项，真实字节/仓储五表/架构正负向边界",
    "source/tests/fit/test_b1_regressions.py：修正Profile身份及完整timestamp夹具，原断言保留",
    "source/tests/fit/test_additional_boundaries.py：真实子字段闭包、完整多session夹具，原断言保留",
    "三份历史独立测试及独立编码器原文不变，共91项完整重跑"
  ],
  "commandsRun": [
    {"command":"uv sync --project source --python 3.12 --locked --extra dev --no-editable","result":"passed","summary":"红/绿隔离环境均正常安装40包，完整cwd/env见commands.jsonl"},
    {"command":"旧环境python check_install.py（初次）","result":"failed","summary":"/tmp与/private/tmp路径别名断言，保留日志；正规化后26文件匹配"},
    {"command":"旧环境python -m pytest test_independent.py test_followup.py test_final_boundaries.py -q -p no:cacheprovider --basetemp red-complete-temp --junitxml red-complete.xml --tb=short","result":"failed","summary":"12失败/79通过，全部原反例复现；此前参考文件层级错误造成的13失败也保留"},
    {"command":"旧环境python -m pytest tests/fit/test_b1_r2.py -q -p no:cacheprovider","result":"failed","summary":"初次语法错误退出2；有效实现前61项48失败/13通过；最终65项旧包控制52失败/13通过"},
    {"command":"uv sync --project source --python 3.12 --locked --extra dev --no-editable --reinstall-package trainlab-source","result":"passed","summary":"最终非editable包重新构建安装，退出0"},
    {"command":"python check_install.py","result":"passed","summary":"最终28份模块/Schema与源码一致，40包版本匹配锁文件"},
    {"command":"python -m pytest tests -q -p no:cacheprovider --basetemp product-final-temp --junitxml product-final.xml --tb=short","result":"passed","summary":"157 passed, 2 warnings；完整绝对参数见commands.jsonl"},
    {"command":"python -m pytest test_independent.py test_followup.py test_final_boundaries.py -q -p no:cacheprovider --basetemp green-final-temp --junitxml green-final.xml --tb=short","result":"passed","summary":"91 passed, 2 warnings；仅开发者重跑，不是新独立验收"},
    {"command":"python -m ruff check --no-cache .","result":"passed","summary":"最终退出0"},
    {"command":"python -m mypy -p trainlab -p tests --no-incremental（首次实现）","result":"failed","summary":"1处新字典类型推断错误；原日志保留"},
    {"command":"python -m mypy -p trainlab -p tests --no-incremental（最终）","result":"passed","summary":"34 source files，无问题"},
    {"command":"python -m compileall -q skills schemas tests","result":"passed","summary":"退出0"},
    {"command":"python -m trainlab.check_architecture","result":"passed","summary":"最终架构与公开Schema通过"},
    {"command":"npm ci --cache /tmp/trainlab-b1-r2-0vQR45/npm-cache; npm run lint; npm run typecheck; npm run test; npm run build","result":"passed","summary":"隔离前端五项各退出0；3测试通过，生产产物用于真实ASGI回归"},
    {"command":"python evidence/check_snapshot.py after","result":"passed","summary":"56文件无差异，聚合SHA一致"},
    {"command":"git diff --check; git diff --cached --exit-code; git status --short","result":"passed","summary":"无暂存；未提交状态保留"},
    {"command":"python3 /tmp/trainlab-b1-r2-0vQR45/final_audit.py","result":"passed","summary":"工作区/副本匹配、历史脚本不变、161保护文件不变、归档CRC通过"}
  ],
  "validationOutput": [
    "旧91项：12失败79通过 → 新实现91通过；004/005/006回归保持。",
    "最终产品157通过；新增65项对旧固定包为52失败13通过。",
    "最终56文件聚合SHA：5cb22a1f1950c1e73c0624c2ac2981f090c246738dc53f62eb13f9a5996149d8。",
    "28份安装模块/Schema匹配源码，40个发行包匹配锁文件。",
    "原始证据与完整命令：/tmp/trainlab-b1-r2-0vQR45；持久归档evidence.zip。"
  ],
  "residualRisks": [
    "尚未独立复验或主Agent亲验，不宣称B0/B1验收完成。",
    "未穷举全部Profile/设备/未知厂商语义与随机协议输入；30,007条不是无限容量证明。",
    "架构静态门不证明任意动态反射或混淆代码无违规。",
    "未运行真实私人数据/业务服务、真实浏览器或8080监听验收；依赖弃用警告保留。"
  ],
  "noStagedFiles": true,
  "diffSummary": "10文件修改、3文件新增、无删除；协议/必需消息检查、数组累计与日期原值修复、共享Profile身份和timestamp三方一致校验、架构门正负向补齐及回归/直接文档同步。储存事务、前端、工具索引、依赖锁及协调记录不变。",
  "reviewFindings": [
    "开发者自查未发现已测场景阻断；此处不是独立Validator裁决。",
    "原测试夹具的四处事实同步及全部中途失败见fixture-and-check-notes.md。"
  ],
  "manualNotes": "本轮授权已用完并在交接处停止；主Agent应固定此快照交全新Validator，再亲验。累计失败与既有停止事实不清零，若后续失败不得自动续轮。"
}
```
