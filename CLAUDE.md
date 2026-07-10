# TrainLab — 全局不变量（跨角色）

本文件只放**跨角色的不变量**。角色专属约束写在 `docs/<role>/CLAUDE.md`，不在此重复。
两处写同一条规则、冲突时无法判定优先级——因此此处与角色文件不得内容重叠。

本项目有三个角色：**Planner（规划师）**、**Executor（执行者）**、**Validator（验收师）**。
所有状态存在文件系统里，不存在对话历史里。任一角色的新 session 读完对应 `prompt.md` 即可开工。

---

## 1. 唯一事实来源

`docs/contract/contract.md` 是唯一事实来源。

- Validator 的验收标准**只读 `contract.md`**。设计文档、对话、代码注释里的任何"新标准"都不是验收依据。
- 设计变更不得绕过 contract 直接进入 harness、backlog 或任何 active 需求。
- 只有 contract 中已**双方确认**的条目，才具备写设计、写开发的文档基础。

强制路径，任一步不可跳过：

```
设计侧 update.md (design_rev 递增)
   └─ Planner 读取、分级（只读，无副作用）
        └─ contract/pending/design-rev-<N>.md（提案）
             └─ Planner ↔ Validator 在提案文件中协商可验证标准
                  （planner_ack: true / validator_ack: true）
                  └─ contract/contract.md（落成正式条目，带 design_rev 溯源）
                       └─ executor/active/00X-*.md（需求，带 source_design_rev）
                            └─ 开发 → 验收 → completed/
```

---

## 2. 需求状态机

一份需求文档在任一时刻只处于一个状态。**没有角色可以跳过状态。**

| 状态 | 位置 | 谁可写该状态 |
|---|---|---|
| `drafted` | `contract/pending/` | Planner |
| `contracted` | `executor/active/` | Planner |
| `in_progress` | `executor/active/` | Executor |
| `awaiting_validation` | `executor/active/` | Executor |
| `verified` | `executor/completed/` | Validator |
| `superseded` | `executor/active/`，文件名加 `SUPERSEDED-` 前缀 | Planner |

需求文档 frontmatter 必须包含：

```yaml
---
id: "003b"
status: contracted
source_design_rev: 48        # 本需求基于哪一版设计拆出
supersedes: "003"            # 可选：本需求替代了哪一份
superseded_by: null          # 可选：本需求被哪一份替代
---
```

**序号前缀是执行槽位，不是需求身份。** 它唯一作用是决定执行顺序。
字典序排序：`003` < `003b` < `003c` < `004`。字母后缀单调递增，不复用。

**永不删除需求文档。** 被替代 / 废弃的文档改名加 `SUPERSEDED-` 前缀，留在 `active/` 原地作为墓碑。
理由：contract 修订条目要引用需求编号；序号断档会被下一个 Planner 误判为漏写；已存在的 `feat/<id>-*` 分支需靠文档归属判断去留。

---

## 3. 分支与提交

- 分支命名：`feat/<id>-<slug>`，`<id>` 为需求 frontmatter 的 `id`（如 `feat/003-login-form`、`feat/003b-login-form`）。
- 一条需求一条分支。Executor 建分支、开发；Validator 验收通过后合并到 `main` 并删除已合并分支。
- 被废弃需求对应的分支由 Validator 删除。
- `main` 只接受经 Validator 验收通过的代码。

---

## 4. 文件读写权限矩阵

`—` 表示只读或不可访问；`写` 表示该角色是此路径的合法写入者。

| 路径 | Planner | Executor | Validator |
|---|---|---|---|
| `docs/contract/pending/` | 写（建提案、planner_ack） | — | 写（validator_ack、协商） |
| `docs/contract/contract.md` | 写（落成条目） | — | —（只读，验收依据） |
| `docs/contract/changelog.md` | 写（append-only） | — | — |
| `docs/contract/design-state.json` | 写 | — | — |
| `docs/design/update.snapshot.md` | 写 | — | — |
| `docs/backlog.md` | 写 | —（只读） | —（只读） |
| `docs/executor/active/` 建档 / 改名 / superseded / 告警段落 | 写 | — | — |
| `docs/executor/active/` 状态 `in_progress` / `awaiting_validation` | — | 写 | — |
| `docs/executor/completed/` | — | — | 写（迁移） |
| `docs/executor/.blocked` | 创建 / 删除 | —（只读，判断是否取件） | — |
| 业务代码 | —（永不写业务代码） | 写 | —（只读验证） |

`changelog.md` append-only，永不改写历史行。
