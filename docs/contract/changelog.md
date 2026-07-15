# Changelog — rev 1～4 历史账本

本文件保存旧三角色 harness 落成 design_rev 1～4 时的历史记录，只作追溯。Codex 模式下的新里程碑状态写入 `docs/project-state.json` 和 `docs/backlog.md`，不再要求为每次开发追加 harness 行。

每条 contract 修订必须记录：`design_rev`、变更档位（cosmetic / structural / scope）、受影响需求编号、决议（保留 / 返工 / 废弃 / 新增）。
以下格式说明仅适用于下方既有历史记录。

格式：

```
- [<ISO 时间戳>] design_rev=<N> impact=<档位> 受影响=<需求编号,...> 决议=<...> — <一句话摘要>
```

---

<!-- 追加区（新行加在文件末尾） -->
- [2026-07-10T05:05:12Z] design_rev=1 impact=structural+scope 受影响=001-014 决议=新增 — TrainLab v1.0 首个定版落成：14 条 contract 条目（C-1..C-14）+ 需求 001–014 建档；提案 pending/design-rev-1.md 双方 ack；C-8 附真实 FIT 样本验收前置。
- [2026-07-13T00:00:00Z] design_rev=2 impact=structural+scope 受影响=001-014,001b-014b 决议=返工 — TrainLab v2.0 落成：全设备响应式（G-resp 升级四断点 mobile/tablet/desktop/wide + 7 路由×4 视口无横向溢出硬不变量）+ 全局视觉保真（#2 吸收进各返工条目 G-token/结构 e2e）+ scope 删除「数据保留策略」分组（C-14 五→四）。C-1..C-14 全部返工，新增门禁#6（响应式无溢出冒烟：7 路由无溢出、6 in-app 路由双模导航、/login 单独断言）。失效检查：001-014 全 verified 走「返工已 verified」流程——原文档留 completed/ 不动，active/ 新建 001b-014b（supersedes 原号、source_design_rev 2）。提案 pending/design-rev-2.md 双方 ack（含 §7 R1-R5 客观可断言性修订）。C-8 FIT 前置已满足（无新增 human fixture）。
- [2026-07-13T00:00:00Z] design_rev=3 impact=structural(pixel-contract) 受影响=001b-014b,001c/003c/004c/005c/006c/007c/008c/009c/010c/011c/012c/014c 决议=返工×12+保留×2 — TrainLab v3.0 落成：视觉契约显式化（fidelity: pixel-contract）。v3.0 无任何视觉设计变更（token 沿用 v2.0），仅把隐式视觉/布局契约硬化——为每个 §A `data-vc` 锚点声明以浏览器 computed 值为准的契约属性 + 交互契约（§B）。新增 G-fidelity（原型=像素级保真契约源、data-vc 镜像硬要求、computed 直接相等、不引入视觉快照）+ pixel-contract 验法细则（容差口径：颜色零容差/像素 ±1px；颜色 sRGB 归一；简写→longhand；grid auto-fit 按已填充列几何；authored 值照抄+实测复核）。C-1/C-3/C-4/C-5/C-6/C-7/C-8/C-9/C-10/C-11/C-12/C-14 追加 design_rev 3 + fidelity:pixel-contract + AC-00Xc-* + data-vc 硬要求（前序 rev 2 判据全保留）；C-14 impact scope→structural。失效检查：001b-014b 全 verified、零 data-vc、命中 §A → 走「返工已 verified」流程，原 b 文档留 completed/ 不动，active/ 新建 001c-014c（supersedes 原 b 号、source_design_rev 3）。C-2(登录)/C-13(上传)无 §A 锚点 → 保留、不建 002c/013c。不新增 e2e 门禁（沿用#1-#6）。C-8 FIT 前置续满足（无新增 human fixture）。提案 pending/design-rev-3.md 双方 ack（含 §7 Validator 裁定 §5 七开放点 + 验法细则）。
- [2026-07-14T09:00:00Z] design_rev=4 impact=structural 受影响=001c-014c 决议=就地 re-base — TrainLab v3.1 落成：完整三张 token 表（表 a 颜色 / b 圆角 / c 间距）交底，纯补全纠错、零视觉设计变更、**零 AC 值变更**。G-token 权威源迁移（token 唯一事实源由「v2.0 实现」迁至 v3.1 三表、1:1 对齐 computed，废止「色板/间距 token 以 v2.0 为准」「无 token 值变更」表述）+ 语义色 oklch→rgb 固化（accent #4292E0 / success #3FBF8F / warn #E0A040 / danger #E06060，有意为之非笔误）+ 修订 C-1 rev-1 功能判据 `oklch(0.65 0.15 230)`→accent #4292E0（消除 contract 内部 oklch/rgb 矛盾）+ 补齐 token（三边框色 / 派生半透明 accent@0.12/0.16/0.18 等 / radiusZone 4 / padCardListItem 14 16，值见三表）+ off-scale 间距裁定 (a)（5/9/11/13/18/22px 及 6.5px gap 一律具名 token、G-token 口径不放宽、token 文件外裸间距仍 error、抽验命中数须为 0）+ typography / 结构尺寸 token 化范围外例外（G-token 不 lint，仍由既有 e2e computed AC 逐条锁）。失效检查：active/ 001c–014c 共 12 条 contracted 未开工、无 feat 分支、命中 §A 引用化锚点 → 用户裁定**就地 re-base**（source_design_rev 3→4、更新 token 依据表述、目标 rgb/px 不变，不改名、不建 001d、不留墓碑；理由：contracted 未开工无已交付实现可失效、墓碑三动机全不成立、零 AC 值变更）。C-2(登录)/C-13(上传)无 §A 锚点、completed/ 全部 verified → 不动。提案 pending/design-rev-4.md 双方 ack（§8 六项裁定齐：zero_ac_value_change / inplace_rebase / gtoken_authority_migration / typography_exception / structural_dimension_exception 全 true、off_scale_spacing_verdict=a）。
