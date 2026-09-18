# ADHOC-0031 B1 首次独立验证报告

## 结论

**失败，当前固定版本不能通过 B1 验收。** 共确认 6 项问题，编号为 **V31-B1-001～006**。主要原因：没有实际 FIT 解码器；采用了未批准的实现目录；JSON 合同和默认123输出不符合要求；同字节重复导入会更新有效数据；已有活动报告时允许静默改变其依赖事实。

- 原有基础检查全部通过：pytest **24 passed**，Ruff、mypy、compileall、静态合同检查均退出 **0**。
- 独立检查：**39 项，21 passed / 18 failed / 0 errors**，进程退出 **1**。失败断言归并为上述 6 个问题，不按断言数量重复计问题。
- 已验证的存储子项包括：表结构、实际外键、25,001 条记录的顺序和完整保存、UTC正规化、部分坏值拒绝、产品导入入口的子行失败回滚、相对路径及链接越界拒绝。
- **这些存储通过项不等于 FIT 解析通过。** 涉及文件导入的存储边界测试明确使用注入 DTO 的替身；未把它当作解码器。真实合成 FIT → 完整解析 → 入库 → 默认123的全流程缺少产品入口，不能完成。
- 本报告是独立验证结果，不代替主 Agent 最终验收，也未修改协调记录。

## 1. 受审版本、只读边界及环境

完整阅读了 `PLAN.md`、`AGENTS.md`、`subagent-templates/validator.md`、`validation-request.md`、`requirements.md`、`review-snapshot.json`，并查阅本副本提供的协议参考、源码和原有测试。没有查询其他会话、开发者报告或外部历史。

| 项目 | 核对结果 |
|---|---|
| 工作位置 | 本次 `trainlab-0031-b1-review-yh_zjbuc` 隔离副本；没有 `.git`，未初始化仓库 |
| 来源分支 | `work/adhoc-0031-local-web-system`，来自固定清单，未读取主工作区 |
| 来源 HEAD | `9db8bb1dda5922e85fe42581e27d2428dbc9f195` |
| 实际受审内容 | 上述 HEAD **加快照记载的未提交实现**，不是只审 HEAD |
| 产品清单 | 38 文件；逐文件 SHA-256、大小、权限模式前后全部一致 |
| 聚合 SHA-256 | 前后均为 `2d31f4664f988146533561e7517836376e7e4d12fbaa0ab40c6961dd99ad2215` |
| 产品文件增减 | 扣除允许的缓存后，新增产品文件 `[]`，缺失文件 `[]` |
| 修改/暂存 | 未修改清单内文件，未改主工作区或计划，未执行 Git 写操作；本副本无暂存区。来源快照的短状态也未列出已暂存文件 |
| 本轮产品变化 | 快照列出 5 个新增文件：FIT 包4文件、存储测试1文件；修改3文件：两个 README、静态检查脚本；共享 `contracts` 实现不在本轮变化列表 |
| Python | 派发提供的 `/tmp/trainlab-b0-fix-venv/bin/python`，3.12.13 |
| 检查依赖 | pytest 9.1.1、Ruff 0.16.7、mypy 1.20.2；详见 `evidence/environment.json` |
| 网络/私密边界 | 全部离线、合成；未读取真实 states、私人 FIT、认证或秘密，未调用业务 Provider 或远端 CI；没有安装依赖 |
| 写入范围 | 仅 `evidence/`、允许的测试/编译缓存和本绑定报告 |

核对证据：`evidence/snapshot-before.log`、`evidence/snapshot-after.log`。最终可复跑核对器：`evidence/check_snapshot.py`，退出0；其中也检查没有新增非缓存产品文件。

来源快照的 `git_status_short` 记载 `.gitignore`、业务协调文件已修改，`source/` 和若干执行计划/证据未跟踪；这些是来源工作区既有状态，不是 Validator 的写入。未去其他工作区复核或改动它们。

## 2. 实际命令与基础检查

以下 `$PY` 表示本次实际使用的 `/tmp/trainlab-b0-fix-venv/bin/python`。原有测试的临时目录通过 `TMPDIR` 指向本副本 `evidence/tmp/`；独立测试用 `--basetemp` 明确写入 `evidence/`。

