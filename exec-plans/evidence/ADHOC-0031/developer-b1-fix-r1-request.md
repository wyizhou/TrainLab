# B0继承缺口与B1首轮修复：Developer任务材料

## 本次任务材料

- 任务类型：问题修复，含原B1尚未完成的FIT解析实现；不是新功能或规划调整。
- 角色：全新Developer，仅按本次给齐材料实现和自查；不继承旧聊天、不调度子任务、不改协调记录。同一工作区只有你一名产品写入者。
- 目标与编号：ADHOC-0031 B1 / ADHOC-0024 T1～T3及T4前置检查，修复V31-B1-001～006；共同修复B0/0031-T1/T2中直接相关的目录与JSON前置。V31-B1-003/004关联旧V31-B0-006，累计历史不清零。
- 验收及来源：ADHOC-0024 AC-01～05/GATE-01～03、0031 U31-05/06；精确实施合同来自 `parent-contract-review-v2.md` 对 `planner-v2.md` 的逐条采用，不是由当前代码、旧测试或前一次派发建议定义。
- 规则：根 `AGENTS.md`、`subagent-templates/developer.md`。规范/示例用项目相对路径及通用AI表述；不要增加解释性代码注释，不删除既有许可/工具必要指令。
- 工作目录与分支：项目根 `.`，`work/adhoc-0031-local-web-system`，派发时明确实际cwd。先核对pwd/分支/HEAD/未提交内容。
- 基线：HEAD `9db8bb1dda5922e85fe42581e27d2428dbc9f195` 加当前未提交产品；受审38文件清单 `b1-review-snapshot.json`，聚合SHA `2d31f4664f988146533561e7517836376e7e4d12fbaa0ab40c6961dd99ad2215`。source仍未跟踪；已有.gitignore与PLAN/MEMORY/执行计划改动，不得丢失或重置。
- 依赖：此前Python3.12/pytest/Ruff/mypy环境可运行，前端已有React/Vite。项目skills/README.md确认无可执行技能包；先检索项目技能再按需用全局技能，不安装或复制技能到全局。只修正与本任务直接相关的前置，不实现B2～B7业务。
- 输入输出：实际合成FIT协议字节 → 经过完整校验的四类数据 → 原子SQLite导入 → 默认123；异常整体失败，已有有效数据/报告不被损坏。交付可执行产品和对应本地测试/依赖/Schema/文档，不再只交Protocol或DTO替身。

### 首次完整材料（均以项目根相对路径）

1. `PLAN.md`、`exec-plans/active/ADHOC-0031-local-web-system.md`、`exec-plans/active/ADHOC-0024-fit-sqlite-parser.md`。
2. `exec-plans/evidence/ADHOC-0031/parent-contract-review-v2.md`，完整阅读，尤其目录A及采纳的T2/01～04、/12边界。
3. `exec-plans/evidence/ADHOC-0031/planner-v2.md`，按上项已采纳条款实施；未采纳建议不变成要求，后续B2～B7仅作接口衔接。
4. `exec-plans/evidence/ADHOC-0031/b1-validation-requirements.md`：本次目标及已采用条款的摘录，不替代原主审核；摘录时状态文字与当前计划不同，以当前实际状态为准，验收不变。
5. `exec-plans/evidence/ADHOC-0031/validator-b1-v1.md`、`parent-b1-v1-triage.md`、`parent-b1-v1-repro.json`、`b1-review-snapshot.json`；前两份完整路径同目录。
6. `exec-plans/evidence/ADHOC-0031/validator-b1-v1-evidence.zip`：原受审产品、独立测试/合成FIT/完整日志及主复现。可解到仓库外临时目录，只读用作失败证据；不要覆盖当前工作区。
7. `references/garmin-fit-parsing.md`、`references/longdou.md`：含官方协议、固定参考SDK/Profile、单位/来源及合法缺失解释；文档不是已验证SDK实现，也不能把参考中的少数字段当解析白名单。按需查公开官方实现/文档，不编辑references。
8. 当前 `source/`，特别是pyproject、trainlab/contracts、trainlab/fit、skills、tests、tools/README。现有运行位置和旧DTO都属于待修受审内容，不能据其存在批准另一套合同。

### 允许修改范围

