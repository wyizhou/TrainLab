# TrainLab

TrainLab 是一个运动数据分析前端产品原型，覆盖 AI 分析、运动记录、FIT 详情、健康记录、佳明连接器、文件上传和设置页面。

项目最初用于实验 Claude Code 三角色开发 harness，目前已迁移为 Codex 直接开发模式。Planner / Executor / Validator 不再是独立角色，而是一个任务内依次完成的规划、实现、验收三个阶段。

## 当前状态

- 当前实现基线：v3.1 / design_rev 4，既有功能与历史测试已交付。
- 当前设计基线：v3.2 / design_rev 5，完整页面、四档断点、关键交互和视觉基线已就绪。
- 下一里程碑：让现有实现全面对齐 v3.2。
- 产品边界：当前仍是纯前端原型，没有真实后端、认证、佳明同步或 AI 网络调用。

状态机读文件：`docs/project-state.json`。

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
3. 验收：运行自动门禁，界面改动对照 v3.2 四档视觉基线。

完整规则见根 `AGENTS.md` 和 `docs/workflow/`。

## 设计与历史

- 当前视觉基线：`design/v3.2/交接/`
- rev 4 历史功能与验收基线：`docs/contract/contract.md`
- 旧 Claude Code harness 历史：`docs/archive/harness/`
- 中文项目交接：`项目交接文档.md`
