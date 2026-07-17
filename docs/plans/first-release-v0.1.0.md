# TrainLab 首个正式版本 v0.1.0 发布计划

- 状态：实现与本地完整门禁已完成，等待最终独立 Validator 和 PR 检查
- 产品版本：`v0.1.0`
- 组件基线：前端 design v3.4 / design_rev 7；后端 v0.3 / 迁移 `0003_activity_data_lifecycle`
- 工作方式：共享基础串行冻结，三个隔离单元并行实现和独立验收，最后由集成负责人统一收口

## 1. 发布目标

将当前已经通过独立验收的前端 v3.4 与后端 v0.3 组合为 TrainLab 首个可重复安装、可本机运维、可备份恢复的正式产品版本。`v0.1.0` 是产品发布版本；现有前端设计版本和后端组件版本继续保留各自含义，不互相替换。

本里程碑涉及认证凭据、全会话撤销、私有 FIT 原文件和破坏性恢复，按大型/高风险任务执行。所有破坏性演练必须使用与现有开发数据完全隔离的 Compose project、数据库和命名卷，禁止读取、修改或猜测当前实际 owner 密码，禁止修改实际 owner 的密码或会话。

## 2. 范围与非范围

### 本次范围

- 本机 HTTP 上的登录、会话恢复与退出。
- 登录用户的本地 FIT 上传、持久化活动列表、通用详情、原文件下载和现有用户数据生命周期 API。
- 运维 CLI 重置指定用户密码，并在同一事务中撤销该用户全部会话。
- 运维 CLI 幂等撤销指定用户全部会话而不改变密码。
- PostgreSQL 与 `trainlab-private-files` 私有卷在同一停写点的可执行备份、校验和破坏性恢复流程。
- 私有存储 readiness、仅回环地址暴露、重复启动不重复创建 owner 或业务数据。
- 前端开发工具链的最小兼容安全升级，使 high/critical npm 审计结果归零且不改变业务或视觉实现。
- 可重复运行的发布门禁、发布说明、安装与本机运维手册。

### 本次非范围

- Garmin Connect、TCX、GPX、真实 AI、外部同步、后台队列、Redis 或微服务。
- 新的活动生命周期 UI、浏览器忘记密码 UI、会话管理 UI 或任何未经外部设计输入确认的新界面。
- 修改 v3.4 外部设计、视觉基线、页面结构、业务文案或响应式契约。
- 公网部署、TLS 终止、高可用、在线不停写备份或跨主机灾备。
- HTTP 密码重置端点、公开注册、邮件或短信找回密码。
- 使用 Alembic downgrade 作为含用户数据版本的回滚方案。

## 3. 冻结的共享契约与安全边界

### 3.1 版本与兼容

- 产品发布号固定为 `v0.1.0`。
- `backend` 包和 OpenAPI 的组件版本继续为 `0.3.0`；设计与实现基线继续为 v3.4 / revision 7。
- 数据库迁移头继续为 `0003_activity_data_lifecycle`；本里程碑不新增迁移。
- 现有 API、视觉锚点、240 项前端单测和 FIT 全栈旅程必须保持兼容。

### 3.2 认证与密码运维

- 用户名和密码规则沿用现状：去除用户名首尾空白后长度必须大于 6，密码长度必须大于 6。
- 密码继续使用现有 `pwdlib` 推荐的 Argon2 哈希；CLI 不建立第二套密码规则或哈希实现。
- `reset-password --username <name>` 默认通过隐藏交互输入读取两次密码；自动化仅通过 `--password-env <ENV_VAR>` 读取。
- 密码哈希更新与该用户全部会话撤销在一个数据库事务中提交；任一步骤失败必须整体回滚。
- `revoke-sessions --username <name>` 不改变密码，多次执行均成功且结果一致。
- CLI 退出语义沿用并冻结为：成功 `0`、输入错误 `2`、用户不存在 `3`、数据库或存储失败 `4`。
- CLI 的标准输出、标准错误、异常和日志不得包含密码、环境变量值、Cookie、session token、CSRF token 或密码哈希。
- 现有登录限流是进程内状态；密码重置不扩张为新的限流架构。本机运维手册必须说明必要时重启 backend 可安全清除旧的失败窗口。
- 不增加 HTTP 重置/撤销端点，也不增加前端入口。

