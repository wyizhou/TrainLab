---
id: "012b"
status: verified
source_design_rev: 2
supersedes: "012"
superseded_by: null
contract_ref: "C-12"
branch: "feat/012b-conflict-merge"
---

# 合并弹窗 mobile 全屏（返工）

## 背景 / 目标
落成 contract C-12（返工，design_rev 2）。mobile 合并弹窗全屏（offsetWidth=视口宽、border-radius=0、内部可 overflow-y 滚动）、desktop 居中 620px、border-radius=14px。rev 1 去重/横幅/逐组选择/合并后横幅消失全部保留。原 012 留 `completed/` 当 rev 1 历史，不改写。

## 范围
- 做：ConflictModal mobile 全屏 + 内部滚动、desktop 居中 620px 的断点响应。
- 不做：去重规则/横幅/逐组选择/合并逻辑改动（rev 1 原样保留）。

## 涉及组件 / token
ConflictBanner、ConflictModal、弹窗宽度/圆角 token。

## 验收标准（来源：contract.md C-12，Validator 只认该条目）
- [ ] rev 1 功能判据保留：按「开始时间+时长」去重、来源标注保留；无法自动判定→页顶横幅「发现 n 组疑似重复运动」+「处理重复」→逐组选「保留中国区/保留国际区」→确认合并；演示连接国际区后 2 组冲突。
- [ ] e2e（门禁#3）：触发冲突 → 逐组选择 → 合并后横幅消失。
- [ ] AC-012b-1（e2e-browser，/connectors，[mobile,desktop]，前置：触发冲突并打开合并弹窗）：mobile 面板 offsetWidth=390、`border-radius=0px`、内部可 overflow-y 滚动；desktop 面板宽 620px、居中、`border-radius=14px`。
- [ ] testing / lint / type。

## 备注
依赖 001b、010b、011b。
