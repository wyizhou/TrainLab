# B0相关前置与B1：当前固定版本独立复验

## 本次任务材料

- 任务类型：修复后复验。全新Validator，受审内容只读，不继承或继续旧聊天、不调度、不改变验收、不代写协调记录。
- 目标/编号：ADHOC-0031 B0直接相关目录/JSON前置与B1；ADHOC-0024 AC-01～05/GATE-01～03。复验V31-B1-001～003及关联正常回归，同时验证004～006没有退化；判断结论不限于已列样例。
- 验收及来源：`requirements.md`为原用户目标及已审核拆解摘录，含来源摘要；以客观技术合同而非其中历史状态性措辞为准。原字段、表数、全量采样、完整解析、合法缺失和默认123要求不变。当前代码/README/Schema/测试断言都属受审材料，不能反向定义正确性。
- 规则：`AGENTS.md`、`subagent-templates/validator.md`。材料不含开发者报告、历史裁决、辩护或失败次数；不得搜索原工作区、其它临时目录或会话补读此类内容。
- 工作目录：派发指定的固定副本`trainlab-0031-b1-fix-r2-review-npe5w0e9`，无Git元数据。来源分支`work/adhoc-0031-local-web-system`。
- 受审版本：HEAD `9db8bb1dda5922e85fe42581e27d2428dbc9f195`加未提交产品，`.gitignore`及source共56文件；聚合SHA `5cb22a1f1950c1e73c0624c2ac2981f090c246738dc53f62eb13f9a5996149d8`。`review-snapshot.json`给出每个文件SHA/大小/权限，不只审HEAD。
- 冻结：主Agent已停止产品写入并复制固定文件；你验证前后核对清单。安装/编译/前端构建的忽略生成物可写，不得修改清单内产品、测试、配置和说明。不能在受审文件中补丁消错。
- 材料/入口：`source/pyproject.toml`、`uv.lock`、`schemas/`、`skills/_shared/scripts/trainlab/`、`skills/fit-store/scripts/`、`tests/`、最小Web/React及能力索引；`source/README.md`提供实际入口。正常包名trainlab经打包映射至Skill/scripts，不允许临时sys.path补丁。
- 客观参考：`references/garmin-fit-parsing.md`、`references/longdou.md`及官方链接；`public-sources/protocol-content.txt`、`activity-content.txt`为公开官方正文，SHA分别为`67d986e4649292edbee0c317c7310d22352368a79f6af5e8067a203b6f99da93`、`94d79baa80f554ec84d7d45076eb63d29d865ce6a93d7597101a39ae921e0b30`。可独立检查公开协议和固定SDK源码/Profile，不把SDK个别输出或产品fixture作为唯一标准。
- 技能：`skills/README.md`说明无完整项目技能包，按需使用已有全局技能，不安装/复制技能到全局。
- 依赖：uv及Python3.12可用；自行在evidence创建独立环境，用声明/锁文件安装，不复用开发者产品环境。核对安装导入及Schema与56文件版本逐字节一致、发行包版本与锁文件一致；不能跑旧wheel而声称当前源码通过。
- 输入输出：独立设计合成FIT/SQLite正常、错误和边界，从真实默认解析入口到实际数据库/默认123验收，返回证据和限制。
- 允许修改：仅本副本`evidence/`临时测试、合成实例、日志、独立环境及绑定报告；可产生适用工具的忽略生成物。受审文件和本材料只读，不访问/改写原仓库或历史证据，不提交/推送/PR/CI。
- 错误边界：只用离线合成实例，不读取真实states/FIT/Goal/凭据，不调用真实业务平台或AI。公开依赖安装和官方静态资料访问可用网络，不发送私人数据。未运行或证据不足不能判通过。
- 停止条件：版本漂移、材料污染/缺失、目标歧义影响判断、环境故障无恢复证据时停止受影响部分并向主Agent报告。确定的产品失败可继续不依赖它的验证，不能修补产品或擅自换执行模式。

## 复验要求与客观场景线索

| 编号 | 预期与需核对的实际入口 |
| --- | --- |
| V31-B1-001 | 默认FIT字节入口完整解析，坏长度/CRC/定义/链式尾段/必需结构不得入库。核对实际全部record顺序/数量、标准/Developer/未知字段、0/null、数组/组件/累计、重定义、原生分段、多session、大小端/压缩时间和UTC证据。合法缺失不得被扩大拒绝，未知但可完整解码结构不得丢弃。 |
| V31-B1-002 | 实现物理位于Skill/scripts，tools只有说明，单一公开Schema、正常包安装，离开源码根可导入，无sys.path写入补丁。对违规临时副本应明确拒绝，同时合法文档/测试/前端/读取操作不受无依据限制。静态门不是任意混淆代码的安全证明。 |
| V31-B1-003 | 完整合法DTO及批准segments对象可保存；非法结构/值、引用、身份或SQL/JSON/时间证据矛盾在实际仓储边界拒绝且五表不变。消息和字段身份按编号、名称、来源与定义互相一致；每例合法基线先成功，然后单因素变异，防止另一处非法先报错造成伪覆盖。 |
| V31-B1-004 | 默认事实恰为三类全文和schema_version/身份及解释所需字段/来源闭包，不带整体sensors、records或fit_path；组件父引用也可完整解释，实际API与Schema一致。 |
| V31-B1-005 | 相同FIT字节不同文件名/解析时间的普通导入，原有效行、路径、parsed_at、records、两报告/config及原件保持不变；不把行数相同当数据幂等。 |
| V31-B1-006 | 显式维护核验实际原件SHA、先完整解析；无变化不写，有活动报告且事实变化先REPARSE_CONFLICT并全保旧，无报告合法维护原子更新；解析/子行失败不破坏旧数据，历史周报/config保留。 |

