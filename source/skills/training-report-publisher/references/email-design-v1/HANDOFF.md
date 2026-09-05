# TrainLab 邮件开发交接

## 1. 交付内容

### 入口与设计稿

- `index.html`：全部设计稿、状态稿和开发文件的预览入口。
- `previews/daily-ready-desktop.html`：日报桌面版，ready＋跑步课程。
- `previews/daily-ready-mobile.html`：日报 375px 手机版。
- `previews/weekly-hold-desktop.html`：周报桌面版，hold＋七日计划。
- `previews/weekly-hold-mobile.html`：周报 375px 手机版。
- `previews/daily-caution.html`：caution＋攀岩课程＋睡眠不完整。
- `previews/daily-blocked.html`：日报 blocked。
- `previews/daily-missing-data.html`：无昨日活动、休息课程、图表不足。
- `previews/weekly-advance.html`：advance。
- `previews/weekly-deload.html`：deload。
- `previews/weekly-blocked.html`：周报 blocked。

### 生产参考模板

- `daily-email.html`
- `weekly-email.html`

两份模板均使用 Gmail 兼容 table 布局、核心 inline CSS、无 JavaScript、无外部字体，并包含模板变量、循环与条件注释。

### 数据与规范

- `daily-sample.json`
- `weekly-sample.json`
- `daily-blocked-sample.json`
- `weekly-blocked-sample.json`
- `FIELD-MAPPING.md`
- `DESIGN-SPEC.md`
- `design-tokens.json`
- `brand-spec.md`
- `trainlab-email-architecture-plan.md`

### 资源

- `assets/icons/`：SVG 设计源与 PNG 2x fallback。
- `assets/charts/`：SVG 图表源与 PNG 2x fallback。
- `assets/illustrations/README.md`：本版不使用装饰插画的原因。

## 2. 如何预览

直接打开 `index.html`，可查看主设计稿、手机画板、关键状态和开发文档。

若浏览器限制本地 iframe，可在项目目录启动静态服务：

```bash
python3 -m http.server 8080
```

然后访问 `http://localhost:8080/`。

生产模板中的 `{{...}}` 是模板变量，不用于直接视觉预览。视觉验收请使用 `previews/`。

## 3. 推荐渲染流程

1. 校验日报或周报 Schema。
2. 丢弃 GPS、路线、私人地址、Token、凭据和内部配置路径。
3. 将原始 payload 转换为邮件 ViewModel。
4. 根据 `status` 和数据存在性选择组件。
5. 基于真实数组生成 PNG 2x、alt 和文字/表格 fallback。
6. 渲染 HTML；不得改写 AI 教练结论。
7. 校验主题与正文顶部标题完全一致。
8. 发送前进行敏感字段、空值和客户端兼容检查。

## 4. 模板变量与 helper

模板使用 Handlebars 风格表达，具体引擎可替换，但语义必须保持。

### 通用变量

- `assets_base_url`：生产时替换为 HTTPS 绝对地址或 CID 资源映射。
- `status`、`schema_version`、`error_code`
- `evidence_refs[]`
- `chart_urls.*`、`chart_alt.*`

### 日报 ViewModel 派生字段

| 字段 | 来源 / 规则 |
|---|---|
| `safety_label` | ready→可以训练；caution→需要谨慎；blocked→报告已阻断 |
| `safety_*_hex` | 来自 `design-tokens.json.status_colors` |
| `activity_label` | running→跑步；climbing→攀岩；rest→休息 |
| `activity_*_hex` | 来自 `activity_colors` |
| `load_label` | low→低负荷；moderate→中负荷；hard→高负荷 |
| `pace_range` | 两端齐全显示 `m:ss–m:ss/km`；单端只显示已知端；休息/攀岩可隐藏 |
| `heart_rate_range` | 两端齐全显示 `min–max bpm`；单端只显示已知端 |
| `yesterday_activity` | 从 `bounded_metrics[]` 中的真实 activity 数据归一化 |
| `sleep` | 从真实 sleep 指标归一化 |
| `recovery` | 从真实 health/recovery 指标归一化 |

### 周报 ViewModel 派生字段

| 字段 | 来源 / 规则 |
|---|---|
| `progression_label` | advance→进阶；hold→维持；deload→减量 |
| `progression_*_hex` | 状态令牌；hold 使用 neutral |
| `progression_dimension_label` | distance→距离；intensity→强度；none→不推进 |
| `distance_change_text` | 前后周值同时存在才计算 |
| `weekly_charts.load[]` | 显式负荷数组；样例来自 `extra_sections[id=weekly-load-series]` |
| `weekly_charts.sleep[]` | 显式睡眠数组；样例来自 `extra_sections[id=weekly-sleep-series]` |
| `text_extra_sections[]` | 排除已消费图表后的扩展文本模块 |
| `weekday` / `month_day` | 由 `training_plan.items[].date` 派生 |
| `target_summary` | 仅拼接真实存在的距离、时长、配速、心率字段 |

