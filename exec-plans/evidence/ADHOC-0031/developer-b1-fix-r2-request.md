# B1第二轮有界修复：Developer完整任务材料

## 本次任务材料

- 任务类型：问题修复。你是全新Developer，不继承/继续旧聊天、不调度子任务、不修改协调记录；本工作区只有你一名产品写入者。
- 目标：ADHOC-0031 B0相关0031-T1/T2和B1 / ADHOC-0024 T1～T4前置；仅修V31-B1-001/002/003剩余解析、架构门、内部一致性问题及同类必要边界，保留004/005/006正常回归，不开发B2～B7。
- 验收及来源：ADHOC-0024 AC-01～05/GATE-01～03；0031 U31-05/06；已审核目录A、T2/01～04及/12合同。原批准要求控制，不由旧测试、现状或SDK部分行为重定义目标。
- 恢复授权：`exec-plans/evidence/ADHOC-0031/user-b1-recovery-r2.md`记录真实用户对“一轮限定这三类问题修复＋重新独立复验”的明确授权。此前已触发停止条件；这不是无限重试许可。
- 规则/角色：根`AGENTS.md`、`subagent-templates/developer.md`；默认不新增解释性代码注释，不删既有许可/必需指令；规范/示例使用项目相对路径及通用AI表述。
- 工作目录与分支：项目根`.`；`work/adhoc-0031-local-web-system`，实际cwd由派发指定。先核对根、分支、HEAD、未提交内容。
- 当前基线：HEAD `9db8bb1dda5922e85fe42581e27d2428dbc9f195`＋未提交53文件产品，[清单]`exec-plans/evidence/ADHOC-0031/b1-fix-r1-review-snapshot.json`，聚合SHA `25f7f11d0e31787bddde584f7103de90c7a95522e5b7379521c6ef9affaa8d0f`。主Agent恢复前已核SHA/大小/权限和产品集合全匹配，索引为空。source未跟踪；`.gitignore`、PLAN/MEMORY及其他执行计划已有修改，保护无关工作，不能用git diff当全部产品差异。
- 依赖现状：Python3.12、uv可用；锁定`garmin-fit-sdk==21.214.0`及`jsonschema==4.26.0`；正常安装及26份安装文件逐字节与source一致已有证据。项目skills只有README，无完整技能包，先检索项目技能再按需使用全局技能，不引入全局配置变化。
- 输入输出：合成FIT真实字节→默认完整解析/字段解释→经过结构和跨层验证的DTO→SQLite→默认123；不完整或自相矛盾输入在写入前失败，五表与原件不变。交付必要实现、回归测试和事实报告，不替主Agent宣称验收完成。

## 首次材料清单（完整读取要求与本轮证据）

1. `PLAN.md`、`exec-plans/active/ADHOC-0031-local-web-system.md`、`exec-plans/active/ADHOC-0024-fit-sqlite-parser.md`；重点区分当前合同、历史未定说明及已采纳补充合同。
2. `exec-plans/evidence/ADHOC-0031/parent-contract-review-v2.md`及`planner-v2.md`；按主审核采纳项执行，未采纳建议不是要求。`b1-validation-requirements.md`是批准要求摘录。
3. 同证据目录`user-b1-recovery-r2.md`、`parent-b1-fix-r1-triage.md`、`validator-b1-fix-r1.md`、`parent-b1-fix-r1-repro.json`、`b1-fix-r1-review-snapshot.json`。此处可向修复Developer提供历史结论/计数，不允许自行修改它们。
4. 同目录`validator-b1-fix-r1-evidence.zip`：SHA `b655807810e9d1a2b90421269a1d6c51941590b2559f56fa788e431816c3d798`。只解压至仓库外；原件包含`review/source/`旧固定产品、`validator/evidence/`三份独立测试及独立编码器、公开Protocol/Activity正文、反例日志与合成数据、`parent/evidence/`主复现。历史证据不可改。
5. 重跑独立测试时，将脚本复制到本轮临时副本的`evidence/`，同级`source/`是本轮产品，带该版本清单、前端构建及按原测试需要提供的公开references。检查脚本的ROOT/清单绑定，避免实际测试到归档旧实现。原脚本的业务断言不能改弱；必要路径适配须明确记录。测试原文及新增测试都保留。
6. `references/garmin-fit-parsing.md`；官方公开协议/Activity正文与SDK Profile对照在归档内，按需查公开来源，不编辑references。SDK/Profile是数值/协议核对资料，不是丢失消息或静默容错的授权。
7. 当前`source/pyproject.toml`、`uv.lock`、`README.md`、`source/skills/fit-store/scripts/`、`source/skills/_shared/scripts/trainlab/`、`source/schemas/`、`source/tests/`、实际工具索引。当前API及正常包映射可沿用，不再次迁移工程或引入运行时sys.path补丁。

