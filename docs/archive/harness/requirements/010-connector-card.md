---
id: "010"
status: verified
source_design_rev: 1
supersedes: null
superseded_by: null
contract_ref: "C-10"
branch: "feat/010-connector-card"
---

# 连接器·卡片状态集合 ConnectorCard

## 背景 / 目标
落成 contract C-10。佳明双区连接器卡片状态机。

## 范围
- 做：四态（已连接/未连接/同步中/同步失败带错误块重试）、上次同步时间/已同步数量/自动同步间隔、演示初始态。
- 不做：授权弹窗（C-11）、合并（C-12）、上传（C-13）。

## 涉及组件 / token
ConnectorCard。

## 验收标准（来源：contract.md C-10；不要求 e2e）
- [ ] 四态齐全（含同步失败红块：失败时间+原因，按钮变「重试同步」）。
- [ ] 显示上次成功同步时间、已同步数量、自动同步间隔（30 分钟/1 小时/6 小时/仅手动）。
- [ ] 演示初始：中国区同步失败(ETIMEDOUT)、国际区未连接。
- [ ] unit：四态各渲染对应胶囊与按钮文案。
- [ ] testing/lint/type：G-* 基线。
