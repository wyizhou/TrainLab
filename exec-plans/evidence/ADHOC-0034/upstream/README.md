# Agent 协作基础 Harness

这是一个通用的 Agent 协作基础 Harness 工程，通过协作规则、计划和记忆模板，帮助 AI 按明确的分工完成规划、开发、验证和交付。

你可以把它理解为一套供 AI 使用的项目协作规范。实际的子 Agent 创建、调度和并行执行依赖所使用的 AI 工具。

## 协作方式与优势

- **跨角色流水线**：开发 A 时可规划当前输入已就绪的 B；固定 A 的受审内容及相关依赖后，可验证 A，同时开发已审核、依赖与资源均就绪的 B。
- **独立功能并行开发**：不同独立功能在规划已审核、当前依赖就绪、共享项修改归属和版本交接明确、写入与测试资源不冲突时，可由多个 Developer 在各自独立工作目录和分支开发。每个目录同一时刻最多一个 Developer，即使修改不同文件也不例外；子功能仍留在所属功能分支。
- **多个子 Agent（subagents）**：将任务交给不同子 Agent，每次派发、修复和复验使用全新实例，提供完整任务材料，减少对旧聊天的依赖。
- **明确的角色分工**：主 Agent 统筹目标和交付，Planner 负责规划，Developer 负责实现，Validator 负责验证。
- **独立验证**：开发完成后，由独立 Validator 根据要求检查成果，通过后再由主 Agent 亲自完成最终验收，避免仅凭开发者的完成声明交付。

| 角色 | 职责 |
| --- | --- |
| 主 Agent | 与用户确认目标和验收标准，审核规划、调度任务、维护记录并亲自完成最终验收。 |
| Planner（子 Agent） | 拆解任务，明确接口、依赖、执行顺序及各项预期；需要调整规划时说明遗漏和理由。 |
| Developer（子 Agent） | 在批准范围内实现功能、修复问题、编写测试并运行检查，返回实际结果、证据和未解决事项。 |
| Validator（子 Agent） | 独立验证成果、复现问题或复验修复，检查正常、错误和边界行为，不改变验收标准或修改受审内容。 |

例如：开发 A 时，B 的规划输入已齐备，就可先规划 B，不必等 A 交付；但 B 若需要 A 尚未确定的接口，就先等该输入。B 只有通过规划审核、当前开发输入及资源就绪后才能开发。A 的验证使用与 B 可写工作区隔离的固定内容，包含未提交差异及相关依赖；分支名或仍在变化的目录不算冻结。

并行前要逐项确定共享文件、接口和重要数据规则由谁修改，其他功能使用哪个固定版本、何时交接，不能各自在分支重复修改。独立目录不自动隔离数据库、账号和端口；归属不清、输入未就绪或资源冲突时，只暂停或串行受影响任务及其依赖链。受审内容或影响结果的依赖变化后，旧证据不能证明新版本通过，须重新固定并独立验证。

每条功能线仍须完成规划审核、开发、独立验证、主 Agent 验收和交付。主 Agent 指定组合与冲突处理责任方，记录实际组合版本及相关依赖，冲突或接口不兼容按既有修复与复验流程处理。各功能分别通过或没有文本冲突，不能替代最终组合版本的集成检查、独立验证和主 Agent 验收；基准或组合内容变化影响结果时须补查和复验，最终仍由用户确认后合并。

## 文件说明

| 文件 | 用途 |
| --- | --- |
| [AGENTS.md](./AGENTS.md) | 回答偏好、角色分工、协作流程与验收交付约定。 |
| [PLAN.md](./PLAN.md) | 总计划空模板，用于记录总目标、范围、大功能预期与验收标准、依赖、状态和执行计划链接。 |
| [exec-plans/template.md](./exec-plans/template.md) | 单个功能的执行计划空模板，用于记录阶段任务、检查证据、当前检查点和失败记录。 |
| [MEMORY.md](./MEMORY.md) | 项目记忆空模板，用于保存已确认的决定、已验证的事实和可复用经验。 |
| [subagent-templates/planner.md](./subagent-templates/planner.md) | Planner 任务模板，用于首次规划或规划调整。 |
| [subagent-templates/developer.md](./subagent-templates/developer.md) | Developer 任务模板，用于正常开发或问题修复。 |
| [subagent-templates/validator.md](./subagent-templates/validator.md) | Validator 任务模板，用于首次验证、问题复现或修复后复验。 |
| [references/](./references/README.md) | AI 整理的接口等文档摘要，注明来源、日期和待核内容。 |
| [skills/](./skills/README.md) | 完整项目技能包及配套脚本、模板和资料。 |
| [README.md](./README.md) | 仓库说明、使用方法与 MIT 授权。 |

## 使用方法

先克隆本仓库：

```bash
git clone https://github.com/wyizhou/agentsmd.git
```

然后根据你的情况，选择一种方式：

### 方式一：用于已有项目

将以下文件和目录复制到项目根目录，保持目录结构：

```text
你的项目/
├── AGENTS.md
├── PLAN.md
├── MEMORY.md
├── exec-plans/
│   └── template.md
├── references/
│   └── README.md
├── skills/
│   └── README.md
└── subagent-templates/
    ├── planner.md
    ├── developer.md
    └── validator.md
```

将 AI 的工作目录设置为该项目目录。已有同名规则或计划时，先核对并整合，避免覆盖原有内容。

### 方式二：直接作为新项目的起点

将克隆得到的 `agentsmd` 目录设置为 AI 的工作目录，直接在其中开始新项目。

### 开始工作

告诉 AI：

> 请先读取 AGENTS.md，按照其中的协作约定开展工作。我要完成的目标是：……

后续的规划、任务分派、验证和项目记录由主 Agent 按约定组织，详细规则见 [AGENTS.md](./AGENTS.md)。

## MIT 授权

本仓库采用 MIT 许可证，允许复制、修改和分发，使用时保留下方版权和许可声明即可。

MIT License

Copyright (c) 2026 wyizhou

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