### 基础检查（工作目录 `source/`）

| 实际命令 | 退出码 | 结果/证据 |
|---|---:|---|
| `$PY -m pytest tests -q -p no:cacheprovider` | 0 | 24 passed，2条依赖弃用警告；`evidence/baseline-pytest.log` |
| `$PY -m ruff check --no-cache .` | 0 | All checks passed；`evidence/baseline-ruff.log` |
| `$PY -m mypy trainlab skills tools tests` | 0 | 21 source files 无问题；`evidence/baseline-mypy.log` |
| `$PY -m compileall -q trainlab skills tools tests` | 0 | 编译通过；`evidence/baseline-compileall.log` |
| `$PY tools/check_b0_static.py` | 0 | B0 static contract check passed；`evidence/baseline-static.log` |

上述命令由 `$PY evidence/run_baseline.py` 在副本根目录调用，执行器退出0；完整参数及结果见 `evidence/baseline-results.json`。

### 独立材料和测试

1. 副本根目录运行 `$PY evidence/synthetic_fit.py`，退出 **0**。生成8个合成 FIT：正常、坏CRC、截短长度、未定义本地消息、缺activity、零record、双链、第二链坏CRC。正常文件272字节，消息编号顺序为 `[0,20,20,20,20,19,18,34]`，4条record、5个Definition；双链8条record。构造器独立核对头/文件CRC、长度及本地Definition遍历。证据：`evidence/fixtures.log`、`evidence/fits/manifest.json`、`evidence/fits/*.fit`。
2. 在 `source/` 运行：
   ```text
   TMPDIR=../evidence/tmp $PY -m pytest ../evidence/test_b1_independent.py -v -s --tb=short -p no:cacheprovider --basetemp=../evidence/pytest-temp --junitxml=../evidence/independent-results.xml
   ```
   退出 **1**；39项中21通过、18失败、0错误。证据：`evidence/independent-pytest.log`、`evidence/independent-results.xml`。
3. 为取得逐场景独立退出码，再用 `$PY evidence/run_scenarios.py` 分19组执行相同39项，最终执行器退出 **1**。每组完整命令、节点、退出码见 `evidence/scenario-results.json`，原始输出见下表。
4. 最后 `$PY evidence/check_snapshot.py` 退出 **0**，固定内容未变化。

**验证器自身脚本修正记录：** 分组执行器第一次漏建 `--basetemp` 的父目录，使用临时数据库的分组出现 `FileNotFoundError`，不是产品结果。初次完整39项运行不受影响。只修正了 `evidence/run_scenarios.py` 的目录创建；创建后记录父目录实际存在，再重跑分组检查。首次输出未删除，保存在 `evidence/scenarios-attempt1/`、`evidence/scenario-results-attempt1.json`、`evidence/scenario-runner-attempt1.log`；修正及恢复证据是 `evidence/scenario-harness-correction.log`。没有为此改动产品或降低断言，没有解释器/依赖故障。

## 3. 逐场景结果

表中 `C(Sxx)` 表示 `evidence/scenario-results.json` 对应场景的 **完整实际命令**；也原样记录在对应日志首行。共同命令形式是在 `source/` 执行：

```text
$PY -m pytest ../evidence/test_b1_independent.py::<节点> [其他节点] -v -s --tb=short -p no:cacheprovider --basetemp=../evidence/scenario-temp/<场景名>
```

`evidence/run_scenarios.py` 保留场景→节点的一对一映射，可整体复跑。下列“通过”严格限定在所写入口和合成输入，不推及未实现解析。

