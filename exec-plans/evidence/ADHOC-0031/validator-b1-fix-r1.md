# B0 相关前置与 B1 修复后独立复验

## 结论：失败

当前固定版本的 **V31-B1-001、002、003 未满足要求**；V31-B1-004、005、006 在本报告实际覆盖范围内通过。正常解析、事务保护和前后端底座有实测通过证据，但不能据此宣布完整 B1 通过。本报告不替代主 Agent 最终验收。

- 原有 Python 测试：**92 通过**。
- 前端测试：**3 通过**；安装、lint、typecheck、生产构建通过。
- 独立测试：**91 个，79 通过、12 失败**。失败均为产品实际行为与断言不符，不是安装或测试入口错误。
- 未修改受审实现、原测试、配置、文档或协调记录；未访问原工作区、历史报告、真实 states/FIT、凭据或业务 Provider。

## 1. 固定版本与环境

已完整阅读 `PLAN.md`、`AGENTS.md`、`subagent-templates/validator.md`、`validation-request.md`、`requirements.md`、`review-snapshot.json`，并核对当前代码、Schema、原测试和实际入口。协议预期依据随附官方正文及锁定 SDK Profile，不以产品 README 或原测试断言作为正确性的唯一来源。

| 项目 | 实际结果 |
|---|---|
| 副本 | `trainlab-0031-b1-fix-r1-review-uhlaq6oc`，无 Git 元数据 |
| 来源分支 | `work/adhoc-0031-local-web-system`，来自清单，不另访问来源工作区 |
| 来源 HEAD | `9db8bb1dda5922e85fe42581e27d2428dbc9f195` |
| 受审内容 | HEAD 加未提交实现；按清单核对 `.gitignore` 和 source 共 53 文件，不把 HEAD 单独当受审产品 |
| 验证前聚合 SHA-256 | `25f7f11d0e31787bddde584f7103de90c7a95522e5b7379521c6ef9affaa8d0f` |
| 验证后聚合 SHA-256 | `25f7f11d0e31787bddde584f7103de90c7a95522e5b7379521c6ef9affaa8d0f` |
| 文件核对 | 53/53 的 SHA、大小、权限前后均匹配；差异为空 |
| Python | 独立 `evidence/venv`，Python 3.12.13 |
| 安装 | `uv sync --locked --extra dev --no-editable`；缓存为 `evidence/uv-cache`，环境为 `evidence/venv` |
| 关键依赖 | `garmin-fit-sdk==21.214.0`、`jsonschema==4.26.0`；全部 40 个已安装发行包版本经名称正规化后与 `uv.lock` 核对一致 |
| 实际导入 | 从 `evidence/`、离开 source 根导入正常安装包；逐一比对全部映射包顶层文件及 Schema，内容与固定副本完全一致，没有 sys.path 补丁或旧 wheel |
| 暂存 | 副本无 Git，未执行暂存/提交；不据此声称重新检查过原仓库索引 |

证据：`evidence/hashes-before.json`、`hashes-after.json`、`install.log`、`install-identity-final.log`。安装、编译和前端构建仅产生允许的生成物。

## 2. 独立检查方法与协议依据

独立编码器为 `evidence/independent_fit.py`，**没有导入产品解码器、产品测试或产品字节生成器**：

- 依据 `public-sources/protocol-content.txt` 手工构造 Definition/Data、大小端、链式头、压缩时间和 CRC；CRC 使用独立位运算实现，并与固定 SDK 交叉核对。
- 正常基线包含 file_id、带四个必需时间字段的 session/lap、实际 record、activity。速度、海拔、elapsed 等预期手工按 Profile 的 scale/offset 计算。
- 复杂组件使用固定 Profile 的字段号、位宽、scale、累积标志核对；HR 数组用手工计算及 SDK 两种方式交叉证明预期。
- 通过实际 `import_fit_file` 默认入口检查 FIT → 完整 DTO 校验 → SQLite → `get_activity_facts`；协议用例未注入替代 decoder。
- 仓储变异先实际保存完整合法基线，然后每例只变更一个目标因素。维护用例先布置旧合法解释，再由真实默认解码器读取原字节维护，不以注入固定 DTO 代替维护解析。