- `source/skills/**`：批准的产品运行和共享实现；可新增 `fit-store/scripts/`，迁入正确模块。
- `source/trainlab/**`：只为迁移/退出未批准物理实现根；Python导入名可保留，但不能以壳导出继续把实现留在旧根，不能靠运行时sys.path补丁。
- `source/schemas/**`、`source/tests/**`、`source/pyproject.toml`、`source/uv.lock`、`source/README.md`及必要的source内打包配置。选定并锁定实际SDK/依赖版本，提供隔离可安装/可导入证据；不随意改全局环境。
- `source/tools/**`：修正能力索引，移出既有执行检查脚本；tools只放文档，检查实现移至共享scripts或测试位置并保持覆盖。
- `source/frontend/**`：只在公共DTO/目录迁移确实影响既有接口时同步必要类型、测试或构建配置，禁止提前开发B6业务UI或无关样式重构。
- `.gitignore`：仅必要的source依赖锁精确放行/新构建缓存精确忽略，不扩大states放行。
- 临时环境、SDK公开资料、测试输出：仅仓库外隔离临时目录；最终报告由工具output绑定保存，返回所有证据路径供主Agent归档。不可写PLAN/MEMORY、执行计划、本任务材料或已有证据报告/归档。
- 不暂存、提交、推送、开PR、合并，不改仓库/全局设置，不新增或主动运行远端CI；不读取真实states/FIT/Goal/认证/AI密钥，不调用真实Garmin或AI。

## 问题修复补充材料

| 编号 | 客观失败、预期及证据 | 已尝试方法与这次不同之处 |
| --- | --- | --- |
| V31-B1-001 | S01没有可执行decoder；parser只有Protocol。正常/坏CRC/定义/链式等完整入口不可测。 | 首次只做DTO替身/仓储边界。本次必须实现固定SDK/协议适配及产品默认解析入口，不能再延期到B4。 |
| V31-B1-002 | S02及清单证明运行实现放在trainlab根，tools内可执行脚本且修改sys.path，公开Schema未落点。 | 先前用另一根和导出壳绕过物理目录。本次使用正常打包映射/安装解决导入，落实目录A，并增加能发现违规的本地门。 |
| V31-B1-003 | S15批准的segments={items:...}被拒；S18九类非法引用/值/字段和SQL-JSON不一致可提交；S17浅层校验漏额外键。 | 先前只靠json.dumps及浅层容器检查。本次单一公开Schema递归校验＋字段字典交叉/跨层校验，实际仓储边界调用，不只测试示例。 |
| V31-B1-004 | S16返回完整sensors及旧DTO；S17拒绝批准DTO。 | 先前“无records就算默认123”。本次只提供三类全文及解释所需字典/来源闭包，不整体第四类。 |
| V31-B1-005 | S12同字节换名重复导入改fit_path和parsed_at；预期有效五表数据不变。 | 先前无条件UPSERT/删重插。本次区分普通幂等导入和明确维护重解析，不用“行数没变”替代数据无变更。 |
| V31-B1-006 | S13已有报告时records从2条变1条却没REPARSE_CONFLICT；旧报告仍在但失配。 | 先前只保报告行不删除。本次保存前比较依赖事实，有报告变化先冲突，失败保留所有旧值。 |

原有5项基础命令均退出0，不能抵消上述失败。独立39项为21通过/18失败，主Agent另一个合成副本复现一致。S03～S11及S14/S19的表键、全量25001条、0/null/UTC、边界和产品事务回滚等正确行为需要保留。

**累计计数**：B1首次独立验收失败1轮，各新编号首次发现失败1；本次是B1修复尝试1，尚无B1修复复验结果。V31-B1-003/004关联V31-B0-006：旧首次验收失败1、既往修复尝试1、当时修复复验失败0，本次发现继承缺口1；本次公共合同修复会是累计尝试2。不得重命名或把新子任务当清零。历史B0通过只适用于当时命令/快照，不豁免本次缺口。

## 实施要点与错误边界