## 允许修改范围

- `source/skills/fit-store/scripts/**`、`source/skills/_shared/scripts/trainlab/contracts/**`、`source/skills/_shared/scripts/trainlab/check_architecture.py`：本轮必要解析、校验与本地架构门修复；按原所有权拆分，必要小辅助模块可放共享scripts下，不把所有新逻辑堆到一个核心文件。
- `source/tests/**`、`source/schemas/**`：补充上述问题的正确回归及必要Schema同步，不降低断言、删关键覆盖或修改输入来规避失败。
- `source/skills/fit-store/README.md`、`source/README.md`：只同步直接受影响行为/命令。仅在上述修复确需依赖或打包调整时可改`source/pyproject.toml`/`source/uv.lock`，说明理由并重新锁定安装核对；不任意升级依赖。
- 其他产品文件默认只读；若确需改变储存所有权/数据库事务实现或扩大路径范围，停止受影响部分并报告理由，不擅自扩大。
- 仓库外独立临时目录可写合成数据、公开依赖环境、原始命令日志、快照及补充复现；最终报告由派发output绑定，返回实际证据位置供主Agent归档。
- 不改`.gitignore`、前端、工具索引、PLAN/MEMORY/任何执行计划/既有证据；本轮无必要变更则保持原字节。禁止git add/commit/push/PR/merge，禁止远端CI、全局设置变更、旧代码恢复、真实states/FIT/Goal/认证/密钥访问、真实业务平台/AI请求。

## 客观失败与已尝试方法

基线自测92通过；独立91项79通过/12失败，主Agent在另一固定合成副本复现同样结果。全部12项是实际断言失败，不是安装/入口故障。

| 稳定编号 | 客观复现、预期与实际 | 已尝试修法与本轮要求 |
| --- | --- | --- |
| V31-B1-001 | `test_independent.py::test_V001_required_structure_not_empty_success`的invalid-field-255、empty-session、empty-lap、empty-record四例：正确CRC/长度的非法字段号或空必需消息仍落库；预期拒绝且不建库/不改旧库。`test_followup.py::test_V001_accumulated_hr_array_seeds_later_components`：直接HR event_timestamp数组[10240,11264]之后12bit压缩[0,1024]，SDK与手算后续[12,13]秒，实际[0,1]。`test_V001_valid_profile_timestamp_threshold_raw_value`：0x10000000合法时间下界，value_form=raw应是268435456，实际字符串min。 | 先前只有Protocol；首轮实现固定Profile＋自有协议遍历，但仅查消息存在、累积状态漏数组、日期边界常量误当枚举。先定位语义根因与相关同类边界，再修普遍规则，不写死这6个样例。 |
| V31-B1-002 | `test_independent.py::test_V002_negative_architecture`三种违规副本：共享scripts中`sys.path = ['x'] + sys.path`，tools/probe.sh带shebang实现，source/service.py运行函数。预期本地门拒绝，实际均放行。其他4种负向及当前布局/安装通过。 | 首轮迁移正常包映射已正确；路径门只列若干名字/扩展、AST形态不完整。本轮只补已批准规则的漏检及对应合法反例，不新增无依据架构限制，不重新迁移已正确模块。 |
| V31-B1-003，关联V31-B0-006 | `test_independent.py::test_V003_single_mutation_real_repository`三例：timestamp-field-mismatch、record-message-name、definition-message-name。完整合法基线实际入库后，新ID单点改变record timestamp字段、message_number=20的字段字典message_name为session、或编号18的摘要Message名为record；预期拒绝且五表不变，实际新增1活动/5records。 | 方法A：DTO/浅层Schema，B1首次已证明不闭合；方法B：公开递归Schema＋部分交叉检查，当前仍漏身份名字与实际timestamp值。应核验同一事实所有表示，不能仅加某一个名称的if或因另一个坏字段先拒绝而声称覆盖。 |

累计历史不可清零：B1首次验收失败1；修复尝试1及修复后复验失败1。本轮是B1尝试2。公共合同V31-B0-006原首次失败1、既往修复1且当时复验失败0，后来继承缺口再现1；上一轮累计修复2仍失败，本輪为累计尝试3。旧通过只保留原时点覆盖，不追改日志；004/005/006上一轮已测通过。真实用户授权本轮解除停止，不意味着旧历史归零或下一轮自动许可。

