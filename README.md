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

将 AI 的工作目录设置为该项目目录。已有同名规则或计划时，先核对并整合，避免覆盖原有内容。上面的清单仅包含通用层；可选适配的隐藏目录需另行显式复制，见下方「可选接入」。

### 方式二：直接作为新项目的起点

将克隆得到的 `agentsmd` 目录设置为 AI 的工作目录，直接在其中开始新项目。

### 开始工作

告诉 AI：

> 请先读取 AGENTS.md，按照其中的协作约定开展工作。我要完成的目标是：……

后续的规划、任务分派、验证和项目记录由主 Agent 按约定组织，详细规则见 [AGENTS.md](./AGENTS.md)。

## 可选接入：Pi 三角色

仅在使用 Pi 时按需接入；其他 AI 环境继续使用通用层，不要求安装或检查此适配。它不替代 [AGENTS.md](./AGENTS.md) 的协作流程，也不会覆盖内置角色。

### 复制与加载

1. 用于已有项目时，显式复制隐藏目录 `.pi/` 中的以下文件到项目根目录（普通 `*` 复制可能漏掉隐藏文件）：[APPEND_SYSTEM.md](./.pi/APPEND_SYSTEM.md)、[settings.json](./.pi/settings.json)、[planner.md](./.pi/agents/planner.md)、[developer.md](./.pi/agents/developer.md)、[validator.md](./.pi/agents/validator.md) 和 [.gitignore](./.pi/.gitignore)，保持目录结构。仅复制这些适配文件，不复制运行产物 `.pi/subagents/`；忽略规则也仅针对该目录。
2. 已有 `.pi/settings.json` 时按键合并 `subagents.agentOverrides`，逐项保留或确认已有自定义，不能整份覆盖。已有 APPEND 或同名角色先核对并整合。项目 APPEND 优先于全局同名文件，**不是两份自动叠加**。
3. 需要 `pi-subagents` 扩展。确认未安装时，由用户安装或明确授权后执行 `pi install npm:pi-subagents`；本仓库不配置自动安装。接口不可见也可能是未启用、未加载或工具受限，先查明原因，不自动改全局设置。
4. 从项目根目录启动 Pi，并由用户确认是否信任项目；不绕过信任。安装或外部修改角色/设置后 `/reload` 并重新核对实际映射；若修改的是 `/trust` 保存的信任决定，须重启，`/reload` 不能替代。APPEND 按当前 cwd 加载，角色/设置的最近项目根发现是另一套逻辑，不能依赖从子目录启动也读到根 APPEND。

接入后主 Agent 首次检查 `list` capabilities 与 `models`，必要时 `get`，核对 `agentsmd.planner`、`agentsmd.developer`、`agentsmd.validator` 的精确身份、项目来源及可执行性。就绪时提示预置角色和实际配置，无变化不重复提醒。注册表发现不代表认证、额度或真实启动成功；缺能力只暂停受影响协作，不阻塞普通讨论，不静默替换内置角色。

### 模型与推理配置

实际 `.pi/settings.json` 只为这三个完整角色名设置 `model: "inherit"`，不改主对话默认或内置角色。可在各角色条目内修改 `model`、添加 `thinking`，例如将 Developer 条目改为：

```json
"agentsmd.developer": { "model": "inherit", "thinking": "medium" }
```

这是现有 JSON 对象中的条目，不是完整设置文件。JSON 不支持注释，也没有 `thinking: "inherit"`。另一种方式是取消角色 YAML 中独立一行的注释：

```yaml
model: inherit
# thinking: high
```

Planner / Validator 提供 `high` 注释示例，Developer 提供 `medium`；注释默认不生效。模型字符串可用实际注册表中的精确 `provider/id`，也可带受支持的 `:level` 后缀，不要照抄占位名称。

优先级要按实际来源核对：本次派发覆盖最优先；settings 同字段覆盖角色 YAML，项目同字段覆盖用户，同一 settings 来源内 provider-scoped override 覆盖普通角色 override。`subagents.defaultModel` / `defaultThinking` 只填角色缺失项；本适配显式 `model: inherit` 不会被 defaultModel 替换，项目 settings 的同名 model 也会覆盖用户设置或 YAML 中的固定模型。取消 YAML thinking 注释后，如 settings 已显式设置该字段，仍以 settings 为准。合法模型后缀优先于独立 thinking。

默认模型由扩展原生继承；**省略 thinking 不保证继承主会话当前等级**。无明确推理策略时，APPEND 约定主 Agent 当次读取主会话 `PI_REASONING_LEVEL`，保留已解析精确模型，用派发 model 后缀补齐，不写回配置。角色 thinking、模型后缀、子 Agent 默认、provider overrides、显式清除/禁用及模型能力/上限等策略优先；`thinking: false` 不等于 `off`，`models` 显示 `default` 也不证明无人配置。未知或不兼容须查明或停止受影响派发，不能猜测或静默降级；工具顶层 thinking 不是派发参数。这是提示约定，不是程序保证，真实生效仍需启动证据。

### 角色边界

主 Agent 首次按通用任务模板给齐材料，每次显式 fresh、全新实例，不 fork/resume/追加任务，子角色不调度或做安装引导。默认继承项目规则、不继承全局 AGENTS 类上下文，不启用角色持久记忆；不意味着屏蔽全局配置或全部扩展。Planner / Validator 的 read-only 标签不是沙箱；Validator 的写工具仅用于任务授权的隔离测试和证据，受审内容仍须冻结。浏览器等扩展工具须另行核对白名单及提供方，缺少时不能跳过验收。

接口核对依据：Pi 核心 0.86.0 的 README、settings / environment-variables 文档及 ResourceLoader；pi-subagents 0.70.0 的 agents / models / configuration / tool-reference / workflows 文档与实际解析器（2026-09-20）。版本变化须重新检查，不代表所有版本或真实启动均已验证。

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
