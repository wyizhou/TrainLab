# TrainLab 邮件设计规范

## 1. 设计目标

TrainLab 邮件以训练决策为核心：日报先回答“今天能不能练”，周报先回答“下周推进、维持还是减量”。复杂指标进入分层卡片，工程证据进入底部低视觉权重区域。

视觉方向为“清爽运动日志”：年轻、清晰、可信、带节奏感，但不过度游戏化。

## 2. 页面结构

### 日报

1. 隐藏 Preheader
2. EmailHeader：品牌、固定标题、日期
3. SafetyHero：ready / caution / blocked
4. CoachSummary：AI 教练原文与停止条件
5. CourseCard：今日课程、目标、步骤、降级规则
6. ActivitySnapshot：昨日活动或无活动状态
7. SleepCard + RecoveryCard
8. StaticChart：仅渲染真实心率分区、睡眠阶段或活动序列
9. TrendSummary：14 天聚合；无逐日序列时不画折线
10. ExtraSectionRenderer
11. EvidenceFooter
12. PrivacyFooter

### 周报

1. 隐藏 Preheader
2. EmailHeader：品牌、固定标题、周期
3. WeeklyDecisionHero：advance / hold / deload / blocked
4. WeeklyKPI
5. WeekComparison
6. StaticChart：仅使用显式逐日数组
7. EvidenceConsistency
8. PlanTimeline：七日课程
9. ExtraSectionRenderer
10. EvidenceFooter
11. PrivacyFooter

## 3. 组件清单

| 组件 | 主要内容 | 邮件规则 |
|---|---|---|
| EmailHeader | 标志、英文眉题、固定中文标题 | 主题与顶部标题使用同一变量 |
| SafetyHero | 状态图形、状态词、结论 | 状态不可只靠颜色 |
| WeeklyDecisionHero | progression 决策与维度 | 显示英文枚举与中文解释 |
| CoachSummary | AI 原文、停止条件 | 不改写、不摘要 |
| CourseCard | 类型、负荷、目标、步骤、降级、停止 | blocked 时隐藏 |
| ActivitySnapshot | 昨日类型、距离、时长、配速、心率、RPE | 无活动不显示 0 KPI |
| SleepCard | 起止、时长、完整性 | 不完整时明确标记 |
| RecoveryCard | RHR、HRV、变化、VO₂ Max | 缺失项显示“暂无数据” |
| MetricGrid / WeeklyKPI | 真实数值与单位 | 单位不可猜测 |
| StaticChart | PNG 2x、alt、文字/表格 fallback | 无真实数组则不显示 |
| PlanTimeline | 七天日期卡 | 手机端纵向堆叠 |
| ExtraSectionRenderer | 白名单扩展模块 | 未知 custom 不直接渲染 |
| EvidenceFooter | SHA、ID、来源、claim | 低视觉权重、允许断行 |
| PrivacyFooter | 使用边界 | 始终显示 |

## 4. 尺寸与响应式

| 项目 | 桌面 | 手机 |
|---|---:|---:|
| 目标画布 | 672px | 375px |
| 内容宽度 | 624px | 343px |
| 左右内边距 | 24px | 16px |
| 卡片内边距 | 20–24px | 16–20px |
| KPI | 最多 4 列 | 最多 2 列 |
| 双卡片 | 2 列 | 单列 |
| 七日计划 | 紧凑纵向时间轴 | 七张全宽日期卡 |
| 证据区 | 两列键值 | 单列键值 |

生产模板使用 `width="100%"` 与 `max-width:672px`，即使客户端忽略 media query，也能安全收缩。手机端不得产生横向滚动。

## 5. 颜色

设计源使用 OKLch，邮件内联样式使用 sRGB fallback。完整值见 `brand-spec.md` 与 `design-tokens.json`。

| 角色 | sRGB | 用途 |
|---|---|---|
| Background | `#F4F8F8` | 邮件外层 |
| Surface | `#FFFFFF` | 卡片与正文 |
| Foreground | `#17323B` | 主文字 |
| Muted | `#556970` | 单位、说明、证据 |
| Border | `#D7E4E6` | 结构边界 |
| Accent | `#087A78` | TrainLab 品牌锚点 |
| Running | `#087B8C` | 跑步标签和图表 |
| Climbing | `#B85B18` | 攀岩标签和图表 |
| Sleep | `#48548E` | 睡眠标签和图表 |
| Recovery | `#26744B` | 恢复图表 |

主强调每个首屏最多出现两次。活动色属于数据语义，不作为装饰背景大面积铺开。

## 6. 状态色

| 状态 | 文字 | 背景 | 边框 | 必须显示的文字 |
|---|---|---|---|---|
| ready | `#1B6F47` | `#E7F5ED` | `#A9D7BD` | 可以训练 |
| caution | `#8A5700` | `#FFF2CF` | `#E6C66D` | 需要谨慎 |
| blocked | `#A7372F` | `#FDE9E6` | `#E6AAA4` | 报告已阻断＋error_code |
| hold | `#40535A` | `#EDF1F2` | `#CAD8DB` | 维持 |
| advance | `#1B6F47` | `#E7F5ED` | `#A9D7BD` | 进阶＋维度 |
| deload | `#8A5700` | `#FFF2CF` | `#E6C66D` | 减量＋依据 |

