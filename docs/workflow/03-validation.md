# 阶段三：验收

## 目标

用可重复的证据证明实现符合本次验收标准。验收是每个开发任务的最后阶段；中型及以上任务由独立 Validator 增加只读复核，但不再通过旧 harness 移动需求文件或接管分支。

## 自动化门禁

按改动范围先跑相关测试，交付前按风险运行：

```bash
npm --prefix frontend run typecheck
npm --prefix frontend run lint
npm --prefix frontend run test
npm --prefix frontend run e2e
npm --prefix frontend run build
backend/scripts/check.sh
backend/scripts/compose.sh --profile test run --build --rm backend-test
```

跨端登录、会话、静态托管或 Compose 变化还需运行：

```bash
backend/scripts/compose.sh up --build -d db backend
TRAINLAB_DEV_PASSWORD=123456 backend/scripts/compose.sh exec -T \
  -e TRAINLAB_DEV_PASSWORD backend trainlab set-development-owner \
  --username admin --password-env TRAINLAB_DEV_PASSWORD
TRAINLAB_PEER_PASSWORD=correct-password backend/scripts/compose.sh exec -T \
  -e TRAINLAB_PEER_PASSWORD backend trainlab create-user \
  --username peer-user --display-name Peer --password-env TRAINLAB_PEER_PASSWORD
npm --prefix frontend run e2e:fullstack
```

后端测试数据库名必须以 `_test` 结尾。数据库迁移变化应至少验证空库升级，以及当前迁移允许时的回退再升级。

不得通过删除测试、扩大容差或降低规则等级来解决失败。

## UI 与视觉验收

涉及界面时：

1. 使用用户在当前任务中提供的只读外部设计路径，结合 `docs/project-state.json` 校验项目标识、版本、修订号和内容摘要；不得沿用历史本机路径。
2. 打开实现与外部原型的同一路由、同一状态，并使用当前外部设计定义的适用视口；不得把历史版本的视口清单当作永久规则。
3. 对照整页截图检查页面宽度、居中、模块顺序、网格、留白和响应式重排。
4. 使用当前设计契约定义的稳定锚点和机器基线检查关键 computed 样式与矩形位置。
5. 覆盖默认态以及任务涉及的弹窗、展开、错误、空态等交互状态。
6. 检查 document 级横向溢出，并记录原型已知例外。
7. 运行 `frontend/tests/visual-baselines/` 对应的实现回归检查；它只能发现实现漂移，最终设计判断仍以本次外部原型实测为准。
8. 完成后复核外部设计关键文件摘要未变化，并确认仓库中没有持久化外部绝对路径。

跨平台字体按批准的有序字体栈验收。字体栈声明、字号、字重、行高、间距、单行与溢出规则必须严格一致；由不同批准字体的字形宽度引起的内在横向尺寸，使用固定边界、相邻间距、顺序、不重叠和无裁切关系验收。不得把字体差异扩大为全局几何豁免：纵向尺寸、固定容器、网格轨道和非文字驱动的位置仍执行当前精确基线。

## 独立复核

按根 `AGENTS.md` 的任务分级执行：小型任务由主 Agent 自验；中型和大型/高风险任务安排独立 Validator；用户明确要求时无条件安排。

Validator 只检查并报告，不默认修改代码。报告必须包含复现条件、期望结果、实际结果和证据；发现问题后由主 Agent 修复并重新验证。Validator 不以主 Agent 的完成声明代替独立判断。

## 并行交付的分层验收

采用分支和 worktree 并行时，验收分为三层：

1. **单元验收**：子 Agent 在自己的提交上运行该单元测试；独立 Validator 按单元契约只读复核文件边界、失败场景和证据。
2. **逐次集成验收**：集成负责人每合入一个单元，检查提交来源并运行受影响模块的回归，确认没有破坏已合入单元。
3. **里程碑验收**：所有单元合入后，在集成分支运行完整适用门禁、迁移升级/回退/再升级、跨端旅程和最终独立 Validator 复核。

单元分支通过不等于里程碑完成。只有集成分支完整通过、范围与动态计划一致、工作区无遗漏，才能创建阶段性 PR。
