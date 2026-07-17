# 后端 v0.3：用户数据生命周期实施计划

- 状态：已完成并通过验收
- 基线：后端 v0.2 / 迁移 `0002_activity_import`
- 执行负责人：Backend Dev（集成负责人）
- 工作方式：公共基础串行，三个功能单元并行，最后统一集成验收

## 1. 目标

让登录用户能够管理自己已经上传的运动数据，而不只是上传和查看：可重命名活动、查看所有导入记录及状态、安全删除活动或失败导入、查看私有原文件占用并受到明确配额保护。

本里程碑包含真实数据删除、数据库迁移和并发容量约束，按大型/高风险任务执行。所有对象继续按 `user_id` 隔离；跨用户访问不得泄露对象存在性；文件系统错误、数据库错误和日志不得暴露私有路径。

## 2. 范围与非范围

### 本次范围

- 用户活动显示名覆盖与恢复原始解析标题。
- 用户归属的导入记录游标列表、状态、失败原因、安全重试提示。
- 按活动或导入记录删除数据库派生数据和私有原文件。
- 删除中断后的可恢复状态，以及相同内容删除完成后的重新上传。
- 当前用户原文件用量、文件数、上限与剩余额度。
- 并发上传下的数据库级配额串行化。
- Alembic 迁移、OpenAPI、后端测试、Compose 配置和备份/隐私说明。

### 本次非范围

- 不实现批量删除、自动过期、回收站、历史版本或云端备份服务。
- 不接入 Garmin Connect、TCX、GPX、AI、队列、Redis 或后台任务系统。
- 不改变登录规则、会话机制、现有 FIT 解析结果或通用运动详情结构。
- 不实现可见前端按钮、弹窗或设置页面。UI 必须在后续任务取得用户当次提供的外部设计输入后单独规划；本次只冻结后端 API。
- 删除只影响在线主存储；已经生成的离线备份按备份保留策略处理，运行手册必须明确这一点。

## 3. 冻结的产品与 API 契约

### 3.1 活动重命名

- `PATCH /api/v1/activities/{activityId}`，需要有效会话与 CSRF。
- 请求：`{"name": "用户名称"}`；`name` 为 `null` 时清除覆盖并恢复解析标题。
- 非空名称先去除首尾空白，长度为 1–255，不允许控制字符；空字符串返回稳定的 `422 invalid_activity_name`。
- 返回更新后的 `ActivityListItem`。列表、详情和后续下载上下文使用相同有效名称。
- 数据库存储解析标题与用户覆盖标题两份事实。覆盖标题放在 `activity_imports.title_override`，因此解析重放、活动派生表重建或解析失败都不得丢失用户命名。
- 不属于当前用户或不存在的活动统一返回 `404 not_found`。

### 3.2 导入记录

- `GET /api/v1/imports?limit=&cursor=`，需要有效会话，按 `created_at DESC, id DESC` 稳定分页。
- 每项至少返回：`importId`、可空 `activityId`、`source`、`originalFileName`、`sizeBytes`、`status`、`createdAt`、`updatedAt`、`attemptCount`、`lastAttemptAt`、`completedAt`、`warningCount`、安全的 `errorCode/errorMessage`、`retryAvailable`、`deleteRetryAvailable`。
- 对外状态集合固定为：`pending`、`processing`、`complete`、`partial`、`failed`、`deleting`、`delete_failed`。
- 现有 `POST /api/v1/imports/{importId}/retry` 保持兼容；`deleting` 和 `delete_failed` 不可解析重试。

### 3.3 安全删除

- `DELETE /api/v1/activities/{activityId}` 删除该活动对应的整条导入及私有原文件。
- `DELETE /api/v1/imports/{importId}` 可删除有无活动结果的导入记录。
- 删除成功返回 `204`。不存在或不属于当前用户也返回 `204`，使 DELETE 幂等且不泄露对象存在性。
- 新鲜 `processing` 记录返回 `409 import_in_progress`；陈旧 `processing` 可进入删除。
- 删除顺序固定为：锁定所有者记录 → 提交 `deleting` → 幂等删除原文件 → 硬删除导入行并由外键级联派生数据。
- 文件删除失败时保留记录并写为 `delete_failed`，返回 `503 delete_incomplete`；重复 DELETE 从 `deleting` 或 `delete_failed` 继续，不要求人工改库。
- 原文件已经不存在时视为文件阶段完成，继续删除数据库记录。
- 文件删除成功但数据库提交失败时保留可恢复状态；重复 DELETE 再次执行幂等文件删除并完成数据库清理。
- 删除完成后，相同 SHA-256 再上传必须建立新的导入和活动；删除中的同 SHA-256 上传返回稳定冲突，不得复活旧活动。
- 所有删除路径先锁定当前用户行，再锁定导入行，并清除该导入的解析 attempt token；上传、删除始终遵守“用户行 → 导入行”的锁序。
- 解析开始时生成不可猜测的 attempt token。解析完成或失败后必须重新锁定导入行，并同时验证 `status=processing` 与 token 未变化才可写入终态或派生数据；删除或新 attempt 已取得所有权时，旧解析结果必须放弃，不能覆盖 `deleting` 或复活活动。

