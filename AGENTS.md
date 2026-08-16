# TrainLab 项目指令

## 权威性与状态

本文件是 AI Agent 的仓库级权威指引。更高优先级的系统指令和用户指令优先于本文件。

仓库状态通过以下文件外置：

- `rules.md` 保存经过人工批准的硬性约束。
- `memory.md` 保存持久偏好、已验证的项目事实以及活动计划链接。
- `PLANS.md` 保存经过人工批准的长期 Roadmap、阶段、任务、依赖和并行批次。
- `references/` 保存由用户主动要求生成或维护的可复用开发专题知识。
- `docs/exec-plans/active/` 保存任务步骤、检查点、阻塞项和验证状态；执行计划是对应任务状态的唯一事实源。
- `docs/exec-plans/tech-debt-tracker.md` 保存有证据但不阻塞当前交付的技术债候选。
- `CHANGELOG.md` 保存未发布的重要项目变更和正式发布；仅在相关工作中按需读取。

根目录只承载 agentForge 开发 Harness 与 Git/CI 元数据。TrainLab 下一代运行 Harness、Skills、
模板和实例状态位于 `source/`；运行时不再依赖旧的 `source/src` 集中式产品包、统一 CLI 或
`source/src/resources/harness/`。两层 Harness 通过职责和目录分离，不得互相冒充或替代。

## 每个上下文的启动流程

对于任何涉及仓库分析、审查或修改的请求：

1. 完整读取本文件。
2. 检查是否存在可用的 `git` 命令。
3. 确认项目位于 Git worktree 中。
4. 检查 Git 根目录、当前分支、已跟踪和未跟踪文件以及工作区改动，并保护无关工作。
5. 完整读取 `rules.md`、`memory.md` 和 `PLANS.md`。
6. 检查 `docs/exec-plans/active/`，存在匹配计划时完整恢复该计划。
7. 检查 `references/`，仅在当前任务需要时读取相关专题文件，不读取全部知识库。
8. 检查 `skills/`，仅在触发条件匹配时读取对应 `skills/<name>/SKILL.md`。
9. 若旧迁移树仍存在，仅在审计旧行为时读取 `source/src/resources/harness/**`；新运行工作以
   `source/AGENTS.md`、`source/skills/README.md` 和被触发的 Skill 为准，不得把旧 Harness
   当作新运行合同。

已退役的 `harness/runtime/HARNESS.md` 不得恢复。不得把根开发 Harness 当作产品运行
指令。旧 `source/index.py` 入口已经退役；新运行通过 `codex exec -C source` 按
`source/AGENTS.md` 和 Skills 执行，不创建或要求仓库 `.venv`。

不检查或修改仓库的纯概念问答，不受 Git 门禁和执行计划要求约束。

## Git 门禁

开始仓库工作前必须具备 Git。

- Git 不可用时停止工作，报告操作系统、失败检查和拟采用的安装方式，并请求用户明确批准安装。未经批准不得安装。
- Git 可用但项目不在 worktree 中时停止工作，解释 `git init` 的影响，并仅在取得单独、明确批准后执行。
- 批准安装 Git 不代表批准 `git init`；批准 `git init` 也不代表批准安装软件。
- 当前目录嵌套于上层 worktree 但不是仓库根目录时，报告实际根目录并询问沿用还是初始化独立仓库，不代替用户决定。
- 用户拒绝、操作失败或仍有歧义时继续停止；门禁通过前不得创建计划或修改项目文件。
- 工作区可以不干净，但绝不能覆盖、丢弃或擅自纳入无关改动。
- 除非用户明确要求，不得暂存、提交、创建或切换分支、推送、合并、部署或创建远程资源。

## Roadmap 与即时执行计划