| 场景/命令 | 要求、类型及实际输入/入口 | 预期 → 实际 | 退出码/结论 | 证据 |
|---|---|---|---|---|
| S01 / C(S01) | B1、AC-02/04、T2/03；正常入口盘点，遍历产品decode实现并检查导入签名 | 应有可用 FIT 解码实现 → 只有不能实例化的 `FitDecoder(Protocol)`，文件导入必须由调用者传decoder | 1，失败；V31-B1-001 | `evidence/scenarios/S01-decoder.log` |
| S02 / C(S02) | 目录A、无sys.path补丁；静态边界 | 实现在批准的Skill/scripts，tools仅文档 → 运行模块在trainlab物理根，检查脚本仍在tools且插入sys.path | 1，失败；002 | `evidence/scenarios/S02-layout.log` |
| S03 / C(S03) | AC-01/05、GATE-02；正常/错误；`open_database`、初始化、导入后种入合成报告/config再初始化 | 12/4/3/3+config，非空联合键、外键，已有数据不丢 → 满足；孤儿/重复记录被拒，重初始化五表内容相同，journal为delete | 0，通过（存储） | `evidence/scenarios/S03-schema.log` |
| S04 / C(S04) | AC-02、GATE-02；边界；产品 `import_activity` 输入25,001条DTO | 保留全部记录、原顺序、重复/逆序时间、间隔、0/null → 逐行index/时间/metrics对象全部相等，无补点裁剪 | 0，通过（DTO到DB，不证明FIT解码） | `evidence/scenarios/S04-records.log` |
| S05 / C(S05) | AC-05；正常；cycling DTO导入 | 非running可存储 → 活动及2条记录保留；未调用B2授权工具 | 0，通过（存储范围） | `evidence/scenarios/S05-nonrunning.log` |
| S06 / C(S06) | T2/03；正常/错误；+08:00输入、19.125秒时长、start/end/record/parsed_at无时区输入 | UTC固定6位小数Z，拒绝无时区且不落行 → 5项均满足 | 0，通过（输入正规化，不证明FIT时间推导） | `evidence/scenarios/S06-time.log` |
| S07 / C(S07) | AC-04、T2/02；错误；原有效数据+报告/config，记录含NaN、Infinity、bytes或object | 显式失败并保旧 → 4项均抛 `FitStorageError`，五表快照不变 | 0，通过 | `evidence/scenarios/S07-invalidvalues.log` |
| S08 / C(S08) | AC-04、GATE-02；错误；在合成DB给record_index=1注入失败触发器，再调用真实 `import_activity` | 首次子行失败不造行，更新失败旧活动/records/报告/config全保留 → 两项均回滚 | 0，通过；不是手写事务替代产品入口 | `evidence/scenarios/S08-rollback.log` |
| S09 / C(S09) | T2/04；正常；合成FIT实际字节、误导文件名，`import_fit_file`+存储替身 | SHA取字节、DB存相对路径、原件不动 → 满足；替身确实收到完整字节 | 0，通过（文件/存储边界） | `evidence/scenarios/S09-fileidentity.log` |
| S10 / C(S10) | T2/04；错误；`../`、根外绝对路径、指向根外的符号链接，均指向本副本内合成文件 | 应在读/解码/建DB前拒绝 → 三项均拒绝，decoder未调用且无DB | 0，通过 | `evidence/scenarios/S10-path.log` |
| S11 / C(S11) | AC-04；错误；文件入口注入抛错decoder，分别无DB/已有有效DB | 首次不建DB，已有数据不变 → 满足；此处只检查异常传播，不证明坏FIT识别 | 0，通过（边界） | `evidence/scenarios/S11-decodefailureboundary.log` |
| S12 / C(S12) | T2/04.2；边界；同一合成FIT换名字、晚一天重复导入，两个decoder给相同DTO | 原有效行、parsed_at、路径不变 → 路径从old.fit改为new-name.fit，parsed_at变晚一天 | 1，失败；005 | `evidence/scenarios/S12-idempotence.log` |
| S13 / C(S13) | T2/04.6；错误；已有活动/周报告/config，把原2条records改为1条不同值 | 返回REPARSE_CONFLICT且五表不变 → 无异常，record被替换，旧活动报告仍留存 | 1，失败；006 | `evidence/scenarios/S13-reportconflict.log` |
| S14 / C(S14) | T2/04；正常；无报告时原子替换记录 | 新记录整场更新 → 成功保存一条新记录；仅证明仓储更新能力，不证明维护入口排空运行视图/SHA验证 | 0，通过（仓储子项） | `evidence/scenarios/S14-noreportupdate.log` |
| S15 / C(S15) | T2/02；正常；原生分段用批准的 `{items:[Message]}` 容器调用仓储 | 正常保存固定结构 → 抛 `segments_json must be a JSON array` | 1，失败；003 | `evidence/scenarios/S15-segments.log` |
| S16 / C(S16) | AC-03、T2/02；正常/边界；DB中123只引用f2，records引用f0/f1，设备消息引用f3，调用 `get_activity_facts` | 仅批准123结构+最少f2字典，无完整sensors → 返回完整sensors，包括设备消息、全部f0～f3和不需要的d0；还缺schema_version和批准键名 | 1，失败；004 | `evidence/scenarios/S16-defaultfacts.log` |
| S17 / C(S17) | 公共合同、T2/02；正常/错误；`validate_payload('ActivityFacts', ...)` | 接受批准默认DTO，拒绝额外结构键 → 批准DTO被判缺basic；旧形状加unapproved却通过 | 1，失败；003/004的继承合同证据 | `evidence/scenarios/S17-publiccontract.log` |
| S18 / C(S18) | AC-04、T2/02；错误；字段/来源悬空引用、坏origin、缺time_evidence、额外键、SQL/JSON运动或时间不一致、未包装大整数、任意值对象 | 完整校验后才能提交，应拒绝9种坏载荷 → 9种均成功写入1条活动 | 1，失败；003 | `evidence/scenarios/S18-jsonvalidation.log` |
| S19 / C(S19) | 缺失边界；不存在活动调用 `get_activity_facts` | 明确不存在而非空成功 → `ACTIVITY_NOT_FOUND` | 0，通过 | `evidence/scenarios/S19-notfound.log` |