协议证据及哈希见 `evidence/protocol-oracles.log`：

- Activity 正文 SHA：`94d79baa80f554ec84d7d45076eb63d29d865ce6a93d7597101a39ae921e0b30`。
- Protocol 正文 SHA：`67d986e4649292edbee0c317c7310d22352368a79f6af5e8067a203b6f99da93`。
- 实际安装 SDK `profile.py` SHA：`bde1a44db3f32d35fba6997edc552dd3238d218ffc2e718381194fd9921ed6fb`。

## 3. 场景与分项结果

表内“通过”只覆盖所列场景；独立测试命令整体失败时，其中通过的用例仍有 JUnit 和逐例日志可核对。

| 要求/类型 | 输入、入口与预期 | 实际结果 | 证据 |
|---|---|---|---|
| V31-B1-001 正常协议 | 12/14/18 字节头、零头 CRC、大小端；真实导入并读库 | 8 组合通过；速度 2.25m/s、海拔 6m、结束取 start+23.125s，不用 timer 或摘要 timestamp | `independent.log`，`test_V001_complete_real_entry` |
| AC-02 全量/顺序 | 30,007 条真实 record，重复时间、不规则和逆序时间 | 全量保存、索引连续；逐行验证时间和心率，无插值或排序重编号 | 同日志 `test_V001_full_long_sequence` |
| V31-B1-001 时间边界 | relative、invalid、missing；压缩时间含 32 秒回绕、Definition 无 timestamp 情况 | 对应 UTC 为 NULL 或正确时刻，时间证据准确；重定义字段 ID 分开 | 同日志 `time_evidence`、`compressed_and_redefinitions` |
| V31-B1-001 多运动/链 | 同文件多 session，加第二完整链；running/cycling/swimming | 保存全部 session 和 records，整体 sport=NULL，不拿第一段 running 冒充整场 | 同日志 `multisession_and_chain` |
| V31-B1-001 字段/来源 | Developer 同名不同来源、重定义、invalid/0、字节数组、超精确整数、未知厂商消息 | 数据、别名和定义分开；未知值保留；原生 lap/length/segment_lap/set/split/split_summary 均保留 | 同日志相关用例 |
| V31-B1-001 组件正常回归 | speed/distance 累计换算，直接 enhanced_speed 与展开值并存；HR 压缩数组 | 通过所测正常组合，但后续 HR **直接数组作为累积起点**失败，详见问题表 | 两份独立日志 |
| V31-B1-001 错误协议 | CRC、截断、尾部垃圾、未定义本地号、缺必需消息、零 record、不完整后链、坏类型/长度、非有限数、重复字段、缺 Developer 描述 | 15 类均拒绝且不建库；另对已有五表实例验证坏 CRC/后链/缺 session 均不改旧数据 | `independent.log`、`final-boundaries.log` |
| V31-B1-001 完整性/数值边界 | invalid 字段号255、空必需消息、HR 累积数组、绝对时间下界 | **失败，6 例**；可入库的坏结构或错误数值，详见下文 | `independent.log`、`followup.log`、`reproduction-details.json` |
| V31-B1-002 安装与物理目录 | 正常 wheel、离源码根导入、单一公开 Schema、当前目录检查 | 当前落点及安装通过，Schema 逐字节一致；原架构命令退出0 | 安装/架构日志 |
| V31-B1-002 违规副本 | 在 evidence 复制清单文件再单点放入违规文件/代码 | root-package、tools Python、Skill/scripts 外代码、sys.path.insert 被拒；**另3种违规漏检** | `independent.log`，`test_V002_negative_architecture` |
| V31-B1-003 仓储合同 | 完整合法 DTO 含合法 segments 对象；24 种单项变异 | 合法基线均成功；21种非法结构/数值/引用/顺序/SQL-basic/时间证据被拒且五表不变；**3种内部矛盾被写入** | `independent.log`、`reproduction-details.json` |
| V31-B1-004 默认123 | 原生全文+Developer 摘要+record-only Developer 来源；独立计算引用及父组件闭包 | **通过**：恰为批准7个顶层键；三类全文相等；仅所需字段及 d0 来源，不带 d1、record 字典、fit_path、sensors 或 records；共享 Schema 校验通过 | `test_V004_exact_minimal_closure` |
| V31-B1-005 普通重复 | 同字节不同文件名、不同 parsed_at，已存在活动/周报告/config | **通过**：身份相同，五表、原路径、解析时间、记录、原件及数据库文件字节均不变 | `test_V005_actual_duplicate_different_filename` |
| V31-B1-006 显式维护 | 无变化、SHA 不符、已有报告事实改变、无报告更新、子行失败、通过 SHA 后解析失败 | **通过**：无变化不写；SOURCE_CONFLICT / REPARSE_CONFLICT；真实默认维护成功或整场回滚；保留原件/路径、历史周报及 config | `test_V006_maintenance_sha_noop_conflict_update_rollback`、`followup.log` |
| AC-01/04/05 事务和键 | 真实首次导入第3条 record 触发 SQL ABORT；孤儿外键；表结构 | 整场回滚；外键拒绝孤儿；12/4/3/3/3列正确；已有周报/config 保留 | `independent.log` |
| /12 只读和写入门 | read_view 内尝试写入，另一线程实际 import；超时后释放；WAL 实例；不存在的库 | 只读拒写；writer 等待，视图退出后提交；RUN_BUSY 可恢复释放；拒绝 WAL，读取不创建库，无遗留 sidecar | `independent.log`、`final-boundaries.log` |
| 零记录边界 | 零 record 的 FIT；空 records DTO；不存在活动 | FIT 拒绝；仓储结构可承载空集合；不存在活动明确 ACTIVITY_NOT_FOUND。未把空集合测试当零 record FIT 合法证明 | 两份独立日志 |
| B0 Web/前端 | 实际 React 生产产物由安装包 create_app 提供；health/未知API；遍历/合成私有文件/静态子链接/根链接 | 通过；127.0.0.1:8080 合同，无后台任务；网页和 JS 实际可取，私有路径404，静态根链接拒绝 | `followup.log`、前端五份日志 |
| B0 JSON/内存/时间 | 重复键、NaN/Infinity/大整数；快照/clear/naive时间；跨UTC日期、固定六位小数、周窗口、4点边界 | 通过；无额外持久化文件 | `independent.log`、`followup.log` |
| 文档/索引 | 实际能力、B2～B7未实现声明、FIT README 相对链接 | 所查链接有效；未将未来业务接口当当前可用服务。README 的完整解析描述不能覆盖下列实测失败 | 代码/文档人工核对及 `test_fit_readme_relative_links` |

