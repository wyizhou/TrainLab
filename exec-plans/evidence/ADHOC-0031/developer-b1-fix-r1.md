# ADHOC-0031 B0相关前置及B1首轮修复事实报告

## 结果与版本

已完成V31-B1-001～006对应实现及本地自查。**这不是独立复验或主Agent验收通过结论**；仍需按新的固定版本派发Validator。没有启动B2～B7，没有写协调记录。

- 分支：`work/adhoc-0031-local-web-system`。
- HEAD仍为 `9db8bb1dda5922e85fe42581e27d2428dbc9f195`，无暂存、提交、推送或PR。
- 开工逐项核对原38文件SHA，全部匹配给定快照 `2d31f4664f988146533561e7517836376e7e4d12fbaa0ab40c6961dd99ad2215`。
- 最终产品清单为53文件（`.gitignore`及source非忽略文件），摘要 `25f7f11d0e31787bddde584f7103de90c7a95522e5b7379521c6ef9affaa8d0f`。最终整组检查前后清单一致。
- 相对原清单：原路径修改5、新增路径32、退出路径17；其中大量是获准目录迁移，不是删除功能。逐路径SHA、大小、权限及增删改清单见 `final-snapshot.json`。
- `source/`仍未跟踪；不能仅以`git diff`代替完整产品差异。原计划、MEMORY及历史证据改动均保留，本实例没有编辑它们。

## 逐问题：根因、实质不同方法与实际结果

| 编号 | 原因及本次方法 | 自查证据 |
| --- | --- | --- |
| V31-B1-001 | 原先只有Protocol和注入DTO。本次提供默认`ProfileFitDecoder`，真实FIT字节经逐链协议遍历、固定官方Profile映射、完整DTO验证后入库。采用官方SDK 21.214.0的Profile/基础类型/CRC，但不依赖会丢信息的分组Decoder输出。支持定义重用/重定义、大小端、压缩时间、invalid/0、标准/Developer同名隔离、子字段/组件独立身份、累计组件单位、未知可解码字段、链式尾段及多session。没有把解码后移至B4。 | `test_decoder.py`、`test_additional_boundaries.py`；默认入口及25,001条真实合成FIT到SQLite测试；最终92项通过。 |
| V31-B1-002 | 原先物理实现位于`source/trainlab`，共享脚本是导出壳，tools检查修改sys.path。本次迁入`skills/_shared/scripts/trainlab`和`skills/fit-store/scripts`；用setuptools正常包映射保留Python导入名；公开Schema进入`source/schemas`。检查移至`python -m trainlab.check_architecture`，加违规落点/导入补丁负例。 | 非editable安装后离开仓库导入；已安装26份产品/Schema文件与当前源码逐字节一致；架构门及负例通过。 |
| V31-B1-003，关联V31-B0-006 | 原先强制segments数组、浅层序列化就提交。本次使用公开Draft 2020-12 Schema及真实jsonschema递归校验，合法segments为`{items:[Message...]}`。附加字段/来源/组件闭包、消息分类/原序、记录索引、同条字段定义/链一致性、SQL/basic及记录时间证据校验；严格JSON拒绝重复键、非有限数、裸大整数、bytes、任意对象及额外结构键。仓储提交边界实际调用，非只验示例。 | 合法基线可入库后逐项变异；每种非法输入分别失败且活动/records/两报告/config五表不变。公共Schema及错误大整数/引用/结构回归通过。 |
| V31-B1-004，关联V31-B0-006 | 原先以“不含records”等同默认123。本次固定返回`activity_id/schema_version/basic_json/summary_json/segments_json/field_definitions/developer_sources`；只计算123引用所需字典和组件父项、来源闭包，不返回完整sensors/路径/采样。同步机器Schema、消费者及索引。 | 默认结果键集合、仅需字段、组件父字段闭包、无多余来源、原生分段、公共Schema通过。 |
| V31-B1-005 | 原先无条件UPSERT并删除重插子行。本次普通同SHA导入校验输入后保持有效行完全不变，不改原路径和parsed_at，不写记录/报告。 | 不同文件名/较晚解析时间重复导入，五表逐值相等；原件字节不变。 |
| V31-B1-006 | 原先只保报告行，事实仍被改。本次新增明确的维护文件入口`reparse_fit_file`，验证已存原路径的实际SHA，完整解析后在共享单进程门下比较事实；无变化不写，有活动报告且事实变化返回REPARSE_CONFLICT；无报告合法变化可原子更新，SQL子行失败保旧。 | 报告冲突、无变化、原件SHA变更、无报告更新、首次/维护子行失败、历史周报/config保护、只读视图阻止写门及DB/sidecar不变通过。 |