S04～S14、S18 的隔离测试使用当前仓储支持的 `segments=[]` 以定位各自行为；这不是认可该形状。批准的 `segments={items:...}` 本身已在 S15 单独证明被错误拒绝。S18 说明仓储连其当前可接收形状里的非法引用/值都不检查，不声称已经成功导入一份完全符合批准协议的DTO。

### 按验收项汇总

| 验收项 | 结论 |
|---|---|
| AC-01 | **通过（SQLite建库/表列/键子项）**，没有以此推定FIT可导入 |
| AC-02 | **失败：实际解析缺失**；DTO层全量、顺序、0/null子项通过；字段来源、单位、Definition、组件等真实解码行为无法判断 |
| AC-03 | **失败**：默认输出包含完整第4类，分段结构不匹配；原生消息提取无法判断 |
| AC-04 | **失败**：完整DTO校验缺失，实际完整解析缺失；已测非法值及SQL子行失败回滚通过 |
| AC-05 | **通过的子项**：保留schema_version/列数，非running可存储、初始化不清空报告/config；真实session运动判定无法判断，报告依赖事实冲突另见006 |
| GATE-01 | 5项现有命令通过；**不足以通过完整门禁**。没有实际FIT场景覆盖；“先测试后实现”的时间顺序不能从当前固定快照确认 |
| GATE-02 | **失败/部分通过**：表键、25,001条存储、事务等通过；默认123、完整解析和JSON一致性未达标 |
| GATE-03 | 固定快照首次独立只读验证已执行且前后冻结核对通过；**产品要求未通过，不能给出验收PASS** |

## 4. 问题表与复现证据

### V31-B1-001：没有实际 FIT 解码器，B1 主流程未实现【阻断；本次新增功能缺项】

- 对应：B1范围、AC-02/04、T2/02消息映射、T2/03完整解析/链式/必需消息。
- 位置：`source/trainlab/fit/parser.py:1-15`；`source/trainlab/fit/storage.py:54-65`；`source/pyproject.toml`。
- 事实：parser只有 `FitDecoder(Protocol)` 的签名；实例化直接抛TypeError。`import_fit_file` 没有默认实现，调用者必须提供decoder。固定产品清单中没有另一实际decode实现、固定SDK适配、消息→四类映射或必需消息判定实现。
- 复现：运行 S01；查看入口签名和遍历到的唯一decode类。预期可处理合成FIT；实际产品没有可执行解析器。
- 影响：正常FIT、坏CRC/长度/Definition、链式第二段损坏、零record、未知扩展、Developer来源和单位转换等都不能由产品完成验证。不能用SQL落库或替身返回DTO替代。
- 证据：`evidence/scenarios/S01-decoder.log`、`evidence/code-review-index.log`。合成协议材料已准备在 `evidence/fits/`，但不把其生成/自检结果当产品解析通过。
- 分类依据：FIT包在快照中明确列为本轮新增。没有依据声称是历史失败的复现。

