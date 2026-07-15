---
design_rev: 4
version: "3.1"
updated_at: 2026-07-14T15:00:00+08:00
---

# v3.1 更新摘要

纯参数交底补全,零视觉设计变更。将 v3.0 散列在各锚点的裸值收敛为单一权威 token 清单(颜色/圆角/间距三张表,以浏览器 computed 值为准),§A 各锚点契约属性改为引用 token 名,并废止"以 v2.0 token 为准"的表述。所有 `data-vc` 锚点名保持不变。

## 变更清单

| # | 组件/容器 | 变更 | impact | fidelity |
|---|-----------|------|--------|----------|
| 1 | G-token 权威源 | 新增完整 token 清单(颜色/圆角/间距)作为唯一事实源;废止"以 v2.0 token 为准""无 token 值变更",改为"实现须 1:1 对齐本表 computed 值"(实现对齐,非设计变更) | structural | pixel-contract |
| 2 | §A 全部锚点 | 契约属性由散列裸值改为引用 token 名,与 token 表交叉核对 | structural | pixel-contract |
| 3 | 颜色 token | 补齐缺失色:3 种边框色、panelNav、accentDeep、accentText、textFaint、sleepRem、toast 底/边、遮罩、hover;强调色定为 #4292E0(非 oklch 渲染值);**success/warn/danger 由 v2.0 oklch 定义固化为原型实测 rgb(#3FBF8F/#E0A040/#E06060),属实现向原型对齐、有意为之** | structural | pixel-contract |
| 4 | 圆角 token | 补齐 2/3/8/12px 与非对称值(14 14 14 4、14 14 4 14、0 0 3 3、3 3 0 0) | structural | pixel-contract |
| 5 | 间距 token | 照实交底手调 off-scale 值(5/9/11/13/18/22px、6.5px gap 等),不凑 8pt scale | structural | pixel-contract |
| 7 | 缺陷修正 | 原地纠错:新增 radiusZone(4px,hr-zone-bar)补 4px 圆角档并清除 A5 编辑残留;新增 padCardListItem(14 16)使 A14 无裸值;声明 typography 与固定结构尺寸为本版范围外显式例外 | structural | pixel-contract |
| 6 | 断点差异 | tablet(实测)升级;mobile 专属值凡未实采标"待渲染确认"并说明 | structural | pixel-contract |

说明:本版无 structural-only 条目。锚点名与 v3.0 一致,不得改名。

## 详细设计

三张 token 表 + 引用化 §A + §B 交互契约见 `v3.1-设计文档.md`。