没有增加业务列，保留12/4/3/3＋config三列及原外键/非空约束，不用REPLACE，不采用活库immutable。共享门/只读视图是B1所需前置，没有实现AI宿主、采样工具或报告生成。

## SDK与协议核实

独立环境安装固定公开发行包 `garmin-fit-sdk==21.214.0`；Profile实际有124种消息、200种类型。SDK文件SHA和全部实际依赖版本见最终 `final-validation/installed-parity.log`。

直接阅读官方发行包源码确认：Decoder的compressed timestamp路径明确不支持；普通解码会省略invalid，Developer字段查找取首个匹配，组件结果可能覆盖同名直接字段。因此本次采用获准的等效受控协议适配，不把SDK返回多少当作完整：

1. `wire.py`保留原始数据消息顺序、链及定义身份，检查全链头/长度/CRC/类型/字节序/数据长度，处理压缩时间戳及溢出。
2. `profile_fields.py`使用完整固定Profile，分离直接/子字段/组件身份，不合并HR到records；保留invalid、未知值、数组及Developer来源/重定义。
3. `parser.py`把基本消息、全部session、原生分段、records与其余消息分别归类；start只用session证据，end用elapsed，不使用timer或汇总timestamp代替。
4. 实际消息分类在公开Schema中记录，解析器与递归校验共同消费。原生分段包含lap、length、segment_lap、set、split、split_summary。
5. 独立Activity必须具备file_id/activity/session/lap/record主体；各含主体的链段分别检查，前段不能补尾段缺失。追加HR/HRV段作为已有完整活动的补充；没有宣布所有零record Activity都合法。固定官方指南仍将record列为必需，本次未发现通用零record例外。

正常合成FIT用官方Decoder交叉核对record数量、speed及elapsed；该SDK不支持的压缩时间、invalid保留、同名覆盖等另用协议断言检查。没有下载或使用私人活动。

公开页面证据在证据根：`activity-content.html/.txt`、`protocol-content.html/.txt`及page-data JSON。初次猜测的protocol文章URL返回404；随后根据官方page-data核实实际路径，成功读取。没有把404记作核实通过，也没有反复重试故障环境。

## 测试先行和旧检查映射

先于产品修改写入合成生成器与回归：

- `red-regressions.log`：21失败，退出1，包含缺默认解析入口、违规目录、批准JSON不被接受、默认123及幂等/维护接口缺失。
- `red-decoder.log`：22失败，退出1，真实协议输入无法进入产品实际解码；正常合成字节先由官方SDK交叉解码。
- 正常合法基线在原版即被segments错误阻挡，因此初次非法变异红灯**不被当成各校验项已命中证据**。最终测试先成功保存完整合法基线，再逐项变异、要求失败及五表保旧。
- 开发过程中补测并修正的红灯原件亦保留：`protocol-red.log`（3失败）、`accumulation-red.log`（1失败）、`packed-byte-red.log`（1失败）、`schema-id-red.log`（1失败）、`fieldset-red.log`（2失败）、`headers-red.log`（2失败）。这些是同一次开发自查过程，不冒充新独立验证轮次。

原独立S01～S19的业务预期映射到当前回归：

| 原场景 | 当前覆盖 |
| --- | --- |
| S01/S09/S11 | `test_decoder.py`＋真实默认文件入口、坏FIT无DB、SHA/路径/原件保护；不再用SyntheticDecoder充当解析完成 |
| S02 | `test_approved_layout`、`test_architecture_negative_cases`、安装文件一致性及模块架构入口 |
| S03/S05/S06 | 表列/外键/初始化五表保护、cycling/混合sport、UTC正规化与naive拒绝 |
| S04 | DTO层25,001条逐条比对，另新增真实合成FIT 25,001条默认入口入库、重复/逆序时间保留 |
| S07/S15/S17/S18 | 完整合法JSON基线及逐项结构/引用/值/SQL一致性变异、真实Schema、正常segments对象 |
| S08/S13/S14 | 首次和明确维护入口子行失败回滚、已有报告事实冲突、无报告原子更新 |
| S10 | 相对越界、绝对越界、根外软链接在读取/建库前拒绝 |
| S12 | 普通同字节导入五表无变更；维护与普通导入分离 |
| S16/S19 | 批准默认123及最少字典闭包，不存在活动明确错误 |