### V31-B1-002：目录A和无临时导入补丁约束未落实【高；继承问题并在本轮扩展】

- 对应：已审核目录与所有权第4项、T2/01、公共Schema落点。
- 位置：`source/trainlab/fit/`、`source/trainlab/contracts/`；`source/skills/_shared/scripts/contracts.py:5-18`；`source/tools/check_b0_static.py:6-8`。
- 事实：共享Skill脚本只是从另一物理实现根导出对象。新增FIT实现继续放在 `source/trainlab/fit/`，没有 `source/skills/fit-store/scripts/`。tools中仍放可执行检查脚本，并主动 `sys.path.insert`。批准的 `source/schemas/` 公开Schema目录也不存在，合同仍内嵌在trainlab模块。
- 复现：运行 S02，并核对固定清单及源码。预期可用打包映射保留trainlab导入名，但物理实现必须在批准位置；实际不是打包映射，而是另一实现根。
- 影响：目录/所有权检查没有覆盖当前批准边界；现有静态脚本退出0不能证明架构要求通过。
- 证据：`evidence/scenarios/S02-layout.log`、`evidence/code-review-index.log`。
- 新旧区分：未改动的 `trainlab/contracts` 是快照可证的继承前置问题；本轮新增FIT模块继续扩大该落点。静态脚本虽列为本轮修改文件，但没有B0逐行差异，**不能断言sys.path补丁首次出现于本轮**。

### V31-B1-003：批准的JSON载体被拒，非法DTO却可提交【高；本轮仓储缺陷＋继承公共校验缺口】

- 对应：AC-04、T2/02共同规则/字典引用/值形式/SQL-JSON一致性、T2/03解析后完整DTO校验。
- 位置：`source/trainlab/fit/models.py:27`；`source/trainlab/fit/storage.py:90-95,153-215`；`source/trainlab/contracts/interfaces.py:275-327`。
- 正常输入复现：S15把 `segments={"items":[Message]}` 传入仓储。预期保存原生分段容器；实际强制list，抛 `DATA_INVALID`。
- 错误输入复现：S18分别向当前仓储接受的结构加入 `f404` 未定义引用、`d404` 来源引用、非法origin、缺失时间证据、额外结构键、basic与SQL运动/时间不一致、裸 `9007199254740993`、任意元数据对象。预期在提交前拒绝；实际9项全部提交。
- 公共合同证据：S17旧ActivityFacts结构增加未知键仍被接受。其校验器只检查浅层类型/required等，仓储也未用共享完整Schema验证，而只是 `json.dumps(allow_nan=False)` 和局部容器检查。
- 影响：入库成功不能代表记录可解释或内部一致；大整数离开Python后存在精度风险，字段/来源引用失效会损害事实解释。拒绝NaN的通过结果不足以代替这些校验。
- 证据：`evidence/scenarios/S15-segments.log`、`evidence/scenarios/S18-jsonvalidation.log`、`evidence/scenarios/S17-publiccontract.log`；复现后的合成SQLite保存在 `evidence/scenario-temp/` 对应场景目录。
- 新旧区分：models/storage为本轮新增；公共 `interfaces.py` 不在本轮变化列表，校验合同缺口属于继承。

### V31-B1-004：默认事实读取整体返回第4类，且不是批准的默认DTO【高；本轮API缺陷＋继承合同偏差】

