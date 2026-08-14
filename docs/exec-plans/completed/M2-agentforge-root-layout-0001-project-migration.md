# 执行计划：将 TrainLab 完整迁移到 agentForge 0.4.2 根项目布局

- 状态：`completed`
- 负责人：主协调 Agent
- Roadmap ID：`M2-0001`
- 阶段/子项目：`M2/root-layout`
- Batch ID：`serial`
- 返工来源：`docs/exec-plans/completed/M1-product-root-0002-source-migration.md`、
  `docs/exec-plans/completed/M1-runtime-root-0003-data-switch.md`
- 开始日期：2026-08-12
- 最后更新：2026-08-12

## 目标与验收标准

- 根 `src/trainlab/` 是唯一产品实现，根 `tests/` 是唯一产品测试根；不存在 `product/`。
- 根 `pyproject.toml` 和 `requirements.lock` 是唯一 Python 项目描述和锁文件。
- 产品运行 Harness、scripts、deploy、design、配置说明和产品文档迁入合适的根目录；
  agentForge 开发 Harness 与产品运行 Harness 继续职责分离。
- CI、质量脚本、构建器、文档命令和路径引用全部以仓库根执行。
- 本地 `state/`、`config/`、`logs/`、`test_data/` 在同一文件系统内迁回根路径，保持
  私有字节、inode/设备、权限和属主；不输出内容。
- 新根 `.venv` 从锁文件重建，旧 `product/.venv` 仅在验证成功后可恢复清理。
- LaunchAgent 的 `TRAINLAB_PROJECT_ROOT` 改为仓库根；工作目录继续使用受限的
  `~/Library/Application Support/TrainLab`，并保持未加载；不触发 Garmin、分析、邮件或其他业务任务。
- wheel、runtime bundle 和 manifest 从根白名单构建，解包扫描不含私有数据、凭据、
  `.orchestration` 或 agentForge 开发状态。
- 完整 pytest、repository quality、Ruff、format-check、mypy、schema/构建门全部通过，
  并取得全新只读独立 Validator `PASS`。

## 范围与非目标

- 允许写入：`product/` 到根目录的完整迁移；根治理文档、规则替代条目、CI、构建器、
  部署路径、本地 LaunchAgent 路径、私有运行目录的原子重命名、虚拟环境重建。
- 禁止写入：产品业务语义、用户健康数据内容、凭据内容、Garmin Provider、Gmail、
  分析/邮件执行、Supervisor 启动、远端 Git、正式发布、全局 Skill。
- 不删除私有数据；任何临时备份或旧环境只做可恢复隔离，验证完成前不永久清除。
- 不恢复 `.orchestration`、Graph/Dashboard、hash-bound handoff 或连续审批版本。

## 适用规则与参考资料

- 已批准规则：A-001、A-002；本任务按用户当前明确要求追加 A-003 替代 A-002 的
  `product/` 路径条款，不弱化其旧控制面禁令。
- 按需读取的 references：无根开发 references；产品 Gmail 资料仅作路径迁移对象。
- 上游依据：agentForge `v0.4.2` 的全部 20 个 Markdown/LICENSE 文档和目录占位文件，
  固定提交 `ccc934ece6b7b64368c08bc3ce431678511ecfa3`。

## 依赖与隔离

- 显式依赖：M1 已完成；ADHOC-0001 已把根治理协议升级到 0.4.2；用户明确纠正布局。
- 共享接口和冻结依据：agentForge `v0.4.2` 根 `src/`、根 `tests/` 合同；当前 Git HEAD
  `96118de49a27fbaea7b6e0b3f528089d0aa07e01`；现有未提交治理更新必须保留。
- 任务分支：不适用——用户未授权创建或切换分支。
- Worktree：不适用——迁移同一项目根与私有目录，不能并行分割。
- 集成分支：不适用。
- 允许写入范围：见“范围与非目标”。
- 禁止写入范围：见“范围与非目标”。

## 功能与测试映射

| 功能 | Feature slug | 测试目录 | 必须满足的行为 |
| --- | --- | --- | --- |
| 根项目布局与导入 | `root-layout` | `tests/root-layout/` 或既有迁移/质量测试 | 根安装、导入、路径解析和唯一源码 |
| 无私有数据构建 | `product-packaging` | `tests/product_packaging/` | 根白名单构建和拒绝私有/开发状态 |
| 本地运行入口 | `local-supervisor` | 既有 `tests/test_local_supervisor.py` 与 macOS 测试 | 根路径静态正确、保持未加载 |

现有测试不机械重排；本次只移动到根 `tests/` 并更新路径合同。新迁移专属测试如有必要
放入 `tests/root-layout/`。

## 工具采用情况

- 可执行技术栈：Python 3.12、setuptools、pytest、Ruff、mypy、LaunchAgent、ZIP/wheel。
- Linter：锁定环境中的 Ruff check/format-check 和既有 mypy 维护目标。
- 测试：迁移定向测试；repository quality；完整 `python -m pytest`；构建后全新临时安装。

## Subagent 派发

| Attempt | Agent 角色/任务 ID | 风险与复杂度 | 模型档位 | 推理档位 | 选档理由 | 平台支持 | 写入边界 | 产物与门禁 | 结果 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 独立 Validator / `M2-0001-validator` | 跨全仓布局、私有运行根和构建边界迁移 | `high` | `high` | 高风险跨模块迁移，需完整只读复验 | 支持；全新独立 Agent | 只读 | 全部验收项报告 | 会话误关闭，未保留终态 |
| 2 | 独立 Validator / `M2-0001-validator-recovery` | 跨全仓布局、私有运行根和构建边界迁移 | `high` | `high` | 新鲜只读复验，替代无终态的首次会话 | 支持；全新独立 Agent | 只读 | 全部验收项报告 | `PASS` |