没有编辑原独立证据。旧API探针定位、segments数组、整包sensors默认返回、已有报告静默更新等错误预期没有继续保留。原B0的17项回归文件未变，仍实际运行。

## 实际检查命令和结果

最终唯一权威整组结果：`final-results.json`，每条记录完整cwd、参数、退出码和日志；执行器 `validate_final.py` 与 `final-runner.log`，退出0。

最终Python为新建的仓库外环境 `/tmp/trainlab-b1-fix-r1-ux1yV8/verify-venv/bin/python`，版本3.12.13。只用声明依赖和`source/uv.lock`，`uv sync --locked --extra dev --no-editable`成功；没有修改给定参考验证环境。早期开发环境在同证据根的`venv/`，与最终干净验证环境区分。

| 实际命令（Python项在source） | 退出 | 实际结果/最终日志 |
| --- | ---: | --- |
| `python -m pytest tests -q -p no:cacheprovider --junitxml=<外部证据>/pytest.xml` | 0 | **92 passed，2条依赖弃用警告**；`final-validation/pytest.log/.xml` |
| `python -m ruff check --no-cache .` | 0 | All checks passed；`final-validation/ruff.log` |
| `python -m mypy -p trainlab -p tests --no-incremental` | 0 | 32个源码文件无问题；`final-validation/mypy.log` |
| `python -m compileall -q skills schemas tests` | 0 | `final-validation/compileall.log` |
| `python -m trainlab.check_architecture` | 0 | 架构＋公共Schema检查通过；`final-validation/architecture.log` |
| 在仓库外运行`check_install.py <项目根>` | 0 | 正常导入已安装包；产品/Schema逐文件与当前源码一致；`final-validation/installed-parity.log` |
| `npm ci` | 0 | 137包安装、审计0漏洞；`final-npm-ci.log` |
| `npm run lint`、`npm run typecheck` | 各0 | `final-validation/frontend-lint.log`、`frontend-types.log` |
| `npm test` | 0 | **3 passed**；`final-validation/frontend-test.log` |
| `npm run build` | 0 | 17模块，真实React生产输出到后端web；`final-validation/frontend-build.log` |
| `git diff --check` | 0 | `final-validation/diff-check.log` |
| `git diff --cached --exit-code` | 0 | 无暂存；`final-validation/index-check.log` |

旧mypy物理路径命令改为检查正常安装的包和当前测试；先重新安装，再逐文件核对安装内容，避免旧wheel假通过。初次editable包不被mypy包发现、后续类型问题及修正日志保留为`mypy-1.log`～`mypy-3.log`，最终结果以上表为准。Ruff初次排序/未使用导入问题也保留，没有关闭规则换绿灯。

前端没有改业务源码/样式/依赖声明。npm对可选fsevents安装脚本给出allow-scripts提示，没有批准脚本或修改全局设置；现有前端检查/构建全部成功。Python两条警告来自FastAPI/Starlette测试依赖，不隐藏，也未为消除警告扩张修复范围。

## 文件与证据位置

证据根：`/tmp/trainlab-b1-fix-r1-ux1yV8/`。

- `baseline.json`、`before/`：原38文件及保护副本。
- `final-snapshot.json`：当前53文件和全部增删改，包含HEAD/分支/无暂存状态。
- `final-results.json`、`final-validation/`：最终全部命令、结果、Junit及安装一致性。
- `clean-lock-install.log`、`final-install-2.log`：只按声明/锁文件的新环境安装证据。
- `check_install.py`、`validate_final.py`：可复跑核对器。
- 红灯和中间自查日志保留，不与最终结果混淆。
- `changed-existing.diff`：原路径中仍存在文件的差异；迁移/新文件完整内容见前后快照，不能把这份diff误当完整差异。
- `developer-evidence.zip`：原/新公开产品快照、合成测试、日志和公开SDK网页证据；排除虚拟环境和wheel，未包含私人实例。CRC检查通过，SHA256 **`4802d51b518840ddd2fc60558f124d5e3bc667d3f93315bafc7aa77416814a44`**，657861字节；`archive-receipt.json`记录收据。

主要物理变化：`source/trainlab/contracts/* → source/skills/_shared/scripts/trainlab/contracts/*`；`source/trainlab/fit/* → source/skills/fit-store/scripts/*`；检查脚本从tools迁出；共享导出与包标记迁入同一共享实现根。新增wire/profile映射、真实Schema/验证器、数据库门、合成协议与回归、锁文件。完整精确文件清单见下方JSON及快照。

## 边界、累计事实和未完成事项