### 3.4 容量与配额

- `GET /api/v1/storage/usage`，需要有效会话，返回 `usedBytes`、`fileCount`、`maxBytes`、`maxFiles`、`remainingBytes`、`remainingFiles`。
- 默认每用户原文件上限为 5 GiB、10,000 个文件，可分别由 `TRAINLAB_USER_STORAGE_MAX_BYTES` 和 `TRAINLAB_USER_STORAGE_MAX_FILES` 配置，且必须为正整数。
- 无 DB 引用文件的清理宽限期默认 60 分钟，可由正整数 `TRAINLAB_STORAGE_STAGING_GRACE_MINUTES` 配置。
- 用量统计所有尚未完成硬删除的 `activity_imports`，包括解析失败、`deleting` 和 `delete_failed`；它们的原文件仍可能占用容量。
- 新上传先在数据库事务中锁定当前用户行，再完成流式暂存和 SHA-256，随后处理同用户重复 SHA、计算用量并登记新导入。所有上传路径必须遵守相同锁序，防止并发越限和死锁。
- 上传取得用户行锁后，先清理该用户无 DB 引用的上次崩溃残留，再写入用户隔离的临时命名空间；单个用户同一时刻只允许一个登记流程。暂存完成后处理重复 SHA 和配额，再将文件原子提升到最终生成路径并提交导入行。数据库提交或文件提升正常失败时立即回滚并清理两侧。
- 重复上传只复用已有记录，不增加用量；超过字节或文件数任一上限时删除本次暂存文件并返回 `409 storage_quota_exceeded`，附带不敏感的当前用量和上限。
- 单文件 50 MB 限制保持不变，并继续优先返回原有 `413 fit_file_too_large`。
- 暂存缓冲不计入已登记用量，但因用户行锁、上传前残留清理和单文件上限，每用户最多只保留一个 50 MB 的短期缓冲。进程在文件写入/提升后、数据库提交前崩溃时，后续上传在重新取得用户行锁后立即清理无 DB 引用的暂存或最终文件；运维 CLI 还必须提供带宽限期的只读审计和显式清理模式，不能让没有后续上传的孤儿文件永久脱离配额。

## 4. 公共数据与恢复模型

迁移 `0003_activity_data_lifecycle` 在 `activity_imports` 增加：

- `title_override VARCHAR(255) NULL`
- `delete_requested_at TIMESTAMPTZ NULL`
- `last_delete_attempt_at TIMESTAMPTZ NULL`
- `delete_attempt_count INTEGER NOT NULL DEFAULT 0`
- `delete_error_code VARCHAR(80) NULL`
- `processing_token UUID NULL`
- 支持用户、状态与创建时间查询的索引

不引入数据库 enum，状态仍由应用层常量和测试约束，避免本里程碑增加 enum 迁移复杂度。降级迁移只移除本次字段和索引，不删除原有活动数据。

公共基础还需集中定义：可见状态、解析可重试状态、删除可恢复状态、解析 attempt fencing 和有效标题投影。现有活动列表、详情、下载、解析终态写入和重复上传必须改用这些公共定义，三个并行单元不得各自复制状态集合。

## 5. 依赖图与执行波次

```text
最新 main
  └─ F0 公共基础（串行、先验收）
       ├─ U1 活动重命名 ─────┐
       ├─ U2 导入管理与删除 ─┼─ I0 集成收口与最终 Validator → PR → main
       └─ U3 容量与配额 ─────┘
```

Backend Dev 先从最新 `main` 创建集成分支 `codex/backend-v0-3-data-lifecycle`。每个下列交付单元都必须创建独立分支、独立 worktree，并交给一个独立子 Agent；实际 worktree 根路径由 Backend Dev 在运行时选择，不写入仓库。

