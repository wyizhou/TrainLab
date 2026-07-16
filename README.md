# TrainLab

TrainLab 是一个运动数据分析项目。当前可运行产品为前端原型，覆盖 AI 分析、运动记录、FIT 详情、健康记录、佳明连接器、文件上传和设置页面；仓库已预留独立后端边界，但尚未选定后端技术栈。

项目最初用于实验 Claude Code 三角色开发 harness，目前已迁移为 Codex 三阶段开发模式。规划、实现、验收是每个任务的固定阶段；独立 Planner / Validator 是否介入由任务风险决定，主 Agent 负责实现和协调。

## 当前状态

- 机器可读的当前实现基线、设计基线和下一里程碑：`docs/project-state.json`。
- 当前阶段的功能要求、产品边界、已知差异和完成定义：`docs/backlog.md`。
- 带日期的项目背景与交接快照：`项目交接文档.md`。

动态状态不在 Agent 规则中重复维护，以免版本推进后留下互相冲突的信息。

## 技术栈

当前技术栈属于 `frontend/`：

- React 18 + TypeScript + Vite
- Vitest + Testing Library
- Playwright
- ESLint + Prettier + Stylelint
- Garmin FIT SDK

## 本地运行

```bash
npm --prefix frontend ci
npm --prefix frontend run dev
```

默认地址：`http://localhost:5173/`。

常用检查：

```bash
npm --prefix frontend run typecheck
npm --prefix frontend run lint
npm --prefix frontend run test
npm --prefix frontend run e2e
npm --prefix frontend run build
```

## 仓库结构

- `frontend/`：当前 React 前端工程，包含依赖、源码、测试和构建配置。
- `backend/`：后端工程预留目录；当前只有启动边界说明。
- `design/`：人工导入的只读设计输入。
- `docs/`：全项目状态、待办、工作流和历史契约。
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

小型任务由主 Agent 完成全部阶段；中型任务增加独立 Validator；大型或高风险任务增加前置独立 Planner，并在实现后由独立 Validator 复核。

完整规则见根 `AGENTS.md` 和 `docs/workflow/`。

## 设计与历史

- 当前视觉基线：由 `docs/project-state.json` 指向 `design/<当前设计版本>/` 中的交接材料。
- rev 4 历史功能与验收基线：`docs/contract/contract.md`
- 旧 Claude Code harness 历史：`docs/archive/harness/`
- 中文项目交接：`项目交接文档.md`
