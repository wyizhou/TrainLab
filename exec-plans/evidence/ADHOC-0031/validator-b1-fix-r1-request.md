# B0相关前置与B1：修复后独立复验任务

## 本次任务材料

- 任务类型：修复后复验；全新Validator，受审内容只读，不继承旧聊天、不自行调度、不修改验收。
- 目标与编号：ADHOC-0031 B0直接相关目录/JSON前置与B1；ADHOC-0024 AC-01～05/GATE-01～03；复验V31-B1-001～006，并检查正常回归。是否通过由你依据当前证据独立判断。
- 验收与来源：`requirements.md`汇集用户目标与已经采纳的Planner/主审核条款及来源SHA，未增加本次要求。摘录中历史状态性文字不代表当前实现；按客观技术要求审查本次固定版本。既有README、示例、测试预期和实现均属受审材料，不能反向修改要求。
- 规则：`AGENTS.md`、`subagent-templates/validator.md`。无历史裁决、开发者报告、开发者辩护或修复次数材料；不要搜索主工作区/其它会话补读这些信息。
- 工作目录：仓库外固定副本 `trainlab-0031-b1-fix-r1-review-uhlaq6oc`，无Git元数据；来源分支 `work/adhoc-0031-local-web-system`。
- 固定版本：HEAD `9db8bb1dda5922e85fe42581e27d2428dbc9f195`加未提交实现；`.gitignore`及source非忽略产品共53文件，聚合SHA `25f7f11d0e31787bddde584f7103de90c7a95522e5b7379521c6ef9affaa8d0f`。`review-snapshot.json`包含逐文件SHA/大小/权限、来源状态及路径变更；不只检查HEAD。
- 冻结方式：主Agent已停止产品写入并复制固定版本。前后检查清单和受审文件；允许的安装/编译/前端生成物须与产品文件区分，不能修改清单内内容或补丁修测试。
- 当前入口/材料：`source/pyproject.toml`、`source/uv.lock`、`source/schemas/`、`source/skills/_shared/scripts/trainlab/`、`source/skills/fit-store/scripts/`、`source/tests/`、最小Web及React；`source/README.md`提供实际安装/检查命令。模块名仍为trainlab，物理位置由正常包映射决定。
- 客观参考：`references/garmin-fit-parsing.md`、`references/longdou.md`及其官方链接；`public-sources/activity-content.txt`、`protocol-content.txt`为公开官方正文副本，对应官方Activity File/FIT Protocol页面。可独立查官方公开文档和固定已声明SDK源码，不把受审说明或SDK输出本身当正确性唯一依据。
- 技能：`skills/README.md`当前无可执行项目技能。按需使用已有全局技能，不安装或复制技能。
- 依赖：Python3.12及uv可用；需在你的隔离目录创建验证环境，按source声明/锁文件安装，不复用已安装产品而不核对版本。正常包映射需安装后导入；不得靠临时sys.path补丁掩盖缺失。主Agent在派发时给出可用解释器/uv位置仅作环境定位。
- 输入输出：独立设计合成FIT/SQLite的正常、错误、边界，验证真实解析→完整校验→入库→默认123以及全部受影响回归；返回实际结果、证据和限制。
- 允许修改：仅副本 `evidence/` 的隔离环境、临时测试、合成数据、日志与本次绑定报告；可产生依赖安装/编译/前端构建的忽略生成物，固定受审文件不能变化。不得修改主工作区、协调文件或历史证据；不提交、推送、开PR、运行远端CI。
- 错误边界：仅离线合成实例，不读取正式states、真实FIT、Goal或凭据，不调用Garmin/AI业务服务。公开声明依赖安装和官方静态文档查阅可用网络，但不带私人数据。没有运行的项不得给通过。
- 停止条件：固定产品变化、材料缺失/污染、目标歧义影响判断或环境故障无恢复证据，停止受影响部分并报告。确定的产品失败可继续不依赖它的其他验证；禁止修改受审内容消错或擅自恢复/换模式。

## 复验范围与客观行为线索

以下是编号对应的要求与待核行为，不给历史裁决或暗示当前结果：

