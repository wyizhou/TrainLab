# TrainLab

TrainLab 是一个运动数据分析前端产品原型，覆盖 AI 分析、运动记录、FIT 详情、健康记录、佳明连接器、文件上传和设置页面。

项目最初用于实验 Claude Code 三角色开发 harness，目前已迁移为 Codex 三阶段开发模式。规划、实现、验收是每个任务的固定阶段；独立 Planner / Validator 是否介入由任务风险决定，主 Agent 负责实现和协调。

## 当前状态

- 机器可读的当前实现基线、设计基线和下一里程碑：`docs/project-state.json`。
- 当前阶段的功能要求、产品边界、已知差异和完成定义：`docs/backlog.md`。
- 带日期的项目背景与交接快照：`项目交接文档.md`。

动态状态不在 Agent 规则中重复维护，以免版本推进后留下互相冲突的信息。

## 技术栈

- React 18 + TypeScript + Vite
- Vitest + Testing Library
- Playwright
- ESLint + Prettier + Stylelint
- Garmin FIT SDK

## 本地运行

```bash
npm ci
npm run dev
```

默认地址：`http://localhost:5173/`。

常用检查：

```bash
npm run typecheck
npm run lint
npm run test
npm run e2e
npm run build
```

## 页面

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