- 对应：AC-03、T2/02默认123 DTO及最少解释字典。
- 位置：`source/trainlab/fit/storage.py:130-150`；`source/trainlab/contracts/interfaces.py:151-182`；`source/tools/README.md` 默认上下文说明。
- 复现：S16中默认123只使用session字段f2，records使用f0/f1，设备说明使用f3。调用 `get_activity_facts`。
- 预期：返回 `{activity_id,schema_version,basic_json,summary_json,segments_json,field_definitions,developer_sources}`，本例只需f2且无Developer来源；不带完整sensors、fit_path或records。
- 实际：返回 `{activity_id,basic,summary,segments,sensors,source_timestamps_utc}`；`sensors`是完整数据库对象，设备消息、全部四个字段定义及d0一起返回。没有返回records及fit_path这一点通过，但不能抵消第4类越界。
- S17进一步证明：公共ActivityFacts校验器拒绝批准DTO，报“missing required property: basic”。**当前API和现有公共Schema采用同一旧形状，但两者共同偏离要求**，不是声称二者彼此不一致。
- 影响：默认事实边界变大，消费者不能依照已批准的schema_version及固定字段合同接入。
- 证据：`evidence/scenarios/S16-defaultfacts.log` 有完整实际对象；`evidence/scenarios/S17-publiccontract.log`。
- 新旧区分：默认读取API为新增；错误的公共ActivityFacts形状来自未改动的前置合同，本轮读取将其落实成了实际行为。

### V31-B1-005：同字节重复导入不是无变更幂等【高；本次新增】

- 对应：T2/04.2，同SHA不同文件名只导入一行，不更新有效行、parsed_at或报告；旧原件引用不被自动替换。
- 位置：`source/trainlab/fit/storage.py:54-76,98-126`。
- 复现：S12把同一份272字节合成FIT先存成old.fit，再存成new-name.fit；两个存储替身返回同样DTO，仅传入解析时间晚一天。
- 预期：五表数据完全不变。
- 实际：仍只有同一SHA活动，但fit_path从 `states/activities/old.fit` 改为 `states/activities/new-name.fit`；parsed_at从 `2030-01-01T01:02:03.123456Z` 改为 `2030-01-02T01:02:03.123456Z`。实现无条件UPSERT并删除重插records。
- 影响：仅用“行数没有增加”不能证明幂等；重复发现同字节文件会改变已有效数据。
- 证据：`evidence/scenarios/S12-idempotence.log`，其中打印前后路径与时间。该结果只针对存储入口，未伪称完成实际解码。

### V31-B1-006：已有活动报告时改变依赖事实，没有REPARSE_CONFLICT【高；本次新增】

- 对应：T2/04.5～6，报告与事实变化冲突应停止维护，保留旧活动/records和报告；不自动付费重生成。
- 位置：`source/trainlab/fit/storage.py:82-128`；错误码合同 `source/trainlab/contracts/errors.py:11-28` 没有相应冲突码。
- 复现：S13经产品入口导入活动及2条record，再在合成DB种入完整活动报告、历史周报和config；随后同activity_id导入只有1条且值为777的不同事实。
- 预期：返回REPARSE_CONFLICT，五表前后相同。
- 实际：没有异常或冲突码，records从2条变成1条，旧活动报告文本仍原样保存。报告行没被删除，却已经与其依赖事实不匹配。
- 影响：普通UPSERT不是受控重解析政策；“报告表还在”不能代替冲突保护。
- 证据：`evidence/scenarios/S13-reportconflict.log` 打印旧/新records及报告未变事实。S08另外证明真实SQL失败时能回滚，说明本项不是事务能力缺失，而是业务冲突判断未执行。

## 5. 原有测试覆盖评估

现有24项测试及静态检查全部真实运行通过，没有删改或跳过，但不能满足本次完整门禁：

- `source/tests/fit/test_storage.py:26-31` 的 `SyntheticDecoder` 对任意非指定坏字符串返回固定DTO；原测试文件输入是 `b"synthetic-fit-bytes"`，不是FIT协议解析。
- `test_zero_record_activity_is_valid...` 直接构造空record DTO，没有Activity必需消息或合法例外的协议证据，不能证明通用零record FIT合法。
- 现有重新导入测试允许改变records并只断言报告文本仍在，未断言应出现事实冲突；这正好遗漏006。
- `test_child_constraint_failure_rolls_back_activity_row` 手写SQL测试SQLite事务，不经过仓储入口；本次S08已独立补测真实产品入口的首次/重入库失败。
- 原有事实读取断言把完整`sensors`纳入默认返回；本次没有沿用它作为验收标准。
- 现有静态检查不检查当前目录A的主要违规，因此退出0与S02失败并不矛盾。