001～003的具体核对输入（只给客观语义，不暗示当前是否通过）：

- 正确长度/CRC的文件中包含字段号255，或session/lap/record为空；区分必需消息存在与结构完整，按官方Activity要求及合同核查。合法可选缺失、invalid、missing/relative时间仍按原要求保留；Developer-only采样不等于空消息。
- HR直接event_timestamp数组原值[10240,11264]后接12bit组件[0,1024]，按Profile scale=1024/累计回绕核对后续12/13秒；同类数组、直接值/展开混合和链式边界自行设计。时间下界0x10000000字段声明raw时应保持数值268435456，不是枚举标签；时间证据和实际字段/SQL必须相符。
- 临时副本含`sys.path = ['x'] + sys.path`、tools中的shell脚本、source根运行文件，均与现有目录A冲突。增加同类必要正负向，不增加未批准规则。
- 合法DTO只改变record的实际timestamp字段而不改SQL/time_evidence；或只改变字典/Message的名称而保留编号和其余身份。检查真实仓储拒绝及五表内容不变，同时检查完整合法的未知身份、正常已知字段/子字段/组件不被误拒。

## 独立验证与适用回归

- 不仅运行现有测试。自行构造或独立核对合成协议字节，说明复杂数值预期的官方依据/手算方法。产品fixture可辅助，不能同时作为被审实现和唯一预期来源。DTO注入可以测仓储，但不能代替真实解码→存储→默认事实流程。
- 正常/损坏FIT走默认文件入口，核对实际库、字典、来源、原生字段与派生字段的身份/单位、消息与record顺序、不规则/重复时间、长集合全量不裁剪、0/null及未知结构。字段/组件不能覆盖、二次换算或静默丢失。
- 检查此次更严格校验与正常输入是否兼容；公开Schema、实际存储和默认输出的交叉引用必须一致。测试器自身输入若不合法应先依据合同确认，不能修改产品以迁就不合法fixture，也不能删减关键正常行为来通过。
- 检查首次导入及维护实际事务失败、外键、12/4/3/3/3列与五表保护；read_view/单进程写入门、等待释放、普通rollback journal和读取不建库等B1前置。
- 回归已有最小FastAPI/生产静态资源/静态根安全、内存历史/时间/Schema表键，前端lint/type/test/build本地执行。B2～B7业务、真实Provider、业务浏览器功能不是本次必须实现内容，不能据其未实现另立缺陷。
- README/索引的当前能力、路径/相对链接与代码一致；说明性文字不能替代功能证据。未穷举的Profile/设备、容量或其他限制明确列出。

## 实际命令和证据

- 自行创建隔离环境：`UV_PROJECT_ENVIRONMENT=<副本evidence内环境> UV_CACHE_DIR=<副本evidence内缓存> uv sync --project source --python 3.12 --locked --extra dev --no-editable`或严格等价安装；记录依赖身份和安装内容与受审快照对应。
- 在source运行：`python -m pytest tests -q -p no:cacheprovider`；`python -m ruff check --no-cache .`；`python -m mypy -p trainlab -p tests --no-incremental`；`python -m compileall -q skills schemas tests`；`python -m trainlab.check_architecture`。
- 在source/frontend运行：`npm ci`、`npm run lint`、`npm run typecheck`、`npm test`、`npm run build`。
- 独立脚本、FIT、SQLite与违规副本仅放evidence，不能向正式states写入。逐命令保存参数、cwd、退出码、关键输出及日志路径；保存前后文件核对。不能只有口述或汇总数字。

## 返回内容

1. 通过/失败/无法判断与精确覆盖，不代替主Agent最终验收。
2. 受审56文件、未提交事实、依赖/安装匹配及前后哈希结果。
3. 场景表：对应要求、类型、输入/步骤/实际入口、预期/实际、命令退出码、证据。
4. 问题表：同类问题沿用V31-B1-001～006，新且独立问题从007起；每项有要求、稳定复现、影响、实际证据，不附猜测。
5. 未验证事项、证据缺口、环境限制和停止原因。
6. 报告通过output绑定保存，独立测试和原始输出留evidence并返回可定位路径。禁止补读历史裁决/Developer报告/计数，不改计划或受审内容。