### helper

- `inc(index)`：列表序号从 1 开始。
- `join(array, separator)`：原顺序拼接，不改写内容。
- `format_duration(seconds)`：秒转换为 `mm:ss` 或 `h:mm:ss`。
- `signed(value)`：变化值保留正负号；不自动解释好坏。

若现有服务不使用 Handlebars，可在服务端完成 ViewModel 派生后替换模板语法。

## 5. 条件显示

### blocked

```text
status == blocked
→ 显示 BlockedHero(error_code, summary, data_gaps)
→ 隐藏 CourseCard / PlanTimeline
→ 隐藏正常绿色图表与 progression 决策
→ 保留已知事实与 EvidenceFooter
```

blocked 参考：

- `previews/daily-blocked.html`
- `previews/weekly-blocked.html`

### 缺失值

- 关键单值：显示“暂无数据”。
- 非关键单值：隐藏该行。
- 无昨日活动：显示“未获取到昨日活动”，不显示 0 km。
- 睡眠不完整：显示已知时长和完整性；不生成完整阶段图。
- 图表数组为空或不足：隐藏图表，显示已知数值表或“图表数据不足”。
- 攀岩和休息课程不强制显示距离、配速或心率。

### extra_sections

允许的类型：

```text
metric_cards
text
alert
table
line_chart
bar_chart
donut_chart
timeline
custom（仅白名单）
```

未知类型降级为 text 或隐藏。不得直接渲染未清洗 HTML。

## 6. 图表生成

### 输入要求

- 心率分区：`heart_rate_zones[]`
- 睡眠阶段：`sleep_stages[]`
- 活动序列：`activity_series[]`
- 周负荷与睡眠：显式逐日数组

没有数组时不得从平均值、最大值、SHA 或缺失日报推测完整序列。

### 输出要求

每张图同时输出：

1. SVG 设计源。
2. 1248px 宽 PNG 2x。
3. 描述类别和值的 alt。
4. HTML 文字或表格 fallback。

正式邮件图片建议使用 CID；如使用 HTTPS，必须是稳定、受控、允许邮件客户端访问的绝对地址。

## 7. 图片缺失降级

- 图表关键数值在图片下方重复为 HTML 文本或表格。
- 状态图标缺失时，中文状态词仍完整可见。
- TrainLab 标志缺失不影响标题和正文。
- 不使用背景图承载关键内容。
- 不依赖 SVG 发送；SVG 仅保留为设计源。

## 8. Gmail 与客户端限制

- Gmail 支持大部分 inline CSS，但可能过滤部分 `<style>` 规则。
- Gmail App 和部分 Android 客户端可能强制深色反转。
- Outlook Windows 可能忽略圆角、box-shadow、部分背景效果。
- CSS 变量不进入生产模板；颜色已展开为 sRGB 值。
- 表格布局是结构基础，media query 只用于增强移动端重排。
- 长 SHA 使用 `word-break: break-all`，不依赖横向滚动。

建议测试矩阵：

- Gmail Web：Chrome / Safari
- Gmail iOS
- Gmail Android
- Apple Mail iOS / macOS
- Outlook Windows 或 Outlook Web

## 9. 发送前检查

- [ ] 主题与顶部标题完全一致。
- [ ] AI 教练结论、降级规则、停止条件未被改写。
- [ ] blocked 没有正常绿色图表、可执行课程或七日计划。
- [ ] 缺失值未被替换为 0。
- [ ] 图表与真实输入数组一致。
- [ ] 每张图有 alt 和 HTML fallback。
- [ ] 375px 无横向滚动。
- [ ] SHA、ID 只在证据区。
- [ ] 正文无 GPS、路线、私人地址、Token、凭据、配置路径。
- [ ] 示例和测试数据均为匿名合成数据。

## 10. 仍需开发确认

1. AI 教练真实命名空间是 `coach.*` 还是 `ai_coach.*`。
2. `current_week_intensity_score` 的量表名称、范围和精度。
3. `completeness` 的真实类型。
4. `garmin_mapping_status` 的完整枚举和中文映射。
5. 图表生成服务、存储策略与 CID/HTTPS 发送方式。
6. `extra_sections[].custom` 的白名单组件范围。
7. 周报逐日负荷、睡眠、RHR、HRV 是否由上游提供显式数组。