代码行号证据统一保存在 `evidence/code-review-index.log`。

## 6. 未验证事项与结论边界

**因001无法完成的产品行为检查：**

- 有效FIT真实消息→四类映射、消息/字段计数、原顺序和跨链record编号。
- CRC、头长/数据长、Definition解码错误、尾链完整性及SDK errors处理。
- 必需file_id/activity/session/lap/record判定、零record合法例外的固定SDK/协议证据。
- 标准/Developer身份、同名不同开发者、重定义、组件展开、未知扩展、单位只换算一次、原始bytes/大整数表示及隐私字段剔除。
- 真实FIT的相对/本地/invalid时间证据、session start+elapsed计算end、多session完整保存及真实运动分类。

已生成的坏FIT未由真实产品解析器执行，不能记录为“正确拒绝”；合成文件构造器的自检也不是官方SDK互操作验证。没有为了绕过缺失实现而安装另一解析器或自行补产品解码。

**其他范围边界：**

- 运行内只读视图、单进程协调和受控重解析的排空/SHA验证没有可证明的完整维护入口；只验证了当前仓储行为。普通rollback journal已在S03观察到，未据此宣称全部一致视图要求完成。
- 数据存储测试到25,001条，不是容量极限或模型发送容量验收；未擅自设采样配额。
- 已知远端来源冲突、真实同步及命名安装流程属于后续同步接入；没有要求B1提前实现整个B3，也没有给这些行为通过结论。
- B2的真实running查询与宿主授权、B3～B7的同步/报告/AI/Context/Web业务流程不在本次完整验收范围。非running DTO入库通过不代表running授权正确。
- 前端本轮无变动，未重跑前端构建/测试；基础pytest中已有的合成Web测试照常运行。
- 没有迁移真实数据库、读取私人文件或做外部服务验证。
- 当前快照无法证明测试编写先于实现，也不能确认修改脚本中每行的历史来源；没有搜索外部历史补推。

固定内容未变，无材料缺失或目标歧义需要追加解释。本次不需要等待旧会话续聊。所有未达到的功能均保留为失败/无法判断，没有用后续优化名义宣布B1完成。

## 7. 证据索引