## 错误边界与实施要求

1. 先保存失败原因分析及将采用的不同方法，再补/重跑红灯，再实现并保存绿灯与全量回归。可以在本次实现中完成必要自查；如果不能在授权范围闭合，应返回未解决事实，不自启另一个修复轮次。
2. 标准/Developer/未知可解码字段、字段重定义、压缩及累积组件、所有record原序/重复时间/0/null/链式与多session不能被修坏。不要通过忽略未知消息、只取常见字段、丢坏消息、排序去重、硬编码样本值或缩小运动范围来通过。
3. 区分字段未定义、协议invalid、合法可选缺失及时间的missing/relative/absolute；不得因修复“空必需消息”而拒绝原合同允许的缺失/相对时间记录。也不得反过来以允许可选缺失为由放行全空的必需消息。依据固定协议与批准合同处理，发现真实冲突应停止并附客观证据。
4. 日期/时间的原值、SQL UTC、time_evidence、value_form保持一致；时间边界常量不是普通枚举值。组件累计要处理数组序列及直接/展开值混合，单位只转换一次。
5. 字段身份从可核对的message_number/name、chain、definition、field_number和来源建立一致对应。既有全局Profile能解释的身份不能通过同时改名绕过；未知厂商消息仍保留合法未知状态，不能自创私有语义。完整合法基线逐因素变异，检查实际仓储，失败五表内容不变，不能仅测内部函数或JSON示例。
6. public Schema/解释字典保持单一来源；不要把SDK依赖重复复制进另一个影子字典或引入跨层私有导入来掩盖身份验证。若实现涉及共享模块，遵循既有所有权，正常打包安装，不改sys.path。
7. 四张业务表12/4/3/3及已授权config三列不扩张。实际FIT字节SHA、完整采样、全文报告、UTC六位Z、默认123最小闭包、普通无变更幂等、REPARSE_CONFLICT、显式维护与写入门/read view回归保持。

## 实际检查与预期结果

- 隔离Python3.12正常非editable安装：`UV_PROJECT_ENVIRONMENT=<隔离环境> UV_CACHE_DIR=<隔离缓存> uv sync --project source --python 3.12 --locked --extra dev --no-editable`。修改后重装并逐文件比对已安装模块/Schema，不能运行旧wheel报告新源码通过。
- `cd source && <python> -m pytest tests -q -p no:cacheprovider`；`<python> -m ruff check --no-cache .`；`<python> -m mypy -p trainlab -p tests --no-incremental`；`<python> -m compileall -q skills schemas tests`；`<python> -m trainlab.check_architecture`。预期所有适用门退出0，已有测试与新增缺陷回归真实通过，不隐藏弃用警告。
- 重跑三份现有独立脚本共91项，期望12个原失败修复且79个通过项不退化；归档对照日志。它们是已知回归下限，不是完整目标上限。新回归须覆盖同类必要正常/错误/边界，尤其累积数组、时间边界、合法缺失、未知身份、完整合法单因素变异与五表保旧。
- 本轮不修改前端；在隔离副本运行现有npm ci/lint/typecheck/test/build以供跨层正常回归、ASGI静态产物检查，构建产物不作为源码写回。若现有独立脚本需要清单，固定本轮真实文件集合而不是伪造旧53文件匹配。
- `git diff --check`、分支/HEAD/索引、产品所有未跟踪文件清单及逐路径SHA差异。保存53文件基线与本轮新增/删除/修改清单，证明无越界文件改动、无私人数据。

## 停止条件和返回

- 新目标/验收/架构例外、超出三类问题的实质范围、需私人实例、基线意外变化、无法在原合同内解释输入、基础设施/环境故障无恢复证据时，停止受影响工作并在最终报告交主Agent。不要改验收迁就代码/测试，不换外部/前台执行模式。
- 不与主Agent续聊补材料；需要新决策时保留证据并结束，主Agent核对后按用户约定处理。不得自行派发、恢复旧子任务或续轮。已有“两种修法”停止事实由本次真实用户仅放行这一轮；本轮仍失败不能自动继续。
- 返回中文事实报告：逐问题根因/本次方法与旧方法差别；准确修改清单/版本/未提交状态；逐命令cwd/参数/退出码/关键输出；每类正常/错误/边界预期与实测；红绿日志和安装匹配；回归/新测试数量；完整临时证据路径；未通过/未运行/残余风险及停止条件。
- 最终文本由output绑定保存，不改计划。Developer自查通过不是独立验收，主Agent将固定受审材料给全新Validator后亲验。