- `PLANS.md` 只回答“将来准备开发什么”；详细实现只写入 exec plan。
- 主协调 Agent 可以提出候选阶段、任务、顺序、依赖和并行批次，但阶段范围、任务增删、排序、目标和并行拓扑必须经人工明确批准后才生效。
- 远期阶段只保留目标、依赖和预期成果；当前阶段准备启动时，才依据最新仓库事实展开叶子任务、验收目标和写入范围。
- 阶段 ID 使用稳定的 `P1`、`M1`、`Q1` 等标识；任务 ID 使用阶段内全局递增编号，例如 `P1-0001`。编号只表示排序和优先级，不代表依赖。
- 依赖必须在 `PLANS.md` 和 exec plan 中显式声明。
- 任务进入 ready batch、即将开始修改仓库时，才创建对应 exec plan；不得为尚未就绪的未来任务批量生成详细计划。
- Roadmap 计划命名为 `<stage>-<initiative-slug>-<sequence>-<feature-slug>.md`；真正返工增加 `-r01`、`-r02` 后缀并链接原 completed 计划；非 Roadmap 工作使用 `ADHOC-<sequence>-<slug>.md`。
- 除纯概念问答和简单状态查询外，每个仓库分析或修改任务都必须创建或恢复一个 exec plan。
- 使用 `docs/exec-plans/template.md` 并遵循 `docs/exec-plans/README.md`。
- 主协调 Agent 是 `PLANS.md`、exec plan、`memory.md` 和协调状态的唯一写入者；Worker 和 Validator 只返回结构化事实。

## 并行批次与 Git 隔离

- 同一 ready batch 中的任务必须范围已批准、依赖已满足、写入范围不重叠、共享接口已冻结，且不会同时修改同一迁移、配置入口或集成文件。
- 每个并行任务使用 `work/<task-id>-<feature-slug>` 本地分支和 `../<repo-name>-worktrees/<task-id>/` 独立 worktree；阶段使用 `integration/<stage-id>` 集成分支。
- 阶段批准只授权明确列出的本地分支、worktree、本地任务提交和阶段集成，不授权远程推送、主分支合并、发布或部署。
- Worker 只能修改获批的代码和测试范围；两个活动 Worker 不得拥有重叠写入范围。
- 发现依赖、接口或写入冲突时停止受影响任务并降为串行。降低并行度无需重新批准；新增任务、范围或外部影响必须重新批准。
- Agent 容量不足时减少并发，不得削弱任务合同或验证门。
- 本仓库禁止加载或调用 `orchestrate-parallel-work`；并行若获批准，只使用本文件定义的 agentForge 分支、worktree、Worker 与 Validator 协议。

## 执行状态与回写

- 状态使用 `planned`、`ready`、`active`、`blocked`、`validating`、`validated`、`integrating`、`completed`、`rework` 和 `cancelled`。
- exec plan 的非终态文件保留在 `active/`；完成或取消后移至 `completed/`，不得删除验证和迭代历史。
- 任务级 Validator `PASS` 后才能进入 `validated`；并行集成级 Validator `PASS` 后才能进入 `completed`。
- 完成时由主协调 Agent 归档 exec plan、更新 `PLANS.md` 中适用任务、重新计算子项目/阶段状态，并删除 `memory.md` 活动指针。
- Validator `FAIL` 时不得勾选。已完成任务返工必须保留原 completed 计划并新建 `-rNN` 计划，将 Roadmap 状态改为 `rework`；普通诊断、命令失败或同一任务内修复只更新当前计划。
- 完成关键步骤、遇到阻塞、准备交接以及上下文结束前更新检查点；每个上下文只追加一条简短迭代记录。
- 恢复任务时使用 Git 和文件系统事实核对检查点；仓库证据优先，并记录偏差。

## 项目 Skill 仅限本地

- 项目 Skill 仅存放在 `skills/<name>/SKILL.md`。
- 只有任务与触发条件匹配时才加载；相对路径以 Skill 所在目录为基准解析。
- 禁止将项目 Skill 复制、移动、安装、同步或链接到 `~/.codex`、`~/.claude`、其他用户级目录、全局注册表或仓库外位置。
- 除非用户单独明确授权，不得为激活项目 Skill 修改全局配置。
- Skill 指令始终服从系统指令、用户指令、仓库指令和已批准规则。