## 4. 问题表与稳定复现

沿用既有编号；下列都属于给定六项行为中的问题，没有另设 V31-B1-007。

### V31-B1-001：结构完整性及部分协议数据解释仍失败

**依据**：AC-02/04、0031-T2/02～03，完整消息/定义检查、来源和单位准确、不以缺损/误解码结果当完整入库。官方 Protocol 明确255是 invalid field number；Activity 正文明示 summary 的四个必需时间字段，以及 record 的 timestamp 和至少一个其他值。这里不把“缺可选字段”或已批准的 missing 时间证据当缺陷。

1. **非法字段号及空必需消息可成功落库。**
   - 输入均带正确长度和 CRC：在完整基线上添加字段号255，或分别将 session、lap、唯一 record 换为空字段消息。
   - 执行 `test_independent.py::test_V001_required_structure_not_empty_success` 四个参数；预期明确拒绝、不建库。
   - 实际四例都成功返回 activity_id、建立数据库，并可读 ActivityFacts；空 record 还生成缺失时间的空采样行。
   - 位置：`source/skills/fit-store/scripts/wire.py:118-133` 未拒绝255；`parser.py:40-79` 仅检查消息存在/部分计数，空必需消息可过。
   - 证据：`independent.log` 的4个失败；`reproduction-details.json` 保存成功写入的 facts/records 和合成 FIT。