### 3.3 本机服务与 readiness

- 正式 Compose 端口仅绑定 `127.0.0.1:8000:8000`。这是本机 HTTP 边界，不表示具备公网或 TLS 安全性。
- `/healthz` 继续只表示进程存活；`/readyz` 必须同时验证数据库连接、迁移头以及私有存储根可访问、可写。
- 存储写探针使用安全随机临时文件并在成功或失败路径清理；不得遗留永久探针文件，不得在响应或日志暴露真实存储路径。
- 私有存储不可用、只读或配置越界时服务不得 ready。

### 3.4 双卷备份与恢复

- 完整备份由同一停写点的 PostgreSQL dump 和私有 FIT 卷归档组成；执行备份前必须停止 backend 写入。
- 每个备份目录包含 manifest，至少记录产品版本、迁移头、UTC 时间、相对文件名、字节数和 SHA-256。
- manifest 不得包含数据库密码、Cookie/token、本机私有绝对路径、账号密码或健康/GPS/设备数据摘要。
- 备份工具必须收紧新建备份目录和制品权限，不能依赖调用者的宽松默认 umask 暴露私有数据。
- 恢复前必须先验证 manifest 结构、允许的相对文件名、大小和 SHA-256；任何不一致都在写入目标前失败。
- 破坏性恢复必须要求显式确认；恢复目标必须是受控 Compose project，归档提取不得目录穿越或跟随不安全链接。
- 恢复后执行迁移升级并撤销数据库内全部既有登录会话，然后再开放 backend。
- 发布回滚使用发布前取得的同停写点双卷备份恢复；Alembic downgrade 只用于隔离迁移测试，不作为含数据回滚方法。

### 3.5 隐私与隔离演练

- 测试只使用仓库内合成/脱敏 fixture 和隔离账号，不提交外部 FIT 样本、GPS、健康数据、设备序列号、原始文件或本机绝对路径。
- 双卷全毁恢复、密码重置、会话撤销和重复启动只能在本轮独立 Compose project 和命名卷中验证。
- 实际 owner 密码未知且数据库仅保存哈希；任何示例密码都只属于隔离测试账号。

## 4. 依赖图、集成顺序与工作区纪律

```text
最新 main
  └─ F0 发布计划与公共契约（串行提交）
       ├─ U1 认证运维 CLI ──────────┐
       ├─ U2 双卷备份恢复/本机边界 ─┼─ I0 顺序集成与发布收口 → 最终 Validator → PR
       └─ U3 前端开发工具安全升级 ──┘
```

- 集成负责人独占集成分支和集成 worktree。
- U1、U2、U3 全部从同一个已提交 F0 SHA 创建独立分支、独立 worktree；一个 worktree 同时只有一个写入者。
- 每个单元只修改本计划分配的文件。需要越界或改变冻结契约时，该单元立即停止并报告，不私下修改共享文件。
- 每个实现单元交回提交 SHA、修改文件、测试命令、测试结果和剩余风险；随后由不同的只读 Validator 复核。
- 只有 Validator PASS 的单元才按 U1 → U2 → U3 顺序合入集成分支，每次合入后立即运行相关回归。
- README、backend README、共享 runbook、项目状态、backlog、发布说明、聚合 CI 与最终发布测试仅由 I0 集成负责人修改。

## 5. 交付单元

### F0 — 发布范围与共享契约

- 唯一产物：本计划。
- 不提前把 `docs/project-state.json`、`docs/backlog.md` 或发布状态标记为完成。
- 完成定义：范围、非范围、版本裁定、文件所有权、依赖、验收矩阵、阻断条件、隐私边界和回滚方式均已冻结并提交。

### U1 — 认证运维 CLI

允许修改：

- `backend/src/trainlab/cli.py`
- 可新增 `backend/src/trainlab/services/user_admin.py`
- `backend/tests/integration/test_cli.py`
- 确有必要的认证集成测试

禁止修改：前端、Compose、迁移、共享/发布文档、HTTP 路由。

验收场景：成功重置、未知用户、短密码、缺失环境变量、交互确认不一致、事务提交/撤销失败整体回滚、输出无 secret；旧密码失败且新密码成功；重置前创建的两个 Cookie 均为 401；单独撤销全部旧 Cookie；重复撤销幂等；其他用户密码和会话不受影响。

