# TrainLab

TrainLab 是一个运动数据分析项目。首个正式产品版本定为 `v0.1.0`：前端覆盖 AI 分析、运动记录、通用运动详情、健康记录、佳明连接器、文件上传和设置页面；后端提供真实账号登录、用户归属的本地 FIT 上传与持久化、重命名、导入记录、可恢复删除、存储配额、数据库迁移和前后端一体化运行。佳明在线同步、TCX/GPX 后端导入和 AI 仍保持模拟或未接入。

项目最初用于实验 Claude Code 三角色开发 harness，目前已迁移为 Codex 三阶段开发模式。规划、实现、验收是每个任务的固定阶段；独立 Planner / Validator 是否介入由任务风险决定，主 Agent 负责实现、集成和协调。大型任务在公共基础验收后，可将真正独立的交付单元分配到各自分支、worktree 和子 Agent。

## 当前状态

- 产品发布信息、范围和验证结果：`docs/releases/v0.1.0.md`。正式 tag/Release 只在发布 PR 合并并通过最终验收后创建；开发分支中的同名文档不等于已经发布。
- 机器可读的当前实现基线、设计基线和下一里程碑：`docs/project-state.json`。
- 当前阶段的功能要求、产品边界、已知差异和完成定义：`docs/backlog.md`。
- 带日期的项目背景与交接快照：`项目交接文档.md`。

动态状态不在 Agent 规则中重复维护，以免版本推进后留下互相冲突的信息。

## 技术栈

前端：

- React 18 + TypeScript + Vite
- Vitest + Testing Library
- Playwright
- ESLint + Prettier + Stylelint
- Garmin FIT SDK

后端：

- Python 3.12 + FastAPI
- SQLAlchemy 2 + PostgreSQL 17 + Alembic
- Garmin FIT SDK 与私有原文件存储
- uv + Ruff + mypy + pytest
- Docker Compose

## 本地运行

完整产品推荐使用 Docker Compose：

```bash
backend/scripts/compose.sh up --build -d db backend
TRAINLAB_DEV_PASSWORD=123456 backend/scripts/compose.sh exec -T \
  -e TRAINLAB_DEV_PASSWORD backend trainlab set-development-owner \
  --username admin --password-env TRAINLAB_DEV_PASSWORD
```

开发期间的固定本机登录凭据为 `admin / 123456`，验证码输入登录页显示的 4 位数字。该凭据公开且强度很低，只允许用于 Compose 的 `development` 环境；生产或可被其他设备访问的环境禁止使用。完整规则、恢复旧备份后的重新配置命令和安全边界见 `docs/runbooks/local-development.md`。默认地址：`http://localhost:8000/`。Compose 只绑定 `127.0.0.1`，当前版本仅支持本机 HTTP，不支持公网、TLS 或高可用部署。前端单独开发仍可运行 `npm --prefix frontend run dev`，默认地址为 `http://localhost:5173/`。

常用检查：

```bash
npm --prefix frontend run typecheck
npm --prefix frontend run lint
npm --prefix frontend run test
npm --prefix frontend run e2e
npm --prefix frontend run build
backend/scripts/check.sh
python3 backend/scripts/test_release_backup_tools.py
npm --prefix frontend run e2e:fullstack
```

Compose 使用独立命名卷保存 PostgreSQL 数据和私有 FIT 原文件；普通 `down` 会保留两者，`down -v` 会同时删除，使用前必须确认已经通过 `backend/scripts/backup_release.py` 取得同停写点双卷备份。恢复、回滚和隔离演练见 `docs/runbooks/backup-restore.md`。

本机忘记密码时使用 `trainlab reset-password --username <name>`；需要恢复固定开发凭据时使用 `set-development-owner`；只需强制退出全部设备时使用 `trainlab revoke-sessions --username <name>`。这些命令只在服务器 CLI 提供，不新增浏览器找回密码或会话管理 UI，详细安全用法见 `docs/runbooks/local-development.md`。

私有原文件默认按用户限制为 5 GiB、10,000 个；孤儿文件审计使用 `backend/scripts/compose.sh exec backend trainlab reconcile-storage`，该命令默认 dry-run。删除动作、`--apply` 清理和 `down -v` 都应先核对数据库与私有卷的同时间点备份。

`npm --prefix frontend run e2e` 会执行完整的功能、样式、几何与截图契约。字体验收采用有序的跨平台字体栈：macOS、Windows 和 Linux 可以使用栈中各自可用的字体；文字内在宽度通过不重叠、固定间距、边界和无溢出关系验收，其他几何仍执行严格基线比较。

## 仓库结构

- `frontend/`：当前 React 前端工程，包含依赖、源码、测试和构建配置。
- `frontend/src/styles/`：集中维护的前端样式和设计 token。
- `frontend/tests/visual-baselines/`：实现侧自包含的视觉回归测试资产。
- `backend/`：FastAPI 后端、数据库模型与迁移、测试和运行脚本。
- `compose.yaml`：PostgreSQL、完整应用与隔离测试环境。
- `docs/`：全项目状态、待办、工作流和历史契约。
- `docs/plans/`：跨多轮大型里程碑的动态实施计划与交付单元。
- `AGENTS.md`：对整个仓库生效的 Codex 项目规则。

## 页面

以下路由由 `frontend/` 提供：

- `/login`：登录页
- `/`：分析
- `/activities`：运动记录
- `/activities/:id`：运动详情
- `/health`：健康记录
- `/connectors`：连接器与文件上传
- `/settings`：设置

## 开发工作流

项目采用同一任务内的三阶段流程：

1. 规划：明确范围、非范围和验收标准。
2. 实现：直接修改代码并同步测试。
3. 验收：运行自动门禁，界面改动对照当前权威设计基线。

小型任务由主 Agent 完成全部阶段；中型任务增加独立 Validator；大型或高风险任务增加前置独立 Planner，并在实现后由独立 Validator 复核。大型任务若可证明单元之间的依赖和文件边界清晰，可使用受控的 worktree 并行实现；集成分支和最终交付仍由主 Agent 负责。

完整规则见根 `AGENTS.md` 和 `docs/workflow/`。

## 设计与历史

- 当前设计来源：由用户在每个 UI 任务中提供仓库外的只读原型路径；`docs/project-state.json` 只保存可迁移的版本、修订号和摘要，不保存本机绝对路径。
- 视觉回归资产：`frontend/tests/visual-baselines/` 用于检测实现漂移，不替代外部设计来源，也不能为了让测试通过而随意更新。
- 字体回归：批准字体栈的声明顺序、字号、字重、行高、单行约束与结构关系属于视觉契约；不同系统字体的自然字宽不要求伪装成同一个字体的像素宽度。
- rev 4 历史功能与验收基线：`docs/contract/contract.md`
- 旧 Claude Code harness 历史：`docs/archive/harness/`
- 中文项目交接：`项目交接文档.md`