2. **HR 完整时间数组未成为后续压缩组件的累积起点。**
   - 合成 `hr.event_timestamp=[10240,11264]`，即 `[10,11]` 秒；随后 `event_timestamp_12` 编码两个12位值 `[0,1024]`。
   - 固定 Profile 指明目标为 accumulated、scale=1024；依照12位回绕，正确后续值是 `[12,13]` 秒。锁定 SDK 对同一字节也返回 `[12,13]`，无 errors。
   - 实际默认导入成功，但数据库保存展开值 **`[0.0,1.0]`**。
   - 位置：`source/skills/fit-store/scripts/profile_fields.py:131-132` 仅在直接值为 int 时更新累积状态，数组被遗漏。
   - 复现：`test_followup.py::test_V001_accumulated_hr_array_seeds_later_components`；日志 `followup.log`。合成 FIT/SQLite 在 `followup-temp/test_V001_accumulated_hr_array0/`。
   - 影响：第四类原生HR解释出现静默错误；不是本轮不启用HR合并的问题，也没有要求补造 record。

3. **绝对时间下界被错误写成枚举字符串。**
   - 原始 timestamp=`0x10000000`（268435456，合法绝对时间下界）。
   - 字典声明 `value_form=raw`，预期对应字段保存原始数值。
   - 实际字段值是 **`"min"`**，而 SQL/`time_evidence.raw` 仍按268435456处理，形成自相矛盾的解释。
   - 位置：`profile_fields.py:55-64` 对 date_time 的 Profile 边界常量套用一般枚举转换。
   - 复现：`test_followup.py::test_V001_valid_profile_timestamp_threshold_raw_value`；`followup.log`。原始时间证据并未全部丢失，但不能把该字段称为原值。

### V31-B1-002：架构检查漏检已禁止的简单违规

**依据**：已审核目录/所有权条款：运行实现物理位于 Skill/scripts；tools 仅能力说明；禁止运行时 sys.path 补丁，并要求本地检查识别违规副本。没有新增目录或调用禁令。

在每个独立清单副本先运行 `check_layout` 确认基线通过，再仅做以下一项变异：

| 变异 | 预期 | 实际 |
|---|---|---|
| `skills/_shared/scripts/probe.py` 内 `sys.path = ["x"] + sys.path` | 拒绝运行时路径补丁 | 未报错 |
| `tools/probe.sh` 放入带 shebang 的脚本 | 拒绝 tools 执行实现 | 未报错 |
| `source/service.py` 放入运行函数 | 拒绝 Skill/scripts 之外的运行实现 | 未报错 |

位置：`source/skills/_shared/scripts/trainlab/check_architecture.py:16-41`；只枚举若干根名、只查 tools 下 `.py`、仅识别特定 AST 形状。当前产品物理落点和非editable安装本身通过，**失败在要求的负向检查能力**。

复现：`test_independent.py::test_V002_negative_architecture[sys-assignment/tools-shell/root-runtime]`；`independent.log`，对应副本在 `independent-temp/`。

### V31-B1-003：仓储允许相互矛盾的字段身份/时间值

**依据**：AC-04，0031-T2/02～03 的完整 DTO、字段字典引用/身份交叉检查、记录时间证据和 SQL/JSON一致性；仓储应拒绝非法输入而保持五表不变。

每例都先用真实 FIT 解析结果完成一次合法保存，再深复制同一完整基线，单项变异后用新活动ID调用实际 `import_activity`：

| 单项变异 | 预期 | 实际 |
|---|---|---|
| 第一条 record 的 timestamp 字段值增加1000，SQL时间与 time_evidence 保持原值 | 拒绝同一时间的互相矛盾证据 | 成功保存 |
| 心率字段定义 `message_number=20`，只把 `message_name` 改为 `session` | 拒绝相互矛盾的消息身份 | 成功保存 |
| 摘要 Message 的编号仍18、字段字典仍session，只把 Message 名称改为 `record` | 拒绝 Message 与字段字典身份矛盾 | 成功保存 |