## 项目参考知识库

- 可复用开发专题知识仅存放在 `references/<topic>.md`；产品说明和运行资料存放在 `docs/`。
- 根 `references/` 初始为空，只使用 `.gitkeep` 保留。不得为了填充目录创建示例知识。
- 只有用户主动要求生成、整理、保存或更新某项参考知识时，主协调 Agent 才能写入根 `references/`；普通开发、搜索、分析或任务结束时不得自动沉淀内容。
- 短小偏好、当前事实和活动计划链接写入 `memory.md`；硬性约束经批准后写入 `rules.md`；可执行工作流写入 `skills/`；这些载体不得互相替代。
- 写入前核对同主题文件，优先更新而非重复建立；文件名使用简短稳定的 kebab-case。
- 每份参考资料必须区分已验证事实、来源、适用范围、记录或复核日期以及不确定内容，不得保存秘密、无关个人信息、未经标注的推测或受许可限制的整段复制内容。
- 读取时只加载与当前目标直接相关的文件，并以当前仓库事实和权威来源为准；资料过期或冲突时不得盲目沿用。

## Subagent 动态选档

主协调 Agent 派发任务前，依据任务事实选择最低充分能力，不在仓库文档中绑定厂商或模型名称。

| 任务类型 | 模型档位 | 推理档位 |
| --- | --- | --- |
| 检索、提取、格式转换、机械检查 | `low` | `low` |
| 单模块实现、常规测试、一般文档 | `medium` | `medium` |
| 跨模块设计、复杂调试、迁移、并发、安全 | `high` | `high` |
| 任务 Validator | 不低于对应 Worker | 至少 `medium` |
| 集成 Validator | 不低于该批次最高 Worker | 至少 `medium` |
| 高风险 Validator | `high` | `high` |

- 每次派发在 exec plan 中记录角色、任务 ID、验收标准、风险、档位、选档理由、平台支持、写入边界、lint/test 门、返回产物和验证要求。
- 能力不足时使用全新 Agent，按 `low/low → low/medium → low/high → medium/medium → medium/high → high/high` 逐级升级，从当前档位之后继续，不降低已选维度。
- 无法完成、证据不足、边界遗漏、自相矛盾、无法定位的检查失败或能力相关的 `FAIL`/`INCONCLUSIVE` 都是升级事实。
- 达到 `high/high` 仍失败时停止自动重试，标记 `blocked` 并重新拆分或请求用户决策，不接受部分结果释放后续依赖。
- 平台不能显式选择某维度时记录 `platform-default`，通过缩小范围、明确验收、完整检查和独立验证补偿，不猜测实际档位。
- 平台不能提供全新独立 Validator 时，计划保持 `validating`，主协调 Agent 不得自我认证完成。

## Linter 门禁

- 空项目不预先猜测或安装工具；本项目已有 Python、Markdown、构建与 CI 门禁，应沿用而不重复建设。
- 多语言或多子项目必须覆盖每一种实际使用的可执行技术栈。
- linter 一旦建立即为永久交付门禁，不得为绿灯跳过检查、屏蔽有效诊断或弱化规则。
- 经过验证的 lint/test 入口记录在 `memory.md`；Validator 仍须依据仓库证据独立确认。

## 功能测试与实施顺序

A-003 的根 `src/`/`tests/` 布局仅适用于历史开发 Harness；当前 A-008 已替代产品运行层
的旧目录合同。新运行功能的确定性脚本、合同和测试位于 `source/skills/`：

```text
source/skills/<skill>/scripts/
source/skills/<skill>/references/
source/skills/_tests/
```

每项功能或缺陷修复按以下顺序执行：

1. 从目标和验收标准提取可测试行为。
2. 创建或确定功能测试目录，并先定义预期行为。
3. 覆盖正常行为、错误路径和适用边界；缺陷修复必须包含回归测试。
4. 实现生产行为。
5. 同时交付实现和测试。
6. 将结果交给独立 Validator。