### U2 — 双卷备份恢复与本机安全边界

允许修改：

- `compose.yaml`
- `backend/scripts/` 下新增备份、恢复和隔离演练工具
- `backend/src/trainlab/api/routes/health.py`
- 确有必要的 `backend/src/trainlab/core/config.py`
- 对应脚本、health 和配置测试

禁止修改：认证 CLI、前端业务、迁移、共享发布状态文档。

验收场景：loopback 端口；数据库正常但存储缺失/只读时不 ready；探针无残留；备份先停 backend；manifest 最小且无 secret；损坏 manifest、大小、checksum、路径或归档在写入前拒绝；无显式确认拒绝恢复；恢复后撤销 sessions；隔离环境中完成“上传 fixture → 备份 → 全毁 → 恢复 → ready/login/list/detail/storage/download”，下载 SHA-256 与上传原文件一致；再次 `up --build` 和重复 `create-owner` 不重复数据。

### U3 — 前端开发工具安全升级

允许修改：

- `frontend/package.json`
- `frontend/package-lock.json`
- 仅在兼容性确有需要时修改 Vite/Vitest 配置或增加工具链兼容性测试

禁止修改：`frontend/src/` 业务与视觉代码、视觉基线、共享发布文档。

当前审计基线为 5 项依赖告警：1 critical、1 high、3 moderate，涉及 Vitest、Vite、esbuild 及其链路。使用官方发布信息和安全公告选择最小兼容升级，不为了追最新版本做无关大版本迁移。

只读规划阶段识别到的最小候选是 Vite 6.4.3 与 Vitest 3.2.6；候选版本不是通过结论，仍必须以官方兼容信息、新 lockfile 的实际依赖树和全部验收命令证明。

验收场景：`npm audit` 的 high/critical 均为 0；若仍有 moderate，返回精确依赖链、仅开发期/运行时属性和缓解说明；typecheck、lint、240 项单测和 build 通过；业务源码、DOM、CSS、截图和视觉基线零改动。

### I0 — 集成、文档与发布收口

由集成负责人串行完成：

1. 顺序合入三个已验收单元并在每次合入后运行相关回归。
2. 更新根 `README.md`、`backend/README.md`、相关 `docs/runbooks/`、`docs/project-state.json`、`docs/backlog.md`，新增 `docs/releases/v0.1.0.md`。
3. 记录安装、首次 owner、密码恢复、会话撤销、备份、恢复、回滚、仅本机边界、范围/非范围和依赖审计结论。
4. 需要时更新 `.github/workflows/ci.yml` 和 fullstack 发布测试，使 release commit 可重复验证本计划关键旅程。
5. 在最终提交上运行完整门禁与隔离恢复演练，修复独立最终 Validator 发现的问题。
6. 推送集成分支并创建指向 `main` 的 ready-for-review PR；本任务不合并 PR、不创建 tag 或 GitHub Release。

## 6. 验收矩阵

| 领域 | 必须证据 | 失败处理 |
| --- | --- | --- |
| 版本 | 产品 v0.1.0、后端 v0.3、设计 v3.4 和迁移头含义一致 | 任一互相覆盖或文档冲突则阻断 |
| 认证运维 | 密码规则、Argon2、事务回滚、旧会话 401、幂等撤销、无 secret | 任一泄漏、部分提交或会话残留则阻断 |
| 服务边界 | 仅 `127.0.0.1:8000`；存储不可写时 `/readyz` 503；无探针残留 | 对外暴露或错误 ready 则阻断 |
| 备份 | 同停写点数据库与私有卷、manifest 尺寸和 SHA-256 可验证 | 单卷备份、在线不一致快照或 manifest 泄密则阻断 |
| 恢复 | 校验先于写入、显式确认、会话撤销、全毁后 FIT 闭环恢复 | 无法恢复、checksum 不同、旧会话可用则阻断 |
| 重复启动 | 卷保留，重建后 ready；重复 owner 初始化和业务数据不重复 | 数据丢失或重复则阻断 |
| 前端安全 | npm high/critical 为 0；工具链门禁和 240 单测通过 | high/critical 或 UI/视觉改动则阻断 |
| 后端质量 | format、lint、mypy、pytest、覆盖率、空库迁移与 Compose 通过 | 任何适用门禁失败则阻断 |
| 前端质量 | typecheck、lint、unit、完整 e2e、视觉回归、build 通过 | 任何适用门禁失败则阻断 |
| 供应链 | npm 与可信 Python 审计命令、工具版本和结论有记录 | 未缓解运行时 high/critical 则阻断 |
| 隐私 | 测试/日志/manifest/提交无真实凭据、绝对私有路径或健康数据 | 任何敏感数据进入产物则阻断 |
| 发布 | 最终 Validator PASS；PR checks 全部通过 | 未通过时不得合并、tag 或发布 |