- 没有读取真实states、FIT、Goal、认证或AI配置；没有业务Garmin/AI调用、定时任务、远端CI、暂存/提交/推送。
- 未实现B2～B7：唯一采样工具的业务派发、报告业务、同步/认证刷新、AI工具循环/Context、完整Web业务及真实端到端仍未完成；未改变D31-03A/B、D31-02A待决政策。
- 本轮没有真实设备文件兼容性测试；固定Profile之外的未知字段只能保留原始可解码值，不能宣称知道其业务含义。SDK/Profile升级、实际设备兼容性需另行核实。
- 25,001条是实际长集合回归，不是设备内存极限、模型上下文容量或运行资源极限证明；没有用任意上限裁剪记录，也没有假报模型容量实测。
- 单进程协调门和只读事务已有合成检查；跨进程宿主、多轮AI持有视图及真实并发接线属于后续阶段，不能拿本次检查代替。
- B1原首次独立失败1轮保留；本次为B1修复尝试1，**尚无修复后独立复验结果**。V31-B1-003/004关联V31-B0-006：旧首次失败1、既往尝试1及原时点通过事实保留，本次为公共合同累计尝试2，不清零。若后续独立复验触及规定停止阈值，由主Agent据证据执行，不由本实例再起修复轮次。

```acceptance-report
{
  "criteriaSatisfied": [
    {"id": "criterion-1", "status": "satisfied", "evidence": "在B0直接相关目录/JSON和B1范围内实现V31-B1-001～006；原38文件保护核对，未实施B2～B7或修改协调记录。完成仅指实现和自查，仍待全新独立复验。"},
    {"id": "criterion-2", "status": "satisfied", "evidence": "提供原/新逐文件快照、测试先行红灯、锁文件干净安装、已安装文件一致性、92项Python和3项前端、静态检查及完整命令日志归档。"}
  ],
  "changedFiles": [
    ".gitignore",
    "source/README.md",
    "source/pyproject.toml",
    "source/uv.lock",
    "source/tools/README.md",
    "source/schemas/__init__.py",
    "source/schemas/contracts.schema.json",
    "source/schemas/examples.json",
    "source/skills/_shared/scripts/trainlab/__init__.py",
    "source/skills/_shared/scripts/trainlab/py.typed",
    "source/skills/_shared/scripts/trainlab/check_architecture.py",
    "source/skills/_shared/scripts/trainlab/database.py",
    "source/skills/_shared/scripts/trainlab/exports.py",
    "source/skills/_shared/scripts/trainlab/contracts/__init__.py",
    "source/skills/_shared/scripts/trainlab/contracts/config.py",
    "source/skills/_shared/scripts/trainlab/contracts/errors.py",
    "source/skills/_shared/scripts/trainlab/contracts/interfaces.py",
    "source/skills/_shared/scripts/trainlab/contracts/json_validation.py",
    "source/skills/_shared/scripts/trainlab/contracts/paths.py",
    "source/skills/_shared/scripts/trainlab/contracts/schema.py",
    "source/skills/_shared/scripts/trainlab/contracts/session.py",
    "source/skills/_shared/scripts/trainlab/contracts/time.py",
    "source/skills/_shared/scripts/trainlab/contracts/web.py",
    "source/skills/fit-store/README.md",
    "source/skills/fit-store/scripts/__init__.py",
    "source/skills/fit-store/scripts/models.py",
    "source/skills/fit-store/scripts/parser.py",
    "source/skills/fit-store/scripts/profile_fields.py",
    "source/skills/fit-store/scripts/storage.py",
    "source/skills/fit-store/scripts/wire.py",
    "source/skills/local-web/scripts/__init__.py",
    "source/tests/fit/__init__.py",
    "source/tests/fit/fit_bytes.py",
    "source/tests/fit/test_additional_boundaries.py",
    "source/tests/fit/test_b1_regressions.py",
    "source/tests/fit/test_decoder.py",
    "source/tests/fit/test_storage.py",
    "source/skills/_shared/scripts/contracts.py",
    "source/tools/check_b0_static.py",
    "source/trainlab/__init__.py",
    "source/trainlab/py.typed",
    "source/trainlab/contracts/__init__.py",
    "source/trainlab/contracts/config.py",
    "source/trainlab/contracts/errors.py",
    "source/trainlab/contracts/interfaces.py",
    "source/trainlab/contracts/paths.py",
    "source/trainlab/contracts/schema.py",
    "source/trainlab/contracts/session.py",
    "source/trainlab/contracts/time.py",
    "source/trainlab/contracts/web.py",
    "source/trainlab/fit/__init__.py",
    "source/trainlab/fit/models.py",
    "source/trainlab/fit/parser.py",
    "source/trainlab/fit/storage.py"
  ],
  "testsAddedOrUpdated": [
    "source/tests/fit/fit_bytes.py",
    "source/tests/fit/test_b1_regressions.py",
    "source/tests/fit/test_decoder.py",
    "source/tests/fit/test_additional_boundaries.py",
    "source/tests/fit/test_storage.py",
    "source/tests/fit/__init__.py"
  ],
  "commandsRun": [
    {"command":"修复前 pytest tests/fit/test_b1_regressions.py", "result":"failed", "summary":"退出1；21失败，红灯原件保留"},
    {"command":"修复前 pytest tests/fit/test_decoder.py", "result":"failed", "summary":"退出1；22失败，真实FIT解析入口缺失"},
    {"command":"开发中补充协议/累计单位/packed bytes/Schema精确ID/跨层引用回归", "result":"failed", "summary":"分别3/1/1/1/2/2失败；同次开发自查的红灯均保留，最终全部通过"},
    {"command":"uv lock --directory source --python <独立Python>", "result":"passed", "summary":"退出0；41包解析，SDK/jsonschema精确固定"},
    {"command":"UV_PROJECT_ENVIRONMENT=<新仓库外环境> uv sync --project source --locked --extra dev --no-editable", "result":"passed", "summary":"退出0；最终新环境只按声明依赖安装；源码更新后重新安装并逐文件核对"},
    {"command":"python -m pytest tests -q -p no:cacheprovider --junitxml=<外部证据>/pytest.xml", "result":"passed", "summary":"退出0；92 passed，2条依赖弃用警告"},
    {"command":"python -m ruff check --no-cache .", "result":"passed", "summary":"退出0"},
    {"command":"python -m mypy -p trainlab -p tests --no-incremental", "result":"passed", "summary":"退出0；32 source files"},
    {"command":"python -m compileall -q skills schemas tests", "result":"passed", "summary":"退出0"},
    {"command":"python -m trainlab.check_architecture", "result":"passed", "summary":"退出0；目录、导入补丁、表/政策、公共Schema检查"},
    {"command":"仓库外 python check_install.py <项目根>", "result":"passed", "summary":"退出0；安装后正常导入，26个产品/Schema文件与当前源码一致"},
    {"command":"npm ci", "result":"passed", "summary":"退出0；137包、0漏洞；可选fsevents脚本提示保留"},
    {"command":"npm run lint && npm run typecheck && npm test && npm run build", "result":"passed", "summary":"逐命令均退出0；3测试通过，真实React构建17模块"},
    {"command":"git diff --check; git diff --cached --exit-code", "result":"passed", "summary":"均退出0；没有暂存文件"}
  ],
  "validationOutput": [
    "最终53文件摘要25f7f11d0e31787bddde584f7103de90c7a95522e5b7379521c6ef9affaa8d0f；整组检查前后一致",
    "最终命令清单：/tmp/trainlab-b1-fix-r1-ux1yV8/final-results.json",
    "日志与JUnit：/tmp/trainlab-b1-fix-r1-ux1yV8/final-validation/",
    "证据归档：/tmp/trainlab-b1-fix-r1-ux1yV8/developer-evidence.zip；SHA256 4802d51b518840ddd2fc60558f124d5e3bc667d3f93315bafc7aa77416814a44"
  ],
  "residualRisks": [
    "尚未执行修复后的全新Validator独立复验和主Agent验收",
    "未使用真实私人FIT；未知Profile/厂商语义及后续SDK升级需另验",
    "25,001条全量回归不是设备资源极限或模型容量验证",
    "B2～B7和真实Provider链路尚未实现/运行；待决业务政策没有默认补齐",
    "两条Python依赖弃用警告及npm可选fsevents脚本提示保留"
  ],
  "noStagedFiles": true,
  "diffSummary": "原路径修改5、新增32、迁移退出17；实际FIT解码、合规包映射、单一递归Schema/跨层校验、默认123闭包、普通幂等及受控维护冲突保护；未改业务列或协调状态。",
  "reviewFindings": ["无已知本轮自查阻断；不替代必需的全新独立审查"],
  "manualNotes": "B1修复尝试1；公共合同关联旧B0-006累计尝试2，原首次失败和原时点通过不改写。所有结果为Developer自查事实，不能据此跳过review gate。参考验证环境未被修改；没有读取真实states、调用业务Provider或Git写入。"
}
```