| 编号 | 当前正常/错误/边界预期 |
| --- | --- |
| V31-B1-001 | 实际FIT字节默认入口完整解码，不依赖调用者注入固定DTO。核对全部消息/record次序、链式完整性、大小端/压缩时间、标准/Developer/组件身份、invalid与0、重定义、单位、未知可解码数据、必需消息、多session及UTC证据；坏结构不得恢复造值或保存半场。 |
| V31-B1-002 | 物理实现为批准Skill/scripts，tools仅能力文档，公开Schema单一来源；正常包安装可离开源码根导入，无sys.path补丁。架构检查能识别违反已批准边界的临时副本，不增加新架构禁令。 |
| V31-B1-003 | 合法segments对象及完整DTO可保存；非法结构/值/字典来源组件引用/额外键/SQL与JSON不一致，在实际仓储边界拒绝，五表不变。每项以完整合法基线单项变异，避免因另一处非法先被拒而伪判覆盖。 |
| V31-B1-004 | 默认事实仅三类全文及解释所需字段/来源闭包，包含批准的schema_version和键，不整体返回sensors、records或fit_path；共享Schema与实际API一致。 |
| V31-B1-005 | 同FIT字节不同文件名/解析时间的普通重复导入保持原有效行、路径、parsed_at、records及报告/config不变；不改原件。 |
| V31-B1-006 | 明确维护入口核验原件SHA、先完整解析；无变化不写，有活动报告且依赖事实改变先返回REPARSE_CONFLICT，旧数据全保留；无报告合法维护原子更新，失败保旧，历史周报/config不损坏。 |

### 独立验证和正常回归

- 不只跑现有测试。自己构造或独立核对合成协议输入；产品自带生成器可辅助，但不能既当被审实现又当唯一正确性依据。对复杂字段/协议明确用何来源判定预期。
- 用正常和损坏FIT走实际默认文件入口，并核对数据库及默认事实。DTO注入可用于定位仓储异常，但不能代替解码验收；结构、SDK能力或来源无法证明时标明无法判断，不臆测为通过。
- 至少核对记录全量/重复时间/不规则与长集合、原生分段、真实sport和多运动不冒充running、UTC/相对/无效时间、字段/数组/单位和定义身份、合法缺失、默认123、隐私字段边界，以及初次与维护导入的真实事务失败/外键/五表保护。
- 结合实际入口检查普通导入与维护、只读视图/单进程写入门、并发等待与事务回滚的B1前置。B5跨AI网络视图/真实Provider并非本次必须完成内容，不能把未实现B2～B7自动判成本次新增缺陷。
- 回归此前最小FastAPI/静态根保护、内存历史/时间、Schema表键等已有底座；React生产构建/lint/type/test一并本地检查，业务Web未在本次完成。
- README/索引与实际能力一致、相对链接和路径正确；仅拼写/链接问题与功能/规则问题区分，不扩大修复目标。

## 实际命令与证据要求

以自己的仓库外环境执行 `UV_PROJECT_ENVIRONMENT=<你的evidence内环境> uv sync --project source --python 3.12 --locked --extra dev --no-editable` 或严格等价的锁文件安装；保存版本/依赖及安装结果。独立核对导入的模块和Schema逐字节对应53文件快照，而非碰巧跑到旧wheel或另一个工作区。

在source下运行：

- `python -m pytest tests -q -p no:cacheprovider`
- `python -m ruff check --no-cache .`
- `python -m mypy -p trainlab -p tests --no-incremental`
- `python -m compileall -q skills schemas tests`
- `python -m trainlab.check_architecture`

前端在source/frontend下运行：`npm ci`、`npm run lint`、`npm run typecheck`、`npm test`、`npm run build`。安装/缓存/build生成物不得当源码修改，也不作为已验收功能。独立测试放evidence，临时SQLite/合成FIT也在evidence，不碰正式实例。

逐命令保存完整参数、cwd、退出码和关键输出；大的日志链接到evidence。验证前后保存受审文件清单核对结果。测试适配当前真实入口，不能因为旧探针硬编码路径失效就宣称业务失败，也不能借迁移删掉关键验收。

## 返回格式

1. 结论通过/失败/无法判断及精确范围，不能代替主Agent最终验收。
2. 固定版本、未提交事实、依赖/安装一致性和前后哈希。
3. 场景表：要求、正常/错误/边界、入口/输入、预期/实际、命令退出码与证据。
4. 问题表：沿用V31-B1-001～006，若是同一问题未解决不要改名；新且独立的问题从V31-B1-007起。逐项提供要求依据、稳定复现与影响，不附无法证明的猜测。
5. 已验证范围与未验证/证据不足/环境限制分别列出，客观报告SDK/协议边界。
6. 最终报告通过工具output绑定保存，独立测试及日志在evidence，返回可定位路径；不要写PLAN/MEMORY或其它协调记录，也不要读取历史裁决/Developer报告/失败次数。