F0 合入集成分支并通过验收后，记录准确基础提交 SHA。U1、U2、U3 必须全部从该 SHA 创建，可以同时开发。任何单元发现需要改动其禁止文件或公共契约时停止并报告，不私下跨界修改。

每个实现子 Agent 交回时必须提供提交 SHA、实际修改文件、已运行命令和未解决风险。Backend Dev 在释放相应并发槽后，为 F0、U1、U2、U3 分别安排只读 Validator；单元未通过复核不得合入集成分支。

## 6. 交付单元

### F0 — 公共生命周期基础（串行）

- 分支：`codex/backend-v0-3-foundation`
- worktree 标签：`backend-v0-3-foundation`
- 结果：迁移、模型、状态常量、有效标题投影和三个空路由/Schema/Service 骨架可供并行单元使用。
- 允许修改：
  - `backend/migrations/versions/0003_activity_data_lifecycle.py`
  - `backend/src/trainlab/db/models/activity.py`
  - `backend/src/trainlab/services/activity_states.py`
  - `backend/src/trainlab/services/activity_projection.py`
  - `backend/src/trainlab/services/activity_import.py`
  - `backend/src/trainlab/api/routes/activities.py`
  - `backend/src/trainlab/api/router.py`
  - 新建 `activity_metadata`、`import_management`、`storage_usage` 的 route/schema/service 空骨架
  - 对应基础、迁移和回归测试
- 必须完成：现有投影读取 `title_override`；现有上传/解析重试明确拒绝删除状态；路由骨架由公共 router 注册；迁移升级、降级、再升级通过。
- 必须完成：每次解析生成并持久化 `processing_token`；成功、部分成功和失败终态都以“行锁 + 状态 + token”比较后写入；被删除或新 attempt 取代的解析不得保存派生数据或覆盖状态。
- 禁止实现：不在 F0 增加三个新功能的最终端点逻辑，不修改前端或动态项目文档。
- 验收：`backend/scripts/check.sh`、隔离数据库迁移测试、现有 FIT 导入集成测试、attempt token/CAS 故障注入和 OpenAPI 回归。

### U1 — 活动重命名

- 前置：已验收 F0 提交。
- 分支：`codex/backend-v0-3-activity-rename`
- worktree 标签：`backend-v0-3-activity-rename`
- 唯一文件所有权：
  - `backend/src/trainlab/api/routes/activity_metadata.py`
  - `backend/src/trainlab/schemas/activity_metadata.py`
  - `backend/src/trainlab/services/activity_metadata.py`
  - 新建的重命名单元测试、集成测试和独立 OpenAPI 契约测试
- 禁止修改：迁移、模型、公共 router、原有 `activities.py`、`activity_import.py`、其他单元文件、前端和根动态文档。
- 验收场景：改名、清除改名、空白/超长/控制字符、未登录/无 CSRF、跨用户 404、列表与详情一致、解析重放成功或失败后仍保留覆盖名、并发更新最后一次已提交写入生效。
- 完成定义：单元测试通过，提交只含允许文件，API 契约与本计划一致。

### U2 — 导入记录与可恢复删除

- 前置：已验收 F0 提交。
- 分支：`codex/backend-v0-3-import-management`
- worktree 标签：`backend-v0-3-import-management`
- 唯一文件所有权：
  - `backend/src/trainlab/api/routes/import_management.py`
  - `backend/src/trainlab/schemas/import_management.py`
  - `backend/src/trainlab/services/import_management.py`
  - 新建的导入管理/删除单元测试、集成测试和独立 OpenAPI 契约测试
- 禁止修改：迁移、模型、公共 router、原有 `activities.py`、`activity_import.py`、`activity_storage.py`、其他单元文件、前端和根动态文档。
- 验收场景：导入列表稳定分页和全部状态；活动删除级联；无活动的失败导入删除；文件缺失；文件删除失败进入 `delete_failed`；重复 DELETE 恢复；数据库最终提交失败后恢复；新鲜/陈旧 processing；运行中的解析跨过陈旧阈值后与 DELETE 竞争时旧 token 被 fence、不得覆盖删除意图；删除中重复上传冲突；删除完成后同文件重新上传；未登录、CSRF 和跨用户不泄露；日志/错误无私有路径。
- 完成定义：任何失败点都不会让活动继续可见却无法恢复，也不会先删数据库而遗留不可定位的私有文件；单元测试通过且提交边界干净。

### U3 — 容量统计与并发配额