## 7. 最终门禁与发布阻断条件

最终 release commit 至少执行：

```bash
backend/scripts/check.sh
backend/scripts/compose.sh --profile test run --build --rm backend-test
npm --prefix frontend run typecheck
npm --prefix frontend run lint
npm --prefix frontend run test
npm --prefix frontend run e2e:ci
npm --prefix frontend run e2e:visual
npm --prefix frontend run build
npm --prefix frontend audit
```

此外必须在唯一的隔离 Compose project 中验证：空库迁移、真实 FIT 上传/刷新/详情/下载、密码重置、全会话撤销、backend 重建后持久化、双卷备份/全毁/恢复和恢复后旧会话失效。Python 依赖使用可信审计工具并记录工具版本、精确命令与结果；GitHub Dependabot 当前未启用，不得表述为“GitHub 告警已清零”。

以下任一情况阻断 PR 进入最终合并/发布：

- 范围内旅程、独立 Validator 或任一适用门禁失败。
- npm 或 Python 运行时依赖存在未缓解的 high/critical 漏洞。
- 认证重置出现部分提交、旧会话仍有效或 secret 泄漏。
- 备份不能证明双卷同停写点，恢复未经校验或无需显式确认即可覆盖数据。
- 恢复后数据、原文件 SHA-256、所有权、登录或下载不一致。
- Compose 暴露到非回环接口，或私有存储不可写时仍报告 ready。
- 改动实际 owner、真实卷、外部设计、业务 UI 或本计划非范围内容。
- 发布文档声称尚未取得的审计、CI、PR、tag 或 GitHub Release 结果。

## 8. 交付与清理

- 全部实现和最终验收完成后，提交并推送集成分支，创建 ready-for-review PR 指向 `main`。
- 本执行任务停在 PR 和远程检查证据，不合并 PR、不打 `v0.1.0` tag、不创建 GitHub Release。
- 只清理本里程碑创建、已经合入集成分支且不再需要的临时 worktree 与本地分支；不触碰其他 worktree、未合并分支或来源不明对象。
- 产品发布是否完成只在 PR 合并、最终独立验收、tag 和 Release 由主协调任务完成后更新；本计划当前状态不冒充该结果。

## 9. 执行证据

- F0 计划提交为 `c4ccfa6`；U1、U2、U3 分别由隔离 worktree 实现、独立复核并按顺序集成，集成提交为 `29c105d`、`f6d95f1`、`befd9cd`。
- 后端空库迁移与 135 项 pytest 通过，覆盖率 89.79%；Ruff format/check、mypy 和 13 项备份安全测试通过。
- 最终审计发现并修复“并发登录验证旧密码后晚于管理命令插入 session”的竞态；登录和管理命令现在使用同一用户行锁形成顺序，2 项无 `sleep` 的 PostgreSQL 双事务测试及独立修复 Validator 均通过。
- Python 运行时锁定依赖经 `pip-audit 2.10.1` 检查，未发现已知漏洞；npm 全依赖与生产依赖审计均为 0。
- 前端 typecheck、lint、43 文件/240 项单测和 build 通过；184 项完整 e2e、126 项 Linux CI e2e、117 项 macOS 视觉回归通过。
- 隔离 Compose 的 3 项真实全栈旅程、密码重置/会话撤销、重建持久化和 FIT 双卷全毁恢复演练通过；真实默认项目、实际 owner 和外部设计均未改动。
- 本记录只证明发布候选本地门禁；最终独立 Validator、PR checks、`main` 合并、tag 和 GitHub Release 必须以各自后续证据为准。