## 工作分解

| 步骤 | 状态（`pending`、`in_progress`、`blocked`、`done`） | 证据 |
| --- | --- | --- |
| 完整读取 0.4.2 文档并冻结迁移映射 | `done` | 已读取全部 20 个 Markdown/LICENSE 文档与文件树 |
| 审计 product 树、引用、运行进程和私有路径 | `done` | 逐项映射、进程和 LaunchAgent 前置核验通过 |
| 追加 A-003 并迁移跟踪项目树 | `done` | 根 src/tests/pyproject/harness；product 不存在 |
| 原子迁移私有目录、重建环境和更新 LaunchAgent | `done` | 70,195 文件原摘要匹配；根 venv/import/只读运行通过；plist 未加载 |
| 更新 CI、构建器、文档和路径合同 | `done` | CI 根执行；根白名单构建；旧非历史引用归零 |
| 运行完整质量、测试、构建和隐私门 | `done` | full exit 0/[100%]；quality/static/46 targeted/build/install/privacy 全绿 |
| 取得全新只读 Validator PASS | `done` | 46 项聚焦测试、独立构建/隐私扫描、全新安装与全部边界复验通过 |
| 归档计划、完成 Roadmap 并清除 memory 指针 | `done` | 计划归档；M2/M2-0001 completed；memory 活动指针清除 |

## 当前检查点

- 当前 Loop：完成归档
- 最近完成：独立只读 Validator 对根布局、环境、构建、隐私和运行入口给出 `PASS`。
- 当前焦点：无；任务完成。
- 下一动作：无；后续提交需用户单独授权。
- 阻塞项：无。
- 已变更文件：上一轮未提交治理更新；product 跟踪树迁至根；治理、CI、构建、测试和合同路径。
- 待验证项：无。

## 决策与发现

- agentForge 0.4.2 明确说明模板不使用 `product/`，实现位于根 `src/`，测试位于根
  `tests/<feature-slug>/`；上一轮“长期保留 product 的适配”不符合用户当前要求。
- `dist/` 不是模板预设目录，但实际技术栈需要时允许增加；TrainLab 已有经过测试的
  白名单构建需求，因此保留为生成目录。
- 本次是对已完成 M1 布局的真正返工，但以新的 M2 阶段承载最终根布局，保留 M1 历史事实。
- 私有迁移前后原有 70,195 个文件摘要全部一致；state/config/logs/test_data 根目录
  inode、设备、权限和属主一致。`foundation verify` 新建的零字节 WAL 和 SHM 已识别为
  本次验证辅助文件并可恢复地移入同卷回滚目录，最终文件集合恢复精确一致。
- 冻结 `04-mail-agent.md` 因 Gmail 设置资料迁入 `docs/runbooks/` 而发生合法链接变化，
  已同步更新三处公开合同哈希和 interface manifest；相关合同测试通过。
- LaunchAgent 的 `WorkingDirectory` 是独立的受限运行目录，并不是产品源码根；迁移只更新
  `TRAINLAB_PROJECT_ROOT`，继续保留该隔离边界，避免把运行时临时文件写入源码树。
- 唯一完整 pytest 使用根 `.venv/bin/python -m pytest -q`，持久日志和原子 marker 位于
  0700/0600 临时证据目录，明确 exit 0 且到 `[100%]`，未重跑。

## 任务级独立验证

- 中性交接：仅提供目标、验收、适用规则、当前仓库结果和只读边界，不提供实施辩护。
- Validator 身份/上下文：全新只读 Agent `M2-0001-validator-recovery`，未参与实施。
- 模型/推理档位：`high/high`。
- 命令与观察：独立复核 repository quality、维护范围 Ruff/format/mypy、46 项聚焦测试、
  既有完整 pytest 原子终态、临时白名单构建、解包隐私扫描、Python 3.12 全新安装、
  LaunchAgent 路径/权限/未加载状态和私有目录元数据；全部通过。
- 结果：`PASS`
- 未满足项与剩余风险：无阻塞；工作区尚未提交，旧环境和验证辅助文件保留在仓库外的
  可恢复迁移备份目录，等待后续人工清理决定。

## 集成级独立验证

- 集成范围：不适用——单一串行原子迁移。
- 结果：`不适用——无并行集成`

## PLANS 回写清单

- [x] Exec plan 已归档到 `completed/`
- [x] Roadmap 叶子任务已更新为 `[x] completed`
- [x] 子项目和阶段状态已重新计算
- [x] `memory.md` 中的活动计划指针已删除

## 迭代日志

| 日期/上下文 | 已完成事项与证据 | 发现 | 下一动作 |
| --- | --- | --- | --- |
| 2026-08-12 / Loop 1 | Git 门禁和上游 0.4.2 全文档读取完成 | `product/` 适配不符合用户要求 | 审计并迁回根布局 |
| 2026-08-12 / Loop 1 续 | 完成根布局、私有目录、环境、CI、构建、LaunchAgent 路径和全部自检 | 原始私有文件均未变化；冻结文档链接需显式合同修订 | 独立只读验证 |
| 2026-08-12 / Loop 2 | 新鲜独立 Validator 返回 `PASS`；完成 Roadmap、计划归档与 memory 回写 | 无阻塞项 | 等待用户决定是否提交 |
