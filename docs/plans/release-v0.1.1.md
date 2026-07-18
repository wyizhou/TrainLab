# TrainLab v0.1.1 发布计划

- 状态：已完成并正式发布（2026-07-18）
- 产品/前端版本：`v0.1.1` / package `0.1.1`
- 后端组件版本：`0.3.1`
- 设计基线：v3.4 / design_rev 7
- 数据库迁移头：`0003_activity_data_lifecycle`

## 1. 目标

把 `v0.1.0` 之后已经完成独立验收和用户人工验收的修复发布为补丁版本。发布只收纳开发默认凭据统一、FIT 拖放、力量/攀岩语义投影、安全批量重解析和 SVG 时间构成，不引入新的产品域。

本任务会修改版本、备份兼容规则和外部 GitHub 发布状态，按大型/高风险任务执行：独立 Planner → 主 Agent 单写入 → 独立 Validator → 候选 PR → tag/Release → 后置发布状态 PR。

## 2. 范围

- 产品和前端 package 从 `0.1.0` 升为 `0.1.1`。
- 后端 package、运行时版本和 OpenAPI 从 `0.3.0` 升为 `0.3.1`。
- 新备份清单写入 `v0.1.1`；恢复端显式接受迁移头相同的 `v0.1.0` 和 `v0.1.1`，拒绝未知版本。
- 更新机器状态、发布说明、活跃 README、备份手册、交接快照和下一里程碑。
- 完成候选 PR、GitHub checks、精确 tag、GitHub Release 和后置发布状态记录。

## 3. 非范围

- 数据管理界面的实现、视觉基线或外部设计修改。
- Garmin CN Connect、TCX/GPX 后端导入、真实 AI 或外部网络调用。
- 新数据库迁移、API 破坏性变更、认证规则变化或默认凭据再次变化。
- 猜测 Garmin profile 未定义的攀岩字段 69–73。
- 公网、TLS、高可用、后台队列或自动定时同步。

## 4. 版本与备份兼容契约

- 产品 tag 和前端 package 同为 `0.1.1`。
- 后端保持独立组件版本线，使用 `0.3.1`；OpenAPI `info.version` 必须与 `trainlab.__version__` 一致。
- 迁移头继续是 `0003_activity_data_lifecycle`，本发布不新增迁移。
- 备份 manifest schema 继续为 1。生成端只写当前 `v0.1.1`，恢复端只接受 `{v0.1.0, v0.1.1}`；不能用宽泛 semver 或只比较主版本放行。
- 恢复仍须在任何写入前验证 manifest、迁移头、尺寸、SHA-256、tar 安全和 PostgreSQL dump；兼容旧产品版本不得弱化其他校验。

## 5. 验收门禁

- 后端 format、lint、mypy、pytest、覆盖率、OpenAPI 机器契约和镜像构建通过。
- 备份安全测试证明：新清单为 `v0.1.1`、合法 `v0.1.0` 可恢复、未知版本拒绝、原有校验与命令顺序不变。
- 前端 typecheck、lint、unit、完整 e2e、视觉回归和 build 通过；package 与 lockfile 都是 `0.1.1`。
- FIT 专项继续覆盖：多文件 DataTransfer 拖放、力量 10 动作/30 active/29 rest、难度 5/5、抱石 21/21、攀岩等级不可用证据门和四档 SVG 圆环。
- OpenAPI 文件与运行时语义一致，SHA-256 与 `docs/project-state.json` 相同。
- 工作区不包含真实 FIT、GPS、密码、Cookie、token、本机设计路径、构建产物或测试报告。
- 独立 Validator 无 P0/P1/P2；候选 PR 的 backend、frontend、frontend-visual、fullstack 和 image checks 全部成功。

## 6. 发布顺序

1. 从最新 `main` 创建 `codex/release-v0.1.1`。
2. 完成版本、备份兼容、测试和候选发布材料，在候选提交上运行门禁与独立 Validator。
3. 推送并创建指向 `main` 的候选 PR；checks 全部成功后合并。
4. 同步 `main`，确认精确合并提交和干净工作区；从该提交创建 annotated `v0.1.1` tag 并推送。
5. 从候选发布说明创建非草稿、非预发布 GitHub Release，并核对 tag、URL 和正文。
6. 从最新 `main` 创建发布状态分支，只记录已经发生的 PR、提交、tag、Release URL 和最终证据；通过第二个 PR 合入。
7. 同步本地 `main`，删除本次两个已合并的本地和远程分支，确认 tag 不移动、工作区干净。

## 7. 阻断与回滚

任一门禁失败、旧备份不再兼容、OpenAPI/版本不一致、PR 冲突、GitHub checks 失败、tag 已存在但指向其他提交、发布权限不足或主分支不是最新，都必须停止，不能强推、移动 tag 或把候选写成已发布。

候选代码合并后但 tag 前发现问题，使用新的修复 PR；不得重写 `main`。tag/Release 创建后发现问题，保留不可移动 tag，发布新的补丁版本。含用户数据的运行环境回滚继续使用同停写点双卷备份，不使用 Alembic downgrade。

## 8. 完成证据

- 候选提交 `0007dca05afbfbe19bd2e6a68a944f74361f4d62` 通过本地完整门禁和独立 Validator，无 P0/P1/P2。
- [PR #16](https://github.com/wyizhou/TrainLab/pull/16) 的 backend、frontend、frontend-visual、fullstack 和 image 五项检查全部成功，并合并为 `ed8b42b85bc3e6b167e6718e61568f95fcaf7d1b`。
- annotated tag `v0.1.1` 精确指向上述合并提交；[GitHub Release v0.1.1](https://github.com/wyizhou/TrainLab/releases/tag/v0.1.1) 已于 2026-07-18 发布，非草稿、非预发布。
