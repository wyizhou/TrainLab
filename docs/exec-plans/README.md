# 执行计划

执行计划回答“当前任务如何完成”，外置需求、步骤、检查点、Agent 派发和验证证据。
产品与工程方向保存在根目录 `PLANS.md`。

## 创建时机与命名

- Git 门禁通过后，除纯概念问答和简单状态查询外，每个仓库任务都创建或恢复计划。
- Roadmap 任务只有进入 ready batch、即将修改仓库时才创建详细计划；阶段获批时不得提前批量创建未来计划。
- Roadmap 计划使用 `<stage>-<initiative-slug>-<sequence>-<feature-slug>.md`。
- 已完成任务的真正返工使用原文件名加 `-r01`、`-r02`，并链接原 completed 计划。
- 普通诊断、验证失败、命令重试和同一任务内修复只更新当前计划，不产生新版本。
- 非 Roadmap 工作使用 `ADHOC-<sequence>-<slug>.md`。
- 历史计划无需机械改名。

## 生命周期

- 非终态计划保存在 `active/`；终态 `completed` 或 `cancelled` 计划移至 `completed/`。
- 状态使用 `planned`、`ready`、`active`、`blocked`、`validating`、`validated`、
  `integrating`、`completed`、`rework` 和 `cancelled`。
- 主协调 Agent 是计划、Roadmap 和协调状态的唯一写入者；Worker 和 Validator 返回结构化事实。
- `memory.md` 只链接活动计划；步骤和检查点只保存在计划中，完成后删除 memory 指针。

```text
planned → ready → active → validating → validated → integrating → completed
                    ↕           │                         │
                  blocked       └── FAIL → active         └── FAIL → active

completed → rework → active
active|blocked|validating|validated|integrating → cancelled
```

任务级 Validator `PASS` 只进入 `validated`。并行结果集成后，集成级 Validator `PASS`
才允许完成、归档并勾选 Roadmap。单一串行任务在任务级 PASS 后可直接完成，集成验证记为不适用。

## 并行与写入隔离

- 计划记录 Roadmap ID、Batch ID、显式依赖、分支、worktree、集成分支、写入范围和禁止范围。
- 同一 batch 的活动任务不得拥有重叠写入范围。
- Worker 只修改任务合同批准的代码和测试；协调文档由主协调 Agent 统一维护。
- 依赖、接口或写入冲突出现时停止相关并行工作，并改为 `blocked` 或串行执行。
- TrainLab 不使用 `orchestrate-parallel-work`、`.orchestration`、Graph/Dashboard 或
  hash-bound handoff 管理这些状态。

## Agent 派发与升级

- 每个 subagent 派发记录抽象模型和推理档位：`low`、`medium`、`high`，不在仓库文档中记录具体模型名。
- 记录选档依据、平台支持、输入、权限、预期产物和 lint/test 门。
- 平台无法控制某维度时记录 `platform-default`。
- 能力不足时使用全新 Agent，按 `AGENTS.md` 的阶梯逐级升级；每次 attempt 记录触发证据和结果。
- `high/high` 仍无法满足合同后停止自动重试并标记 `blocked`。

## 检查点与回写

- 同一计划最多一个步骤为 `in_progress`。
- 完成关键步骤、出现阻塞、准备交接和上下文结束前更新检查点。
- 每个上下文追加一条简短迭代日志，不保存完整对话。
- 恢复时以 Git 和文件系统事实核对检查点，仓库事实优先并记录偏差。
- 验证通过后按顺序归档计划、更新适用 Roadmap 状态并删除 memory 指针。

## 验证证据

- Validator 必须是全新、只读且未参与实施的 Agent，只接收中性目标、验收标准、适用规则和当前结果。
- 计划保存 Validator 档位、命令、观察、`PASS`/`FAIL`/`INCONCLUSIVE`、未满足项和风险。
- Validator 不可用或结果为 `INCONCLUSIVE` 时不得完成计划。