每例五表行数从 **2/10/1/1/1 → 3/15/1/1/1**；不是因已有相同ID而短路，也不是另一个非法字段提前拒绝。报告/config 未损坏，但不该写入的活动和5条记录实际持久化了。

位置：`source/skills/_shared/scripts/trainlab/contracts/json_validation.py:138-190`：身份比较只覆盖编号、chain、definition及来源；时间检查只比较 SQL 与 time_evidence，没有比较实际 timestamp 字段。Schema 对消息名只做字符串/NULL 类型检查。

复现：`test_independent.py::test_V003_single_mutation_real_repository[timestamp-field-mismatch/record-message-name/definition-message-name]`。证据：`independent.log`、`reproduction-details.json` 及 `reproduction-data/`。其余21种非法变异拒绝正常，不能推导这3种也安全。

## 5. 实际命令、退出码与证据

所有子命令的完整绝对参数、cwd、退出码和用时在 `evidence/commands.jsonl`，完整输出在同名 `.log`。以下为相对副本根的便于阅读写法；`P` 是该副本 `evidence/venv/bin/python` 的绝对路径。命令通过 `evidence/run.py` 执行并保存日志，没有仅凭口述记通过。

安装命令设置 `UV_CACHE_DIR=<副本>/evidence/uv-cache`、`UV_PROJECT_ENVIRONMENT=<副本>/evidence/venv`，实际使用 `/opt/homebrew/bin/uv`，`--python /tmp/trainlab-b1-fix-r1-ux1yV8/verify-venv/bin/python`。所给解释器仅用于创建独立环境，未读取/改写其开发材料。

| cwd | 实际命令摘要 | 退出码 | 关键输出/日志 |
|---|---|---:|---|
| 副本根 | 所给 Python 执行 `evidence/check_snapshot.py before` | 0 | 53文件匹配；`hashes-before.log` |
| 副本根 | `/opt/homebrew/bin/uv sync --project source --python <上述解释器> --locked --extra dev --no-editable` | 0 | 安装40包；`install.log` |
| evidence | `$P check_install.py`，安装后及结束前各一次 | 0/0 | 映射模块/Schema哈希一致，最终核对全部发行包；`install-identity*.log` |
| source | `$P -m pytest tests -q -p no:cacheprovider --basetemp <evidence>/product-pytest-temp` | 0 | 92 passed；`pytest.log` |
| source | `$P -m ruff check --no-cache .` | 0 | All checks passed；`ruff.log` |
| source | `$P -m mypy -p trainlab -p tests --no-incremental` | 0 | 31 source files，无问题；`mypy.log` |
| source | `$P -m compileall -q skills schemas tests` | 0 | `compile.log` |
| source | `$P -m trainlab.check_architecture` | 0 | 基线通过；`architecture.log`，不代表负向变异通过 |
| source/frontend | `npm ci` | 0 | 137 packages，0 vulnerabilities；`npm-ci.log` |
| source/frontend | `npm run lint` | 0 | `frontend-lint.log` |
| source/frontend | `npm run typecheck` | 0 | `frontend-type.log` |
| source/frontend | `npm test` | 0 | 3 passed；`frontend-test.log` |
| source/frontend | `npm run build` | 0 | Vite生产产物输出到既定web目录；`frontend-build.log` |
| evidence | `$P -m pytest test_independent.py -v -p no:cacheprovider --basetemp <evidence>/independent-temp --junitxml <evidence>/independent.xml` | **1** | **68 passed, 10 failed**；`independent.log` |
| evidence | `$P -m pytest test_followup.py -v -p no:cacheprovider --basetemp <evidence>/followup-temp --junitxml <evidence>/followup.xml` | **1** | **5 passed, 2 failed**；`followup.log` |
| evidence | `$P reproduction_details.py` | 0 | 成功收集已复现失败的落库事实，不表示产品通过；`reproduction-details.log/.json` |
| evidence | `$P protocol_evidence.py` | 0 | 固定公开正文/Profile哈希、字段语义和独立CRC核对；`protocol-oracles.log` |
| evidence | `$P -m pytest test_final_boundaries.py -v -p no:cacheprovider --basetemp <evidence>/final-boundaries-temp --junitxml <evidence>/final-boundaries.xml` | 0 | 6 passed；`final-boundaries.log` |
| 副本根 | `$P evidence/check_snapshot.py after` | 0 | 53文件匹配且未变；`hashes-after.log` |

