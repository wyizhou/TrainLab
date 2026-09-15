# TrainLab-next 迁移历史来源快照

2026-09-15：以下是随源码保留的 next 历史记录，不表示主 TrainLab 已升级到其开发脚手架。
主根仍使用 [AGENTS.md](../AGENTS.md) 指定的 Harness；本次只保存 API 重构前的未验证代码
快照，范围见 [ADHOC-0019](exec-plans/completed/ADHOC-0019-adopt-next-before-api.md)。
下文原计划、归档和工作目录链接仅作历史定位，不要求补建这些目录，也不据其恢复旧任务。

---

# 开发脚手架升级说明（来源原文）

本文件记录来源、采用范围与历史恢复位置。现行协作规则见 [AGENTS.md](../AGENTS.md)，本轮检查与交付以 [PLAN.md](../PLAN.md) 关联的 HARNESS-20260911 执行计划为准；产品阶段、失败与暂停恢复见 [M12 执行计划](../exec-plans/active/M12-fit-weekly.md)。

## 2026-09-11 agentsmd 20260911 升级

- 固定来源：[release 20260911](https://github.com/wyizhou/agentsmd/releases/tag/20260911)，commit [1f7deb6c99c117b24251fd7d8eefef81242d21ce](https://github.com/wyizhou/agentsmd/tree/1f7deb6c99c117b24251fd7d8eefef81242d21ce)，tag 对象 `9651ed7a4c40ba60061c038f5b8e733cac4a7713`；[八文件来源摘要](/Volumes/DiskOther/Code/TrainLab-handoffs/agentsmd-20260911-upgrade/upstream.json)与固定上游副本保存在本轮外部证据目录。
- 工作目录 `/Volumes/DiskOther/Code/TrainLab-next`，本轮分支 `codex/agentsmd-20260911`，HEAD `7125a30f8d58e948516d72df39c1d5fb8d21d1d3`。本轮不暂存、提交、推送、PR、合并或触发远端 CI，不改两个旧工作树。
- 根 AGENTS 与 `subagent-templates/planner.md`、`developer.md`、`validator.md` 直接采用固定上游原字节；执行计划模板已相同，保持不动。三角色首次材料按相应模板填写，补充首次/调整规划、正常开发/修复、首次验证/复现/复验的任务入口及异常分流。
- PLAN、MEMORY 保留项目事实与模板结构，由 Main 维护；本轮新建单独治理执行计划。README 保留 TrainLab 说明，CHANGELOG 只追加 Unreleased 事实，两个 MIT 正文与历史 agentForge 声明完整保留，见 [第三方声明](legal/third-party-notices.md)。采用范围不改变 TrainLab 产品整体许可。
- 业务保持暂停。被中断的业务 pytest 61707 已确认退出，不记为通过；恢复位置为 R7-CFG-RUNNER 当前修复的全新独立复验与 Main 验收，之后再处理尚未开始的 Email 与整合。业务原阶段状态、问题编号与累计失败次数保持，本轮不恢复业务或重判历史。
- 保护 `source/` 公开成果、产品合同、CI、依赖、旧完成计划和失败历史；私人数据、配置与凭据不读取或复制。[升级前公开基线](/Volumes/DiskOther/Code/TrainLab-handoffs/agentsmd-20260911-upgrade/before.json)记录 286 文件的摘要与权限，[公开原件](/Volumes/DiskOther/Code/TrainLab-handoffs/agentsmd-20260911-upgrade/before-public.tar.gz)仅供隔离核对和恢复，不覆盖现有成果。
- 本轮只进行本地治理、适用布局/忽略边界及隔离模板演练；检查、独立验证和 Main 最终验收按实际证据记录，不预写通过。模板是任务说明，不能证明自动调度、名额回收或产品运行时已修复，也不替代 Runner 或双平台业务验收。

## 以下为升级前整个迁移文件的历史原文

下方原文件连续、逐字节保留，包括旧标题、“当前/本次”、来源、分支、恢复指令和历史链接；它们只说明当时事实，不作为本轮现行状态、规则或业务恢复授权。现行入口以上方和根 AGENTS 为准。

---

# 开发脚手架迁移说明

本文件只作来源、文件映射与恢复索引。当前总目标和功能总览见 [PLAN.md](../PLAN.md)，详细状态、检查和交付见 [本次治理执行计划](../exec-plans/completed/HARNESS-20260910-1-governance-migration.md)；产品阶段、失败及暂停见 [M12 执行计划](../exec-plans/active/M12-fit-weekly.md)。迁移时业务保持暂停；当前业务开发与检查的恢复状态以 [M12执行计划](../exec-plans/active/M12-fit-weekly.md) 为准。

## 2026-09-10 agentsmd 20260910.1 迁移

- 固定来源：[release 20260910.1](https://github.com/wyizhou/agentsmd/releases/tag/20260910.1)，commit [9622d7753fe6e8daa5fdd2a2f7ee0f111b4aa222](https://github.com/wyizhou/agentsmd/tree/9622d7753fe6e8daa5fdd2a2f7ee0f111b4aa222)。根 AGENTS 与 exec-plans/template 原字节采用；SHA-256 分别为 `736598a4aae3cc7f975a8484bb8080a5eb967e3b74f2b9f7115f94992c378afd`、`17d0d93e3f79e2174bf751a5c8e80acf70aa35807ed8db73050e8faafe842f05`。[固定源校验](/Volumes/DiskOther/Code/TrainLab-handoffs/agentsmd-20260910.1-20260910T135835Z/upstream-manifest.json)保留五文件、release/tag/blob 依据。
- 工作目录 `/Volumes/DiskOther/Code/TrainLab-next`，本次分支 `codex/agentsmd-20260910-1`，基准 `7125a30f8d58e948516d72df39c1d5fb8d21d1d3`；两个旧工作树及历史原件不变。
- 当前只采用根 AGENTS 的开发方式；旧 rules、docs/exec-plans 协议/角色、旧 A-019/A-020/A-024 开发条款及 COL/GATE 旧交付解释仅存证，不重新加载。CLAUDE 只引根 AGENTS，根 skills 隔离说明继续适用；产品代码里的状态和合法 active/completed 目录不作清理对象。

| 原材料 | 当前位置或处理 | 保留边界 |
| --- | --- | --- |
| 迁移前 PLAN 全文 | [原件](/Volumes/DiskOther/Code/TrainLab-handoffs/agentsmd-20260910.1-20260910T135835Z/old-PLAN.md.txt)及[29章节/51问题索引](/Volumes/DiskOther/Code/TrainLab-handoffs/agentsmd-20260910.1-20260910T135835Z/plan-source-index.json) | 原 124546 字节与失败不改写；不作为当前入口。 |
| PLAN 总目标/功能 | 根 PLAN.md | 原模板骨架，只存四个大功能、验收/依赖/状态/链接与整体关注。 |
| M12 各阶段、CFG/FIT 单元及证据 | 一份 active/M12-fit-weekly.md | 原 M12-R0–R7、R6-1–6 和配置 ID 保留；产品暂停，不把局部验收当整体完成。 |
| 已完成原本地治理功能 | completed/MIG-20260909-agentsmd-migration.md；completed/HARNESS-20260910-harness-update.md | 只记原适用本地验收和交接，旧 App 角色不当作本次真正子代理验证。 |
| 原 26 项业务条款、十份 A 全文、尾段与已确认 CFG/FIT 修订 | [现行产品合同](product-contract.md) | 除明确修订外原条款保留；LIVE 模型名称被环境命令要求替代；开发条款映射根 AGENTS。 |
| 原 51 条问题 | M12 exec 的 48 条；MIG exec 的 3 条 | 一个问题只有一个当前累计权威位置；原表/后续报告连续保留。 |
| 问题别名与补充 | M12 exec 问题表 | FIT-TEST-INVENTORY-001 / VAL-RUNNER-003 / M12-R5-TEST-INVENTORY 同链共3事件；Runner default 两方法、私有夹具两次、Goal映射再次发生及原独立FAIL不清零；新增 CFG-RUNNER-STOP-OBSERVATION-001 承接原 process_stop_unconfirmed 节点/批次和未解释04b超时。 |
| 历史 M1–M11、旧 M12 及取消健康/日报/复杂HTML | [.migration-archive](../.migration-archive/)及[原备份](/Volumes/DiskOther/Code/TrainLab-handoffs/agentsmd-20260910.1-20260910T135835Z/before-public-and-evidence.tar.gz) | 原编号/状态/取消及替代依据不变，不排回待办、不伪装 completed。 |
| 稳定决定与经验 | 根 MEMORY.md | 原模板两表，不重复维护任务进度。 |
| README/嵌套产品说明/退役映射 | 原位置必要指针调整 | 229 个 criterion_source 改指产品合同，JSON 其余深值/顺序/格式不变；代码/测试/Schema/Prompt/依赖/CI及其他文档不改。 |

## 本次备份与恢复

外部证据根为 `/Volumes/DiskOther/Code/TrainLab-handoffs/agentsmd-20260910.1-20260910T135835Z`，目录 0700、文件 0600；原公开文件权限另按清单保留。

- [before.json](/Volumes/DiskOther/Code/TrainLab-handoffs/agentsmd-20260910.1-20260910T135835Z/before.json)：迁移前 280 个公开文件/权限、分支、HEAD、索引和 tracked/untracked 状态。
- [完整原件归档](/Volumes/DiskOther/Code/TrainLab-handoffs/agentsmd-20260910.1-20260910T135835Z/before-public-and-evidence.tar.gz)及[成员清单](/Volumes/DiskOther/Code/TrainLab-handoffs/agentsmd-20260910.1-20260910T135835Z/archive-members.json)：39212 个公开与历史证据文件，压缩包 SHA-256 `f766f7c06a3e1f00e32232de2d9f71aff638a5a83655a64c139f99cac92ede70`；不混入正式 Goal/FIT/凭据。
- [备份核验](/Volumes/DiskOther/Code/TrainLab-handoffs/agentsmd-20260910.1-20260910T135835Z/backup-verification.json)、[实际恢复回执](/Volumes/DiskOther/Code/TrainLab-handoffs/agentsmd-20260910.1-20260910T135835Z/restore-rehearsal.json)及[恢复说明](/Volumes/DiskOther/Code/TrainLab-handoffs/agentsmd-20260910.1-20260910T135835Z/RESTORE.md)：在新隔离目录从完整 history.bundle 恢复基准，应用 tracked.diff，再解出公开原件，逐项比对 hash/mode 和全部 Git 状态。不得对现有工作树执行覆盖恢复；本次回滚也先保护迁移后的成果再在隔离副本演练。
- [两个旧树基线](/Volumes/DiskOther/Code/TrainLab-handoffs/agentsmd-20260910.1-20260910T135835Z/old-worktrees-before.json)和 [Git 历史核验](/Volumes/DiskOther/Code/TrainLab-handoffs/agentsmd-20260910.1-20260910T135835Z/history-bundle.json)保留来源；不要执行归档内脚本。

许可范围保持，两个 MIT 正文和历史 agentForge 声明见[第三方声明](legal/third-party-notices.md)。本迁移不表示产品整体重新许可，不发布或部署产品。

## 以下为旧迁移记录的历史原文

下方整个原文件（含原标题、“当前/本次/本轮”、旧 PLAN 职责、分支、禁令和许可来源）逐字保留，仅解释旧时事实；现行入口和授权仅以上方及根 AGENTS 为准。旧引用不会重新加载旧规则，当前细节不回写到历史区。

# 开发脚手架迁移说明

本文件是来源与文件映射索引。当前任务状态仅以 [PLAN.md](../PLAN.md) 为准；不把历史协议、已结束授权或旧裁决重新作为当前指令。

## 2026-09-10 当前脚手架升级

- 当前来源：[agentsmd 发布 20260910](https://github.com/wyizhou/agentsmd/releases/tag/20260910)，固定 commit [5d158ecd6f719f79296f4e892f10e427d67caf6d](https://github.com/wyizhou/agentsmd/tree/5d158ecd6f719f79296f4e892f10e427d67caf6d)；tag 对象 `ef4ed06bbdf19d40f71408efa532dea096f0afcb`。
- 根 `AGENTS.md` 直接采用该提交的原字节，SHA-256 `223fb7a540147b71bf4c1cfb294dd784cd05fca39d7ad81b314472250965cde6`；不追加项目例外。上游 PLAN/MEMORY/README 模板未变，项目 PLAN/MEMORY 继续保留已有内容。
- 当前工作目录 `/Volumes/DiskOther/Code/TrainLab-next`，分支 `codex/m12-completion`，HEAD `7125a30f8d58e948516d72df39c1d5fb8d21d1d3`。以下首次迁移记录中的分支和索引状态仅代表迁移当时。
- 本次公开范围仅 `AGENTS.md`、`PLAN.md`、`MEMORY.md`、`README.md`、`CHANGELOG.md`、`docs/migration.md`、`docs/legal/third-party-notices.md`；Main 独占 PLAN/MEMORY，Developer 修改其余五项。产品、CI、依赖、旧树和历史原件保持原样。
- 临时全任务串行限制已完全撤销；按上游依赖、接口、独立工作目录和资源隔离条件调度，同一工作区仍只允许一个 Developer 写入。首次给齐材料，之后只查询或等待；需要调整时确认旧任务结束，再交全新角色。该规则仅规避回收问题，不证明运行时已修复或历史名额已释放。
- 全部产品工作继续暂停，后续须用户明确恢复。当前只做治理检查，独立验证和 Main 验收以 [PLAN.md](../PLAN.md) 的 H-01–08 实际记录为准；不将治理检查计为 Runner 或其他产品验收。
- 本次固定源文件、差异、升级前原件和保护基线位于 [升级证据目录](../logs/harness/20260910-upgrade/)；Developer 证据位于其中的 `developer/`。产品恢复索引为 `logs/development/r7-configuration/runner-review-repair/PAUSED-HANDOFF.md`，保留暂停快照、未提交成果、未决失败及原累计。本轮不执行产品检查、安装、暂存、提交、推送、PR、合并或真实服务动作。

## 2026-09-09 首次迁移记录（历史原文）

以下至文件末尾保留首次迁移全文；其中“当前”“本次”“本轮”、旧提交 cb1a83a、迁移分支及索引状态均指 2026-09-09 首次迁移当时，不作为本次升级的现行状态或授权。

## 来源与独立性

- 上游：[agentsmd cb1a83a35e0812c37aef7c08db0cf9158939cb31](https://github.com/wyizhou/agentsmd/tree/cb1a83a35e0812c37aef7c08db0cf9158939cb31)。根 AGENTS.md 与其原文字节一致；PLAN/MEMORY 保留模板字段并填入本项目材料。
- 源工作树：`/Users/lucas/.codex/worktrees/76b6/TrainLab`；分支 `work/m12-running-only-planning`；基准 `0710ba3beb7340c7c06d3ccedafef73f0dd66bf5`。
- 新目录：`/Volumes/DiskOther/Code/TrainLab-next`；分支 `codex/agentsmd-migration`；独立 `.git/`。使用 `git clone --no-local --single-branch` 复制完整祖先历史，不复制旧工作树管理目录、私有本地配置或对象链接。
- 远端仍为 `https://github.com/wyizhou/TrainLab.git`；本次只创建本地副本与分支，未授权暂存/提交/推送/PR/合并。旧主目录及 76b6 原目录保留。

## 文件映射

| 原材料 | 新位置或处理 | 保留边界 |
| --- | --- | --- |
| 根 AGENTS.md | 上游固定版本原文 | 原件仅在历史归档；不追加旧执行协议 |
| PLANS.md、活动计划、memory.md 中的进度 | 根 PLAN.md | R0–R7 状态、依赖、暂停、失败与恢复入口完整迁入 |
| rules.md、RUN-VC-001 产品要求 | PLAN.md 的产品要求与已确认约束 | 原编号保留；26 项业务合同逐字迁入；旧协作/状态/交付条款明确由新指引替代 |
| memory.md 中的稳定决定和经验 | 根 MEMORY.md | 不放任务状态或完整历史；通过先移走小写原件再创建大写文件避免大小写冲突 |
| docs/exec-plans 协议、模板、角色、历史、技术债 | 私有压缩归档 public-tree/docs/exec-plans/ | 退出活动入口；历史结论、取消及问题原文不变 |
| source/ 及未提交产品成果 | 原相对路径复制 | 源码、Schema、Prompt、测试、资源及依赖字节/权限不变；仅两份说明文档调整开发指针和旧交付口径 |
| source/AGENTS.md、source/docs/legacy-retirement.md | 原位置窄范围调整 | 保留产品与安全含义、旧入口停用和新入口尚未交付的事实 |
| .github/workflows/ci.yml | 原样保留 | 本地沿用检查，本次不触发远端 CI；未来推送/PR 前检查自动触发和合并条件 |
| CLAUDE.md | 原样保留 | 仅引用新根 AGENTS.md，不加载旧协议 |
| 原交接包和失败证据 | 私有归档 handoff/ | 原字节、权限及索引保留；不把旧辅助脚本自动运行或给 Validator 暗示结论 |

当前主要求不需要加载旧 rules 或历史计划。Skill 中 A-010/A-011 等产品编号继续对应 PLAN 同名条款；COL 与 GATE 的开发方式按 PLAN 映射后生效。原运行 Schema/账本中的历史版本号不因换脚手架改写。

## 归档与恢复

- `.migration-archive/pre-migration.tar.gz`：476 项迁移前公开树文件、完整原交接包和固定上游四文件，共 623 个文件成员；SHA-256 `e911880ac73d8733c3749a22f229e138707523878773053d1c704fb0f40a40e4`。
- `.migration-archive/archive-manifest.json`：压缩包摘要及每个成员的 SHA-256、大小和原权限。
- `.migration-archive/source-before.json`、`main-before.json`：两个旧工作树的提交、分支、索引摘要、未提交清单及公开文件摘要/权限。
- `.migration-archive/tracked-diff.patch`：已跟踪文件差异；未跟踪文件已收入 public-tree，不能仅用补丁恢复。
- `.migration-archive/approved-plan.md`：本次批准原文；`RUN-VC-001-original.md.txt`：原合同存证。
- `.migration-archive/verification/`：本次检查与交接证据，具体完成状态以 PLAN 为准。

归档目录权限 0700，档案及证据文件 0600，并被 Git 忽略。只在核对历史或恢复时显式打开，不能成为产品导入、Schema、AI 输入、CI 或日常启动依赖。需要恢复时先验证压缩包与成员摘要，再只解包到另一个全新隔离目录；不直接覆盖旧树或当前工作区。

本轮只复制 Git 列出的公开 tracked/untracked 文件和已指定交接包。正式 state、FIT/raw、数据库、goal、收件配置、凭据、缓存及 data-backup 均未从旧目录迁入；Git 已跟踪的公开目录占位与配置示例按清单保留。

许可见 [第三方声明](legal/third-party-notices.md)。本次采用 agentsmd 不改变 TrainLab 产品本身的许可。

## 本地交接索引

本次真实检查结果及迁移任务完成状态集中记录在 [PLAN.md](../PLAN.md)；原受审清单、独立报告和 Main 验收证据位于 `.migration-archive/verification/`。归档原件不因结果回写而改变。

macOS 物理目录中只有大写 `MEMORY.md`。本次明确不暂存，所以 Git 索引仍保留历史 `memory.md` 拼写，默认状态可能显示小写路径被修改。未来明确获准 Git 交付时，应显式记录大小写重命名并确认索引只跟踪 `MEMORY.md`；本轮不通过暂存处理此项。

由本地检查新生成的工具缓存仍受原忽略规则管理；它们没有从旧目录复制，也不属于迁移成果或恢复依赖。原有正式实例及私人资料保持在原处。