- 冻结核对：`evidence/check_snapshot.py`、`evidence/snapshot-before.log`、`evidence/snapshot-after.log`。
- 基础检查：`evidence/run_baseline.py`、`evidence/baseline-results.json`、`evidence/baseline-*.log`、`evidence/environment.json`。
- 独立用例：`evidence/test_b1_independent.py`、`evidence/independent-pytest.log`、`evidence/independent-results.xml`。
- 分场景命令和日志：`evidence/run_scenarios.py`、`evidence/scenario-results.json`、`evidence/scenarios/*.log`；对应合成DB在 `evidence/scenario-temp/`，完整套件合成DB在 `evidence/pytest-temp/`。
- 合成协议输入：`evidence/synthetic_fit.py`、`evidence/fixtures.log`、`evidence/fits/manifest.json`、`evidence/fits/*.fit`。
- 静态人工复核：`evidence/code-review-index.log`。
- 验证器分组执行器第一次的准备错误及更正：`evidence/scenarios-attempt1/`、`evidence/scenario-results-attempt1.json`、`evidence/scenario-runner-attempt1.log`、`evidence/scenario-harness-correction.log`。此部分不是产品缺陷证据，也未隐藏。

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "not-applicable",
      "evidence": "本任务为只读Validator，不实施产品修改。38个固定产品文件前后SHA256/大小/模式全部一致，无新增非缓存产品文件。"
    },
    {
      "id": "criterion-2",
      "status": "satisfied",
      "evidence": "已提供固定版本、前后哈希、原有5项检查、39项独立用例及19组完整命令/退出码/日志、6个稳定问题编号和未验证边界；产品结论为失败。"
    }
  ],
  "changedFiles": [
    "evidence/check_snapshot.py",
    "evidence/run_baseline.py",
    "evidence/synthetic_fit.py",
    "evidence/test_b1_independent.py",
    "evidence/run_scenarios.py",
    "evidence/ 下生成的检查日志、结果清单、合成FIT和SQLite；没有受审产品文件变更"
  ],
  "testsAddedOrUpdated": [
    "evidence/test_b1_independent.py：39项独立检查，仅验证材料",
    "evidence/synthetic_fit.py：8个离线合成FIT及结构/CRC自检",
    "evidence/run_scenarios.py：分19组复跑相同用例并保存命令和退出码"
  ],
  "commandsRun": [
    {"command": "source/: python -m pytest tests -q -p no:cacheprovider", "result": "passed", "summary": "退出0；24 passed，2条依赖弃用警告"},
    {"command": "source/: python -m ruff check --no-cache .", "result": "passed", "summary": "退出0"},
    {"command": "source/: python -m mypy trainlab skills tools tests", "result": "passed", "summary": "退出0；21 source files"},
    {"command": "source/: python -m compileall -q trainlab skills tools tests", "result": "passed", "summary": "退出0"},
    {"command": "source/: python tools/check_b0_static.py", "result": "passed", "summary": "退出0；但不覆盖已批准目录A的主要违规"},
    {"command": "python evidence/synthetic_fit.py", "result": "passed", "summary": "退出0；8个合成协议输入，自检不等于产品解析"},
    {"command": "source/: python -m pytest ../evidence/test_b1_independent.py -v -s --tb=short -p no:cacheprovider --basetemp=../evidence/pytest-temp --junitxml=../evidence/independent-results.xml", "result": "failed", "summary": "退出1；39项，21 passed、18 failed、0 errors"},
    {"command": "python evidence/run_scenarios.py（第一次）", "result": "failed", "summary": "验证器脚本漏建basetemp父目录；原始错误已保留，不归因产品"},
    {"command": "python evidence/run_scenarios.py（仅修正evidence脚本目录准备后）", "result": "failed", "summary": "退出1；19组逐项日志与完整独立套件结果一致"},
    {"command": "python evidence/check_snapshot.py", "result": "passed", "summary": "退出0；38文件哈希/大小/权限一致，聚合摘要匹配，无非缓存新增产品文件"}
  ],
  "validationOutput": [
    "整体结论：失败；V31-B1-001～006阻止当前B1验收",
    "来源HEAD 9db8bb1dda5922e85fe42581e27d2428dbc9f195 加固定未提交实现",
    "前后聚合SHA256均为2d31f4664f988146533561e7517836376e7e4d12fbaa0ab40c6961dd99ad2215",
    "存储通过项不等于FIT解析通过；所有替身用途均明确标注"
  ],
  "residualRisks": [
    "实际FIT解码器不存在，完整协议/字段/链式/时间/多session行为不能验证",
    "JSON、默认123、幂等及已有报告重解析冲突缺陷尚未修复",
    "B2～B7、真实数据/服务、前端本轮回归未纳入本次完整功能验收"
  ],
  "noStagedFiles": true,
  "diffSummary": "受审38文件零变更；仅增加evidence独立验证材料和绑定报告，未提交、推送或操作主工作区。",
  "reviewFindings": [
    "blocker V31-B1-001: source/trainlab/fit/parser.py:13 - 只有Protocol，无实际FIT解码器",
    "blocker V31-B1-002: source/trainlab/fit/、source/trainlab/contracts/、source/tools/check_b0_static.py:8 - 目录A和无sys.path补丁约束未落实",
    "blocker V31-B1-003: source/trainlab/fit/storage.py:161,203 - 批准JSON结构被拒，非法引用/值/跨层不一致可入库",
    "blocker V31-B1-004: source/trainlab/fit/storage.py:130 - 默认事实返回完整第4类且DTO偏离批准合同",
    "blocker V31-B1-005: source/trainlab/fit/storage.py:104 - 同字节重复导入改变原有效路径和parsed_at",
    "blocker V31-B1-006: source/trainlab/fit/storage.py:98 - 已有活动报告仍可静默替换依赖事实，无REPARSE_CONFLICT"
  ],
  "manualNotes": "这是首次独立验证，不含历史裁决。所有命令使用派发Python环境；完整命令和实际退出码见evidence清单。未修补产品或受审测试；主Agent仍需独立最终裁决。"
}
```