1. 完整实现T2/01～04既定合同。使用公开官方SDK/固定Profile或等效可核实协议适配，记录版本/选项/实际能力证据；允许在独立环境安装公开依赖、检查官方实现。若SDK分组输出丢失原顺序/invalid/定义等，采用必要的受控适配保留证据，不把“SDK返回多少”当完整。不能用未知消息一律忽略、只支持几项常见运动指标、CRC宽松恢复或任意新上限缩减目标。
2. 消息映射覆盖实际消息及未知可解码结构，原生lap/split/set/length与record区分；标准/Developer/展开字段身份分离，字段重定义/链式片段不覆盖；单位只转换一次。保存可解释字段，剔除未授权私人身份，不开放FIT原字节工具。
3. UTC固定六位Z；start来自可确认session，end用可核验elapsed，不猜摘要timestamp；相对/local/invalid/missing时间保留证据，不造绝对时刻。多session完整保存，不把第一段running当全文件权限，存储与分析范围分开。
4. 必需消息及零record合法性依固定协议/SDK证据判定；不能简单全部零record成功，也不能将合法可选缺失都当损坏。检查全部链长度/CRC/definition/消息与errors，失败无半场写入。
5. 按采纳结构落实basic/summary/segments/sensors/metrics与共用字段字典、来源；strict JSON、坏类型/额外键/有限数、大整数/bytes形式、引用及SQL一致性检查；默认123只附必要定义与来源，必要组件引用也须完整解释。
6. 同字节普通导入不改有效行、原路径、parsed_at或报告。维护入口应明确区分，可无UI；核原件SHA、先完整解析、在允许维护的视图/写入边界更新，无报告变化原子提交，有报告依赖事实变化返回REPARSE_CONFLICT；失败和无变化保持旧状态。单进程写入协调/普通rollback journal协议不能靠未授权REPLACE或活库immutable替代；不提前实现AI宿主。
7. 12/4/3/3＋config列不扩张，不恢复被否决六列；外键实际开启，初始化/重复/错误/维护全过程保护报告/config与原件。
8. 当前独立测试中的旧导入路径、Probe类名称、旧segments基线等是复现定位手段，不是产品API冻结。迁移时可以按原业务预期重写正确回归并记录映射；不得编辑历史证据、删除关键覆盖或弱化断言。修复JSON验证要由完整合法基线逐项变异，不能因另外的坏字段先失败就说本项已覆盖。

## 检查方法与预期

- 先补会失败的合成回归，再实现对应修复，保存实际结果。用符合协议的合成FIT走真实产品解析入口→SQLite→默认123，不依赖私人文件或把SyntheticDecoder当解码测试。
- 覆盖正常/缺失/0/无效值/损坏/缺必需消息/链式尾段/Developer同名和重定义/未知字段/组件与单位/多session/相对时间/长records/默认123/幂等/有报告冲突/首次与维护子行失败/路径及静态根/内存历史等相关正常回归。必要时用选定SDK交叉核对合成fixture合法性；fixture自检不当互操作验收。
- Python3.12在隔离环境由声明依赖运行pytest、Ruff、mypy、compileall、真实JSON Schema及新的架构检查。原命令可因正确物理迁移调整到可运行入口，但不能减少覆盖；说明旧→新命令映射。
- 原基线命令供定位：`cd source && python -m pytest tests -q -p no:cacheprovider`；`python -m ruff check --no-cache .`；`python -m mypy trainlab skills tools tests`；`python -m compileall -q trainlab skills tools tests`；`python tools/check_b0_static.py`。后两处旧物理路径应按迁移结果退出，不保留违规实现来维持命令绿灯。
- 因迁移共享底座，验证最小FastAPI应用/静态安全/时间历史，前端既有lint/typecheck/test/build也做回归；不新增业务页面。
- `git diff --check`、版本/未提交变更清单、隐私与忽略检查。source未跟踪时不能仅用git diff当作完整差异。

## 停止与返回

- 目标/授权/表结构需要改变、SDK能力无法满足完整性且不能在原范围实现、需读取真实实例才能继续、固定基线意外变化、或环境故障无恢复证据：停止受影响工作并最终报告，不自行缩范围或换执行模式。
- 同类两种实质不同修法仍失败，或连续三轮修复验证不收敛，停止并保全证据；考虑旧B0-006历史，不反复试同办法。不向原子任务追加消息；新决策交主Agent，必要时另建新实例。
- 返回中文报告：逐问题根因、这次与旧方法的实质区别、修改/删除/新增文件及目标、实际版本/未提交内容、逐命令与逐场景预期/实际/退出码/日志位置、依赖/SDK证据、仍未实现/未运行/未通过事项及停止条件。未完成如实说明，不能以报告产出或单测绿灯自称B1验收通过。
- 只提交事实报告及证据定位，不修改计划状态；主Agent会固定新版本，派发全新Validator，再亲自验收。
