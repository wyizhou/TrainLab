# Contract — 唯一事实来源

本文件是 TrainLab 唯一事实来源（single source of truth）。
Validator 的验收标准**只读本文件**。任何来自设计文档、对话、代码注释的"新标准"都不是验收依据。

只有本文件中已双方确认（`planner_ack` + `validator_ack`）落成的条目，才具备写设计、写开发的文档基础。
提案在 `pending/` 协商，双方 ack 后由 Planner 落成到此处。

---

## 条目格式

每条正式条目形如：

```
### C-<n> — <标题>
- design_rev: <落成时的 design_rev>
- impact: cosmetic | structural | scope
- 受影响需求: 003, 003b
- 决议: 保留 | 返工 | 废弃 | 新增
- 可验证标准:
  - [ ] <一条可客观判定通过/失败的标准>
  - [ ] <做什么 / 不做什么 / 如何 test / 如何 lint>
```

---

## 正式条目

_（暂无。首个设计变更经 pending 协商双方 ack 后，由 Planner 落成于此。）_