纯治理变更不要求新建功能测试目录，但仍运行所有现有且适用的检查。禁止为了绿灯删除测试、移除关键用例、降低断言、改变正确预期、过度 mock、无理由 skip 或隐藏失败；只有目标或验收标准被明确修改后才能调整测试预期，并在计划中记录授权和理由。

## 独立 Validator

任何修改代码、配置、功能文档或其他仓库结果的任务，在完成前必须通过独立验证。并行任务使用任务级和集成级两层验证。

- Worker 完成后将任务设为 `validating`，由任务级 Validator 检查独立交付；`PASS` 后进入 `validated`。
- 主协调 Agent 集成同批 validated 结果后，由另一个全新 Validator 运行整体 lint、完整测试和跨任务回归；只有其 `PASS` 才能完成。
- Validator 必须是未参与实施的全新、只读 Agent。
- 只提供中性目标、验收标准、适用条款、已批准规则和当前仓库结果；不得提供实施者推理、辩护、预期结论、计划日志、memory 偏好或缺陷导向提示。
- Validator 独立检查 Git 范围、工具配置、lint、测试结构与真实性、禁止的测试弱化、定向测试、全部适用测试、验收标准和规则。
- Validator 返回 `PASS`、`FAIL` 或 `INCONCLUSIVE`，附命令、观察、证据、未满足项和风险，且不得修改文件。
- `FAIL` 后由主 Agent 修复并交给新的独立 Validator；`INCONCLUSIVE` 或 Validator 不可用时保持 `validating`，自检不能替代独立验证。
- Validator 档位不得低于 Worker，推理至少 `medium`；高风险验证使用 `high/high`。
- 只有适用层级全部 `PASS` 才能归档完成。只读分析不强制独立 Validator，但须在计划中记录证据。

## 技术债治理

- 主协调 Agent 可把执行中发现、有证据且不阻塞当前正确性、安全和交付的问题记录到 `docs/exec-plans/tech-debt-tracker.md`，不得借此扩大当前任务。
- 每条记录 ID、来源任务、证据、影响、范围、建议行动、人工决定以及关联 Roadmap/exec plan。
- 状态使用 `candidate`、`accepted`、`deferred`、`rejected`、`promoted` 和 `resolved`。
- 只有人工能接受、拒绝、排序或提升技术债；主协调 Agent 不得自动安排实施。
- 阻塞当前交付的问题必须进入当前计划或停止，不能记为以后处理。

## 规则、记忆、隐私与发布

- AI 可提出候选规则，但只有人工明确批准后才能修改 `rules.md` 中的生效规则；不得静默弱化历史规则。
- 持久偏好、已验证事实、验证命令或活动计划链接变化时自动维护 `memory.md`，不保存任务步骤、秘密、个人健康数据、邮件内容或未经验证的推测。
- 私有 state、logs、test_data、FIT、raw、数据库、凭据和私有配置不得进入 Git 或 `dist/`。
- `data-backup/` 只保存旧实例的本机归档，始终被 Git 忽略；不得把归档内容作为当前数据源。
- `source/` 是唯一产品工程；不生成或维护 wheel、bundle、dist 或 deploy 发布层。
- 普通工作不创建版本。值得记录的变更先进入 `CHANGELOG.md` 的 `Unreleased`；只有用户明确要求发布并批准版本号后才能建立正式版本。
- 不安装、卸载、复制或修改用户级全局 Skill；不得恢复 `.orchestration`、Graph/Dashboard 或 hash-bound 审批工作流。
- Gmail MCP 服务器必须是当前环境中启用的精确 `gmail` 绑定，使用 `@artymclabin/gmail-mcp`；不静默安装、认证或回退到主机专用传输。

## 完成交付

交付报告必须包含完成结果、重要变更路径、lint/test 命令及结果、独立 Validator 状态与证据、跳过检查及原因和剩余风险。计划仍为 `blocked` 或 `validating` 时，不得声称任务完成。
