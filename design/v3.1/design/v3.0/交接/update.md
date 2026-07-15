---
design_rev: 3
version: "3.0"
updated_at: 2026-07-13T16:00:00+08:00
---

# v3.0 更新摘要

不做任何视觉设计变更。本版把 v2.0 原型里隐式的视觉/布局契约显式化:为每个视觉契约对象加稳定锚点 `data-vc`,并在设计文档中逐锚点记录以浏览器 computed 值为准的契约属性与断点差异,供下游自动验证保真。

## 变更清单

| # | 组件/容器 | 变更 | impact | fidelity |
|---|-----------|------|--------|----------|
| 1 | G-fidelity 基线 | 交接基线升级:声明原型为像素级保真契约源,非结构示意图;新增 `data-vc` 锚点体系与逐锚点契约表 | structural | pixel-contract |
| 2 | ChatMessage(chat-bubble-ai / chat-bubble-user) | 无设计变更,声明视觉契约(独立背景/边框/不对称圆角/断点 max-width) | structural | pixel-contract |
| 3 | ChartCard(chart-card) | 无设计变更,声明视觉契约(背景/边框/圆角/四态) | structural | pixel-contract |
| 4 | 分析布局(analysis-main / session-rail / analysis-input) | 无设计变更,声明布局契约(三栏关系/会话栏尺寸/输入区在流内非 fixed) | structural | pixel-contract |
| 5 | 睡眠结构图(sleep-chart-bar-deep/-light/-rem) | 无设计变更,声明堆叠配色与条形圆角契约 | structural | pixel-contract |
| 6 | 心率区间条(hr-zone-bar) | 无设计变更,声明分区配色/高度/圆角契约 | structural | pixel-contract |
| 7 | 指标卡(metric-card) | 无设计变更,声明卡片视觉契约 | structural | pixel-contract |
| 8 | 运动列表(activities-table / activities-card-list) | 无设计变更,声明「桌面表格 / 手机卡片」重排契约 | structural | pixel-contract |
| 9 | 连接器(connectors-grid / connector-card / status-pill-*) | 无设计变更,声明网格列数/卡片/状态胶囊三态配色契约 | structural | pixel-contract |
| 10 | 设置布局(settings-page / settings-group / settings-account-grid / settings-zone-grid) | 无设计变更,声明布局契约(760 居中、分组单列堆叠、账户/区间网格断点列数) | structural | pixel-contract |
| 11 | 选择态胶囊(scope-chip / type-chip / health-tab / top-nav-item / bottom-nav-item / session-rail-item) | 无设计变更,声明「选中 vs 常态」配色/边框契约 | structural | pixel-contract |
| 12 | 弹窗(modal-connector-auth / modal-conflict / modal-overlay) | 无设计变更,声明桌面居中面板 / 手机全屏化契约 | structural | pixel-contract |
| 13 | 顶栏与导航(top-nav / sync-chip / bottom-nav / toast / btn-primary) | 无设计变更,声明断点显隐与主按钮契约 | structural | pixel-contract |

说明:本版无 structural-only 条目;所有锚点均为 pixel-contract(边框/圆角/背景/关键间距/配色/布局列数为契约)。

## 详细设计

逐锚点契约属性表(以 computed 值为准)、断点差异与交互契约见 `v3.0-设计文档.md`。锚点清单一旦定名不再变更,下游按 `[data-vc="<锚点名>"]` 选择器镜像进实现代码作验收抓手。