- 前置：已验收 F0 提交。
- 分支：`codex/backend-v0-3-storage-quota`
- worktree 标签：`backend-v0-3-storage-quota`
- 唯一文件所有权：
  - `backend/src/trainlab/api/routes/storage_usage.py`
  - `backend/src/trainlab/schemas/storage_usage.py`
  - `backend/src/trainlab/services/storage_usage.py`
  - `backend/src/trainlab/services/activity_import.py`
  - `backend/src/trainlab/services/activity_storage.py`
  - `backend/src/trainlab/core/config.py`
  - `backend/src/trainlab/cli.py`
  - `backend/.env.example`
  - `compose.yaml`
  - 新建的容量/配额单元测试、集成测试和独立 OpenAPI 契约测试
- 禁止修改：迁移、模型、公共 router、原有 `activities.py`、其他单元文件、前端和根动态文档。
- 验收场景：空用量、失败/删除失败记录计入、成功删除后释放、重复上传不增加、字节与文件数分别超限、超限暂存文件清理、两个并发上传只能在合计不超限时同时成功、进程在暂存后或提升后崩溃留下的无 DB 文件会被同用户下一次上传立即清理且可由 CLI 在宽限期后清理、合法在途文件不被 CLI 清理、配置非法时启动失败、跨用户用量隔离、数据库/日志不泄露路径。
- 完成定义：用量计算、暂存和登记新导入遵守同一用户行锁序；不存在“各自检查都通过、合计超限”的竞态；`trainlab reconcile-storage` 默认 dry-run，只有显式 `--apply` 才清理满足宽限期且无 DB 引用的生成文件；现有 50 MB 和幂等语义不回归。

## 7. 集成负责人收口（I0）

I0 不是下放给子 Agent 的并行功能单元，由 Backend Dev 在集成 worktree 串行完成：

1. 按 F0 → U1 → U2 → U3 顺序审查并合入；每次合入后运行该单元及现有 FIT 回归。
2. 只在集成分支处理共享文件、冲突和公共契约调整；若调整改变单元验收标准，退回 Planner 重新确认。
3. 生成并核验 `docs/api/openapi.json`，增加后端架构记录，更新 `backend/README.md`、容量/暂存配置、孤儿文件审计命令和 `docs/runbooks/backup-restore.md`。
4. 更新 `docs/project-state.json`、`docs/backlog.md` 和本计划状态；在真实完成前不得把 backend baseline 改成 v0.3。
5. 保持前端可见界面不变，运行现有全栈上传、刷新、详情、下载旅程证明兼容。
6. 安排独立 Validator 只读复核数据所有权、删除失败恢复、并发配额、迁移和 API 契约。

## 8. 最终门禁与交付

至少执行：

```bash
backend/scripts/check.sh
backend/scripts/compose.sh --profile test run --build --rm backend-test
npm --prefix frontend run typecheck
npm --prefix frontend run lint
npm --prefix frontend run test
npm --prefix frontend run build
backend/scripts/compose.sh up --build -d db backend
npm --prefix frontend run e2e:fullstack
```

迁移必须在空库和 v0.2 数据库上分别验证升级，并验证 `0003 → 0002 → 0003`；回退前后的既有活动和原文件不得因迁移本身丢失。删除与配额的并发/故障注入测试必须在 PostgreSQL 上运行，不能只用 mock 或 SQLite 代替。

全部门禁和最终 Validator 通过后，按 `AGENTS.md` 创建到 `main` 的阶段性 PR，等待检查通过再合并；随后同步本地 `main`，清理本里程碑已合并的 worktree、本地分支和远程分支。不得删除无关或来源不明的工作区和分支。

## 9. 完成记录

- F0、U1、U2、U3 均从冻结依赖提交分叉，在独立 worktree 完成并经只读 Validator 验收后按顺序合入集成分支。
- 迁移头更新为 `0003_activity_data_lifecycle`；活动命名、导入列表、可恢复删除、解析 token fencing、用户配额、隔离暂存、原子提升和孤儿审计均按本计划契约实现。
- I0 统一接入上传配额错误、生成 OpenAPI，更新架构、运行手册、项目状态和待办；前端可见界面未改变。
- 后端两套 Compose 门禁均为 116 项通过，覆盖率 88.87%；前端 typecheck、lint、240 项单测、build、184 项完整 e2e、28 项 v3.4 视觉回归及 3 项真实全栈旅程通过。
- 最终独立 Validator 复核所有权、删除恢复、token fencing、配额竞态、隐私缓存、迁移、OpenAPI、文档和前端边界后 PASS。
- PR 与分支清理证据以本里程碑 GitHub 交付记录为准。
