# ADHOC-0034 / 0034-T04 修正交接后的独立复验

## 本次任务材料

- 任务类型/角色：修复后复验，全新Validator，不继承旧会话，不自调度、不改受审物。核当前是否满足要求，不接收历史裁决/开发辩护。
- 目标/验收/来源：inputs/requirements.md的H34-01～07及inputs/approved-decomposition.md；用户要求最新官方并行Harness，保护既有业务。仅文档/规则/项目技能与主协调交接，不是业务功能或调度器实现。
- 规则及入口：先读根PLAN、AGENTS、本任务，再核两组实际PLAN、0034执行计划、AGENTS和Validator模板。历史业务/失败状态是被保护对象，不作为本轮通过依据。不要阅读当前或旧Developer报告、自查结论、旧Validator报告/脚本/主裁决来决定结果；可仅计算其SHA以核保全。
- 工作目录/分支：配置cwd是无Git的物理review根。C34基础af09e3f/work/adhoc-0034-agentsmd-parallel；Cuse基础ab43cc4/work/adhoc-0033-ai-coach＋原15修改/23新增source。真实身份、当前输入在inputs/combination-location.json，不能只用分支名当冻结。
- 固定受审/实际差异：manifest.json绑定两候选/inputs/入口所有字节，派发另给SHA。inputs/C34-git-*、Cuse-git-*提供真实Git信息；未跟踪/必要忽略资源已经物理复制。当前落地实际差异在inputs/landing-delta.patch；原coordination-delta.patch与history-baseline-Cuse是历史累计比较，不代表当前before。
- 冻结/核对：C34、Cuse、inputs与根规则/任务/manifest只读，核前后全清单且无外链。当前所有落地before在inputs/before/，逐项严格对应inputs/landing.json；after均指Cuse实际文件。当前唯一落地清单是inputs/landing.json，候选内旧combination-location.json是保留的第一轮证据；现行入口为handoff-v2.md和combination-v2-location.json。
- 并行/角色/写入：无Developer写入，无并行产品活动；你仅可写validation-tests/、validation-evidence/及绑定报告。禁止修改/chmod C34/Cuse/inputs或根文件，不访问原目录/旧临时目录/平台/全局/私有states。
- 资源与公开states：本次无产品安装、数据库、账号、端口、浏览器或业务网络。唯一允许读的states是两固定组合里明确提供的4个公开占位/虚构示例：states/Goal-example.md、states/{activities,health,verification}/.gitkeep；不推断或读取其他states。它们不是私人实例。
- 共享归属/版本：H的唯一修改方为0034，8份更新文件同版，两组7份与官方37520a5132bb5f84064e04f18d7a4467ebdc9116原字节一致，skills索引最小合并，references不变；主独占计划/记忆/组合与本次landing材料，不由Validator修正。
- 材料来源：inputs/upstream、upstream.json固定官方11文件；developer-baseline.json仅为原374文件基线；baseline.json为Cuse179保护项及原工作状态；protected-old-evidence.json为6234旧项，其中6231普通文件已复制、3历史解释器链接只记身份不跟随；baseline-C34为该分支原记录，history-baseline-Cuse为早期比较原件，before是当前实际回写前件。
- 当前就绪：当前版本含H、双组合各自业务记录、全部当前before/明确不存在、实际after及公开依赖，足以开始本轮验证。T03因交接验收尚待本轮复验而保持exec，不代表材料缺失；具体验证输入就绪与任务最终验收分开，未预写复验成功。
- 组合责任/检查范围：主负责冲突、实际原区落地及后续交付；你审完整当前组合及001/002相邻正常/错误回归，不仅看改动两行。C34产品树保持原基准且不导入0033，Cuse保护175source+4references、38差异及旧记录。两业务树不要求相同，H必须相同。
- 输入→输出：当前固定材料→独立场景/结果、问题复现、真实命令/退出/原始证据及未验边界。无权改标准、维护协调记录或宣称已落地。
- 允许修改范围：仅validation-tests/和validation-evidence/；隔离污染/缺失/前置冲突样本只能在这里。可检查受审的landing_guard.py，但绝不能以原工作区为目标执行；只用隔离样本或静态审核。无Git操作、安装/运行产品、Chrome或真实服务。
- 错误边界/停止：SHA或必要依赖不一致、范围/授权歧义、环境/工具故障即停止受影响项报主，不修原件/悄悄改清单/切换执行协议。有效问题沿稳定编号，新增从H34-V2-001起。
- 检查方法/预期：见下；这些是客观输入，须自行设计正常/禁止/边界和有效反例，不复用旧结论凑通过。标准库足够，约20分钟有界收口；不扩审历代产品，不因时间降标准。
- 返回与证据：绑定报告；validation-evidence保留原始失败和校正，不覆盖首错。明确通过/失败/无法判断、实际版本、场景和逐目标guard覆盖、保护/业务保真、未执行的真实落地/主验/Git交付。

## 客观复验线索（不是历史结论输入）

- H34-V1-001对应H34-04/05/07：先前同称“前置字节”的PLAN是6efc8402…，清单prelanding.PLAN是92fe513d…。本轮检查当前before目录每个实际字节是否与当前landing.before一致，历史累计比较与实际落地前件是否明确分离；不要求旧时点历史文件被改写成新值。
- H34-V1-002对应H34-04/05/07：先前目标只有8H、PLAN/MEMORY/0033计划，缺已存在的0034计划及证据的前置保护。本轮须核完整当前install/retain目标集、已有/不存在前提、after和精确差异；不是只补一个requirements示例即算完整。
- 复验正常回归：7文件原字节/许可/技能、最小索引和references、9字段/角色规则、两组合业务记录/暂停/失败保真、相对链接/锚点、目录/资源/共享项隔离与最终组合要求。

## 当前交接的可观察合同

1. landing.entries逐项列当前8H、PLAN/MEMORY、0033/0034计划和所有已存在的0034证据，before来自当前原实际字节；after是实际Cuse。retain绝不回拷，install仅在允许清单内。不存在整目录覆盖。新技能需明确null，已有同名文件/目录应拒绝。
2. 必须在任何install前检查全部前置值/固定来源、原分支HEAD和空暂存及保护清单；不符即停。安装后回读after并再次核原业务保护。不以重算before来迁就并发变动。
3. 后续本轮独立报告/主验收/派发/实际交付收据尚未产生，landing另列追加范围和仅排他新建规则（xb、同名存在即停），不得覆盖已有证据。不能要求预写未知结果，也不能借“证据”扩大改写旧文件。
4. 状态/结果的真实后置补写或归档由主核精确差异；语义或依赖变化仍须重固定/新独立复验，不能将该例外用于改规则。
5. 自行设计反例：缺before、错误before、漏目标/证据、错误after、retain变写入、缺文件前提遇已有对象等；仅在隔离样本测试。结合实际文件/差异与受审landing_guard.py核预期，不要求运行业务/并行调度器。
6. 按要求独立核正常流水线及禁止场景：当前输入齐时可规划；已审/接口齐才开发；冻结实际未提交与依赖后可验证同时独立开发；同目录双Writer/抢测试资源/共享各改一份/只给分支名冻结/以单体通过替代组合验收均拒绝。只暂停受影响链不清零停止线；纯文档不启动浏览器。

仅返回当前证据支持的结果；后续真实落地和Git交付由主亲自完成，未运行不得通过。