警告如实保留：Python测试有 Starlette/httpx 和 anyio 弃用警告；npm 有 fsevents install-script 提示。相关命令均实际成功，未为了消警告变更依赖。

## 6. 未验证事项、边界与归档

- **无法据本轮证据判断**所有124种 Profile 消息、所有字段/子字段/组件组合及所有设备的端到端正确性；发现HR数组反例后，尤其不能将其他少量组件通过推广为完整映射正确。未运行海量随机协议模糊测试。
- 实测长集合为30,007条，证明该规模全量/原序，不宣称无限容量或已完成后续模型发送容量策略。
- 没有通用零 record Activity 合法例外的官方证据；本轮未放宽，亦未把仓储可存空数组当协议例外。
- 未访问私人FIT、真实运动平台/AI Provider、认证/Goal；未知厂商字段只证明结构保留，不证明其私有语义或所有未知身份信息均可自动识别。
- B2～B7 的真实查询授权、报告生成、同步、AI运行视图和完整业务Web不属于本次验收；没有把它们未实现另立缺陷。
- 最小Web通过真实ASGI客户端提供生产产物验证，未做真实浏览器交互、视觉验收或启动实际8080监听进程；8080是已检查的应用合同。
- 无环境/材料阻塞，未发生受审版本漂移；没有修改实现来消除失败。所有独立脚本、合成FIT/SQLite和日志都位于本副本 `evidence/`。
- 建议归档本报告，以及 `evidence/*.py`、`*.log`、`*.json`、`*.jsonl`、`*.xml` 和各测试临时实例/违规副本、`reproduction-data/`。`venv/`、`uv-cache/` 和编译缓存属于可重建隔离环境，不必作为源码交付。

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "not-applicable",
      "evidence": "本任务为只读Validator，不授权实现修补；53个受审文件前后SHA、大小、权限完全一致，仅新增隔离证据及绑定报告，未扩大到B2～B7。"
    },
    {
      "id": "criterion-2",
      "status": "satisfied",
      "evidence": "独立协议编码器、91个独立用例、实际SQL/默认事实反例、完整命令日志及前后清单可复核；明确报告79通过12失败，而非宣称产品通过。"
    }
  ],
  "changedFiles": [
    "evidence/run.py",
    "evidence/check_snapshot.py",
    "evidence/check_install.py",
    "evidence/independent_fit.py",
    "evidence/test_independent.py",
    "evidence/test_followup.py",
    "evidence/test_final_boundaries.py",
    "evidence/reproduction_details.py",
    "evidence/protocol_evidence.py",
    "evidence/commands.jsonl",
    "evidence/hashes-before.json",
    "evidence/hashes-after.json",
    "evidence/reproduction-details.json",
    "绑定报告 validator-b1-fix-r1.md；其余生成日志/XML/合成实例见evidence，无受审文件改动"
  ],
  "testsAddedOrUpdated": [
    "evidence/test_independent.py：78个用例，68通过10失败",
    "evidence/test_followup.py：7个用例，5通过2失败",
    "evidence/test_final_boundaries.py：6个用例，6通过"
  ],
  "commandsRun": [
    {"command":"uv sync --project source --python <授权解释器> --locked --extra dev --no-editable","result":"passed","summary":"evidence隔离环境安装40包；完整参数见install.log"},
    {"command":"python check_install.py","result":"passed","summary":"正常安装的全部映射文件及Schema与快照一致；40包版本匹配锁文件"},
    {"command":"python -m pytest tests -q -p no:cacheprovider --basetemp <evidence>/product-pytest-temp","result":"passed","summary":"92 passed"},
    {"command":"python -m ruff check --no-cache .","result":"passed","summary":"All checks passed"},
    {"command":"python -m mypy -p trainlab -p tests --no-incremental","result":"passed","summary":"31 source files，无问题"},
    {"command":"python -m compileall -q skills schemas tests","result":"passed","summary":"退出0"},
    {"command":"python -m trainlab.check_architecture","result":"passed","summary":"受审基线退出0；另有负向用例失败"},
    {"command":"npm ci","result":"passed","summary":"安装成功，0 vulnerabilities"},
    {"command":"npm run lint","result":"passed","summary":"退出0"},
    {"command":"npm run typecheck","result":"passed","summary":"退出0"},
    {"command":"npm test","result":"passed","summary":"3 passed"},
    {"command":"npm run build","result":"passed","summary":"React生产构建成功"},
    {"command":"python -m pytest test_independent.py -v -p no:cacheprovider --basetemp <evidence>/independent-temp --junitxml <evidence>/independent.xml","result":"failed","summary":"68通过10失败，退出1"},
    {"command":"python -m pytest test_followup.py -v -p no:cacheprovider --basetemp <evidence>/followup-temp --junitxml <evidence>/followup.xml","result":"failed","summary":"5通过2失败，退出1"},
    {"command":"python -m pytest test_final_boundaries.py -v -p no:cacheprovider --basetemp <evidence>/final-boundaries-temp --junitxml <evidence>/final-boundaries.xml","result":"passed","summary":"6通过，退出0"},
    {"command":"python reproduction_details.py","result":"passed","summary":"保存7项反例实际落库详情；非产品通过"},
    {"command":"python protocol_evidence.py","result":"passed","summary":"公开文本/Profile哈希、关键语义、CRC核对"},
    {"command":"python evidence/check_snapshot.py before；python evidence/check_snapshot.py after","result":"passed","summary":"两次均53文件匹配，聚合SHA相同"}
  ],
  "validationOutput": [
    "总体失败：V31-B1-001、002、003存在确定反例；004、005、006在已测范围内通过。",
    "独立91例：79通过12失败；原测试92通过，前端3通过。",
    "源码聚合SHA前后均25f7f11d0e31787bddde584f7103de90c7a95522e5b7379521c6ef9affaa8d0f。",
    "全部实际参数、cwd和退出码见evidence/commands.jsonl；输出及反例见对应log/XML/JSON。"
  ],
  "residualRisks": [
    "V31-B1-001：非法字段号/空必需消息可入库，HR数组累积错误，date_time下界原值被写成min。",
    "V31-B1-002：sys.path赋值、tools shell、根运行文件三个已禁违规形态漏检。",
    "V31-B1-003：时间字段/证据及消息身份矛盾可在仓储边界持久化。",
    "未穷举全部Profile/设备；无私人实数据、业务Provider、真实浏览器或无限容量验证。"
  ],
  "noStagedFiles": true,
  "diffSummary": "受审产品和原测试零修改；仅新增evidence内独立脚本、日志、合成数据/环境及本绑定报告。",
  "reviewFindings": [
    "blocker: V31-B1-001 - source/skills/fit-store/scripts/wire.py:118、parser.py:40、profile_fields.py:62/131存在可复现完整性及数值反例。",
    "blocker: V31-B1-002 - source/skills/_shared/scripts/trainlab/check_architecture.py:16，三个已批准禁止边界的变异未被拒绝。",
    "blocker: V31-B1-003 - source/skills/_shared/scripts/trainlab/contracts/json_validation.py:138-190，内部矛盾DTO未被拒绝且写入数据库。"
  ],
  "manualNotes": "这是验证任务完成报告，不是产品通过结论。副本无Git；未暂存文件，也未重新读取原工作区索引。主Agent仍须审核这些客观问题及最终验收。"
}
```