blocked 不显示正常绿色图表、可执行 CourseCard 或 PlanTimeline。

## 7. 字体

不加载外部字体。

```text
-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif
```

证据区：

```text
SFMono-Regular, Consolas, Menlo, monospace
```

### 字号

| 角色 | 桌面 | 手机 | 字重 | 行高 |
|---|---:|---:|---:|---:|
| 邮件标题 | 28px | 24px | 600 | 1.2–1.25 |
| 区块标题 | 20px | 20px | 600 | 1.3 |
| 卡片标题 | 17–22px | 17–20px | 600 | 1.3–1.4 |
| 正文 | 15–16px | 15–16px | 400 | 1.55–1.6 |
| 小字 | 13px | 13px | 400/550 | 1.5 |
| 证据 | 10–12px | 10–12px | 400 | 1.5 |

英文眉题为 ALL CAPS，`letter-spacing` 使用 `0.08em`。32px 以上标题使用负字距。

## 8. 间距、圆角与阴影

- 基础间距：4 / 8 / 12 / 16 / 20 / 24 / 32 / 40px。
- 卡片圆角：16px；邮件外框：20px；紧凑提示：12px；状态 pill：999px。
- 卡片主要依赖边框分层；关键 CourseCard 可使用 `0 8px 24px rgba(23,50,59,.08)`。
- Outlook 不支持圆角或阴影时，内容层级仍由标题、边框和留白维持。
- 禁止圆角卡片叠加彩色左边框。

## 9. 图表颜色与资源

图表 palette：

```text
#087B8C  running
#B85B18  climbing
#48548E  sleep
#26744B  recovery
#8A5700  caution
#A7372F  blocked / high risk
```

资源结构：

```text
assets/
  icons/       SVG source + PNG 2x fallback
  charts/      SVG source + PNG 2x fallback
  illustrations/README.md
```

图表规则：

1. SVG 是设计源；PNG 是邮件生产资源。
2. PNG 宽度 1248px，对应邮件逻辑宽度 624px。
3. 图片包含 alt，图片下方保留文字或表格 fallback。
4. 条形长度、折线点位必须由真实数值计算。
5. 周报的逐日负荷和睡眠只读取显式数组；不从 SHA 或缺失日报反推。
6. 日报只有聚合 14 天数据时只显示 KPI，不伪造 14 点折线。

## 10. 条件显示

| 条件 | 行为 |
|---|---|
| `status == blocked` | 显示阻断主卡；隐藏课程、计划和正常图表；保留证据 |
| `today_course == null` | 显示“今日未安排课程”，不生成默认课程 |
| 无昨日活动 | 显示中性空状态，不显示 0 km |
| 单项指标为 null | 关键指标显示“暂无数据”；非关键项隐藏 |
| `heart_rate_zones[]` 为空 | 不显示分区图 |
| 只有平均/最高心率 | 只显示两个数值 |
| `sleep_stages[]` 不完整 | 不显示完整阶段时间轴 |
| 图表采样不足 | 显示“图表数据不足”与已知值表 |
| `activity_kind == rest` | 隐藏距离、配速、心率目标 |
| `load_level == hard` | 显示“高负荷”文字标签与停止条件 |

## 11. 可访问性

- 正文对比度目标不低于 4.5:1；大字号不低于 3:1。
- 状态用图形、文字和颜色三重表达。
- 关键结论为 HTML 文本，不放进图片。
- 图表 alt 描述结论及全部类别和值。
- 证据 SHA 使用可断行 monospace，不放入横向滚动容器。
- 手机正文不低于 15px；触摸交互不适用于邮件，因此不设计 hover、按钮状态或弹窗。
- 深色模式使用实色卡片和 media query；客户端强制反色时仍保持结构和文字可读。

## 12. Gmail 与客户端兼容策略

- 核心布局使用 table，`role="presentation"`。
- 关键样式 inline；`<style>` 仅保留 media query 与 dark mode 增强。
- 无 JavaScript、无外部字体、无 SVG 生产依赖。
- PNG 可使用 CID 或 HTTPS 绝对地址；不可使用本地相对路径发送邮件。
- Gmail 对 CSS 变量支持不作为生产前提；生产 HTML 使用已展开的 sRGB 值。
- Outlook Windows 可能忽略圆角、渐变、box-shadow；纯色和边框是必要 fallback。
- Gmail App 可能强制深色反转；发送前需在 Gmail Web、iOS Gmail、Android Gmail 和至少一个 Outlook 客户端测试。

## 13. 禁止事项

- 不改写 AI 教练结论。
- 不删除字段映射中的任何字段。
- 不在主视图突出 SHA、ID 或工程元数据。
- 不生成不存在的分区、阶段、活动或趋势。
- 不展示真实私人数据、GPS、路线、地址、Token、凭据或配置路径。
