---
id: "000"
status: contracted            # drafted | contracted | in_progress | awaiting_validation | verified | superseded
source_design_rev: 0          # 本需求基于哪一版设计拆出
supersedes: null              # 可选：本需求替代了哪一份（如 "003"）
superseded_by: null           # 可选：本需求被哪一份替代（如 "003b"）；废弃时写 null + reason
# reason: dropped             # 仅废弃墓碑需要
contract_ref: "C-0"           # 对应 contract.md 中的正式条目编号
branch: "feat/000-slug"       # feat/<id>-<slug>
---

# <需求标题>

## 背景 / 目标
<为什么做这条，解决什么。引用 contract 条目，不复制设计原文。>

## 范围
- 做：<明确要做的>
- 不做：<明确排除的，避免范围蔓延>

## 涉及组件 / token
<列出本需求触及的组件、props、token；失效检查按此列匹配变更清单。>

## 验收标准（来源：contract.md，Validator 只认这里映射的条目）
- [ ] <一条可客观判定通过/失败的标准>
- [ ] testing：<如何测，跑什么命令>
- [ ] lint：<如何测，跑什么命令>

## 备注
<可选。>

<!--
## 设计变更告警        ← 由 Planner 在失效检查时追加，Executor 见此停工。
- design_rev: <新 rev>
- 差异摘要: <...>
- 决议: 待 contract 协商
-->
