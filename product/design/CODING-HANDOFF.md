# TrainLab 邮件模板 Coding 交接

> 更新日期：2026-07-28
> 交付范围：`daily_report`、`weekly_report`、`mail_reply`
> 目标：将当前可预览的 HTML 设计模板接入服务端数据与邮件发送链路。

## 1. 交付结论

当前项目已经完成三类邮件的视觉设计、响应式 HTML 和设计预览入口。Coding 接手后的核心工作不是重新设计页面，而是：

1. 定义并校验三类邮件 payload。
2. 将 payload 绑定到 `data-*` 模板标记。
3. 正确生成重复区块、可选区块与 `running/rest` 变体。
4. 清理设计标记和示例数据，生成最终 HTML 与纯文本正文。
5. 保证主题、正文和 HTML 中不泄露内部运行字段。
6. 完成真实 Gmail、Apple Mail、Outlook、iOS、Android 投递测试。

## 2. 最终文件结构

```text
.
├── index.html
├── trainlab-daily-report-email.html
├── trainlab-weekly-report-email.html
├── trainlab-mail-reply-email.html
├── brand-spec.md
└── CODING-HANDOFF.md
```

| 文件 | 职责 | 是否进入发送链路 |
|---|---|---|
| `index.html` | 设计预览入口，支持模板和桌面/手机宽度切换 | 否 |
| `trainlab-daily-report-email.html` | 每日训练简报模板 | 是 |
| `trainlab-weekly-report-email.html` | 每周训练计划模板 | 是 |
| `trainlab-mail-reply-email.html` | 邮件回复及计划修改建议模板 | 是 |
| `brand-spec.md` | 视觉令牌、字体与设计规则 | 否，供后续扩展参考 |
| `CODING-HANDOFF.md` | 开发接入、字段、规则与验收说明 | 否 |

直接打开 `index.html` 可查看三类模板的最终视觉与移动端重排效果。

## 3. 不可改变的设计约束

- 邮件主体使用 640px 表格骨架。
- 680px 以下切换为移动端单列布局。
- 邮件 HTML 不依赖 JavaScript、远程图片、SVG、外部字体或 CSS 变量才能阅读。
- Outlook 固定宽度回退依赖现有 MSO 条件表格，不要删除。
- 视觉令牌以 `brand-spec.md` 为准：
  - 背景：`#F3F7F8`
  - 表面：`#FBFCFC`
  - 正文：`#142337`
  - 次级文字：`#627184`
  - 边界：`#D8E2E5`
  - 强调色：`#0B7F78`
- 不要把模板改造成多列 Web 页面；邮件客户端兼容优先于现代 CSS 写法。
- 不要把内部调试信息、模型解释或数据血缘放入页脚。

## 4. 推荐渲染架构

```text
业务数据
  ↓
Payload 校验与枚举归一化
  ↓
内部字段递归拦截
  ↓
选择 email_type 对应模板
  ↓
生成 data-repeat 重复区块
  ↓
选择 data-variant 结构
  ↓
删除空的 data-optional 区块
  ↓
替换 data-field 文本
  ↓
清理所有设计/绑定属性
  ↓
生成 subject + text/plain + text/html
  ↓
发送前断言与邮件投递
```

建议在服务端完成渲染。可使用现有模板引擎，也可以用 HTML DOM 解析库实现；不要在邮件客户端执行模板逻辑。

### 4.1 伪代码

```ts
function renderTrainLabEmail(payload: EmailPayload): RenderedEmail {
  validatePayload(payload);
  assertNoForbiddenKeys(payload);

  const document = loadTemplate(payload.email_type);

  renderRepeatedBlocks(document, payload);
  selectStructuralVariants(document, payload);
  removeEmptyOptionalBlocks(document, payload);
  replaceFieldText(document, payload);

  assertRequiredFieldsResolved(document, payload.email_type);
  stripHandoffAttributes(document);

  const subject = buildSafeSubject(payload);
  const html = serialize(document);
  const text = buildPlainText(payload);

  assertNoForbiddenContent({ subject, html, text });
  return { subject, html, text };
}
```

## 5. 模板标记契约

### `data-field`

单值字段。默认使用 `textContent` 写入，禁止直接拼接未转义 HTML。

```html
<h1 data-field="title">每日训练简报</h1>
```

### `data-repeat`

数组字段。由服务端按数据项生成子节点。

```html
<div data-repeat="daily_plans">...</div>
```

当前重复字段：

- 每日：`decision_factors`
- 每周：`key_findings`、`daily_plans`
- 回复：`recommendations`

### `data-optional`

可选区块。对应值为空、空数组或业务条件不成立时，删除整个节点，不要只清空文字。

### `data-variant`

结构变体。每周计划使用：

- `data-variant="running"`
- `data-variant="rest"`

休息日不得保留热身、主训练、冷身、配速或心率区间。

### 最终发送前清理

最终邮件 HTML 应移除：

- `data-field`
- `data-repeat`
- `data-optional`
- `data-variant`
- `data-od-id`

这些属性用于设计交接和服务端渲染，不是用户可见数据。

## 6. Payload 总体结构

```ts
type EmailType = "weekly_report" | "daily_report" | "mail_reply";

interface CommonEmailPayload {
  email_type: EmailType;
  subject?: string;
  preheader: string;
  brand_name: "TrainLab";
  title: string;
  subtitle?: string;
  display_date: string;
  generated_at_local: string;
  footer_note: string;
  data_limitation?: string;
  safety_notice?: string;
}
```

实现时建议使用判别联合：

```ts
type EmailPayload =
  | DailyReportPayload
  | WeeklyReportPayload
  | MailReplyPayload;
```

不要用一个包含全部可选字段的大对象替代判别联合，否则很难保证不同邮件类型的必填规则。

## 7. 每日训练简报

### 7.1 页面结构

```text
邮件头部
状态条
昨日回顾
判断依据（可选/重复）
今日安排
停止条件（可选）
判断说明
数据说明（可选）
页脚
```

### 7.2 目标字段

```ts
interface DailyReportPayload extends CommonEmailPayload {
  email_type: "daily_report";

  summary_date: string;
  advice_date: string;

  overall_state: string;
  decision_factors?: string[];
  activity_evidence:
    | "已确认有活动"
    | "已确认无记录活动"
    | "活动数据不完整"
    | "尚未确认";
  plan_evidence: string;
  data_completeness: "完整" | "部分完整" | "有限";
  daily_summary_text: string;

  activity_kind: "running" | "rest";
  session_title: string;
  course_type?: string;
  hansons_session_role?: string;
  warmup?: string;
  main_work?: string;
  cooldown?: string;
  total_volume?: string;
  planned_duration?: string;
  planned_distance?: string;
  effort_guidance?: string;
  heart_rate_guidance?: string;
  stop_conditions?: string;
  daily_advice_text: string;

  configured_difficulty_level: 1 | 2 | 3 | 4 | 5;
  selected_session_difficulty_level: 1 | 2 | 3 | 4 | 5;
  difficulty_adjustment_reason?: string;
  confidence: "较高" | "一般" | "较低";
  confidence_reason: string;
}
```

### 7.3 当前模板已标记字段

- 状态：`overall_state`、`data_completeness`、`confidence`
- 回顾：`summary_date`、`daily_summary_text`、`decision_factors`
- 课程：`advice_date`、`activity_kind`、`session_title`、`total_volume`、`hansons_session_role`、`effort_guidance`
- 步骤：`warmup`、`main_work`、`cooldown`、`daily_advice_text`
- 判断：`configured_difficulty_level`、`selected_session_difficulty_level`、`difficulty_adjustment_reason`、`confidence_reason`
- 边界：`stop_conditions`、`data_limitation`

### 7.4 Coding 需要补齐

当前视觉模板没有为以下字段提供独立节点：

- `activity_evidence`
- `plan_evidence`
- `course_type`
- `planned_duration`
- `planned_distance`
- `heart_rate_guidance`
- `safety_notice`

建议处理方式：

- `activity_evidence`、`plan_evidence`：加入“判断依据”区。
- `course_type`：加入今日安排的课程元信息。
- `planned_duration`、`planned_distance`：有值时加入训练量行；无值时不渲染。
- `heart_rate_guidance`：仅在区间可靠时加入训练指导，不可靠时删除。
- `safety_notice`：使用独立安全提醒区，不要与普通 `stop_conditions` 混为一个字段。

## 8. 每周训练计划

### 8.1 页面结构

```text
邮件头部
本周总结
负荷 / 恢复 / 进展摘要
关键发现（可选/重复）
计划依据
未来七天（固定 7 项）
本周注意（可选）
数据说明（可选）
页脚
```

### 8.2 日程模型

```ts
type HansonsSessionRole =
  | "easy"
  | "long"
  | "tempo"
  | "speed"
  | "running_strength";

type CourseType =
  | "easy"
  | "long_easy"
  | "steady"
  | "intervals";

interface RunningDayPlan {
  date: string;
  weekday: string;
  activity_kind: "running";
  session_title: string;
  hansons_session_role: HansonsSessionRole;
  course_type: CourseType;
  warmup: string;
  main_work: string;
  cooldown: string;
  planned_duration?: string;
  planned_distance?: string;
  effort_guidance: string;
  heart_rate_guidance?: string;
  rationale: string;
  stop_conditions: string;
  safety_state?: string;
}

interface RestDayPlan {
  date: string;
  weekday: string;
  activity_kind: "rest";
  session_title: string;
  rationale: string;
  recovery_advice: string;
}

type DailyPlan = RunningDayPlan | RestDayPlan;
```

### 8.3 主体模型

```ts
interface WeeklyReportPayload extends CommonEmailPayload {
  email_type: "weekly_report";

  week_start_date: string;
  week_end_date: string;
  review_start_date: string;
  review_end_date: string;

  weekly_summary_text: string;
  overall_state: string;
  key_findings?: string[];
  training_load_summary: string;
  recovery_summary: string;
  progress_summary: string;
  attention_items?: string;

  training_method: "Hansons Marathon Method";
  training_difficulty_level: 1 | 2 | 3 | 4 | 5;
  marathon_goal_time?: string;
  half_marathon_goal_time?: string;
  plan_objective: string;
  plan_constraints: string;
  plan_note: string;

  daily_plans: [
    DailyPlan,
    DailyPlan,
    DailyPlan,
    DailyPlan,
    DailyPlan,
    DailyPlan,
    DailyPlan
  ];
}
```

### 8.4 Coding 需要补齐

当前模板展示了七项示例日程，但并不是可直接循环的单行原型。接入时应由服务端按 `daily_plans` 重新生成七项，并根据 `activity_kind` 选择结构。

当前模板还需要补齐：

- 周总结区的 `overall_state`
- 运行日的 `warmup`、`cooldown`
- `planned_distance`
- `heart_rate_guidance`
- `stop_conditions`
- `safety_state`
- 公共 `safety_notice`

必须断言：

```ts
payload.daily_plans.length === 7
```

## 9. 邮件回复

### 9.1 页面结构

```text
邮件头部
回复上下文
核心回答
计划修改（条件区块）
建议事项（可选/重复）
下一步（可选）
完整回复正文
一般提醒（可选）
安全说明（可选）
数据限制（可选）
页脚
```

### 9.2 Payload

```ts
type RevisionStatus =
  | "等待分析"
  | "已生成修订建议"
  | "需要用户补充信息";

interface MailReplyPayload extends CommonEmailPayload {
  email_type: "mail_reply";

  original_subject: string;
  response_kind: string;
  subject_intent: string;
  requires_thread_reply: boolean;
  reply_date: string;

  reply_text: string;
  answer_summary?: string;
  explanation?: string;
  recommendations?: string[];
  next_steps?: string;
  acknowledgement?: string;
  data_limitations?: string;
  warnings?: string;

  change_kind?:
    | "移动训练"
    | "取消训练"
    | "替换训练"
    | "可用时间变化"
    | "伤病情况"
    | "个人偏好";
  affected_dates?: string[];
  effective_date?: string;
  change_constraints?: string;
  revision_status?: RevisionStatus;

  red_flag: boolean;
  exercise_suspended: boolean;
  safety_note?: string;
}
```

### 9.3 条件规则

- 没有计划修改请求时，删除整个 `change_kind` 区块。
- 存在 `change_kind` 时，`revision_status` 必填。
- `revision_status` 只能使用上述三个值。
- 重新分析完成前，不得显示“修改已经完成”。
- `red_flag === true` 时必须提供 `safety_note`。
- `exercise_suspended === true` 时，回复中必须明确暂停运动建议。

### 9.4 Coding 需要补齐

当前模板没有为以下字段提供独立标记：

- `response_kind`
- `requires_thread_reply`
- `red_flag`
- `exercise_suspended`
- 公共 `safety_notice`

这些字段主要驱动渲染和发送行为，不一定全部显示为正文文字：

- `requires_thread_reply`：决定是否使用原会话的 reply API。
- `red_flag`、`exercise_suspended`：决定安全区块是否出现以及使用的文案强度。
- `response_kind`：用于业务路由，可按需要加入回复上下文。

## 10. 主题与 Preheader

`subject` 属于邮件头，不在正文重复显示。推荐由服务端统一生成，不直接复用包含调试信息的上游字符串。

推荐格式：

```text
[TrainLab] 每日训练简报 · 2026-07-28
[TrainLab] 本周训练计划 · 2026-07-27—2026-08-02
Re: 用户原主题
```

要求：

- 移除 CR/LF，防止邮件头注入。
- 回复主题先清理内部字段，再补 `Re:`。
- `preheader` 必须写入模板顶部隐藏预览文本。
- 主题与 preheader 均不得携带运行编号、哈希或数据血缘。

## 11. 内部字段禁显

以下字段可以存在于内部任务对象，但必须在进入邮件 payload 前移除：

```text
run_id
run_key
artifact_id
response_artifact_id
delivery_run_id
subject_id
message_id
thread_id
revision_id
content_sha256
idempotency_key
```

同样禁止：

- 数据库内部编号
- Gmail 内部编号
- 数据来源血缘编号
- 凭证、Token、密钥
- 配置文件和凭证路径

### Gmail 幂等传输例外

应用渲染完成的 `subject`、`text/plain` 和 `text/html` 仍必须通过上述禁显检查。
由于当前 Gmail MCP 不支持自定义幂等请求头，投递适配器会在发送前向 HTML
追加一个 `display:none` 的传输标记，用于未知发送结果后的唯一搜索与对账。
该标记不得写入主题、纯文本、业务模板、数据库 artifact 或用户可见页脚；适配器
必须拒绝调用方预先注入同一标记，并继续执行歧义、线程与参与者校验。

建议递归扫描对象 key，并在 subject、text、html 上执行发送前二次扫描。

```ts
const FORBIDDEN_KEYS = new Set([
  "run_id",
  "run_key",
  "artifact_id",
  "response_artifact_id",
  "delivery_run_id",
  "subject_id",
  "message_id",
  "thread_id",
  "revision_id",
  "content_sha256",
  "idempotency_key"
]);
```

## 12. 示例内容与转义

模板中的现有文字用于展示设计效果，不是默认业务数据。生产渲染必须做到：

- 所有必填 `data-field` 都由 payload 覆盖。
- 所有可选字段有值则替换，无值则删除区块。
- 不允许示例日期、课程名或说明文字意外进入正式邮件。
- 用户回复、训练说明和 AI 文本默认按纯文本转义。
- 只有经过白名单清洗的可信片段才能作为 HTML 写入。
- 换行可转换为 `<br>`，但不要允许任意标签、脚本或事件属性。

建议在渲染器中记录每个字段的处理状态，若仍存在未处理的绑定标记则发送失败。

## 13. 纯文本与 MIME

发送时生成 `multipart/alternative`：

1. `text/plain; charset=UTF-8`
2. `text/html; charset=UTF-8`

纯文本正文应使用同样的信息顺序，不要简单删除所有 HTML 标签后直接发送。

推荐顺序：

- 标题与日期
- 核心结论
- 训练安排或回复正文
- 判断与数据限制
- 安全提醒
- 页脚

## 14. 邮件客户端兼容要求

| 客户端 | 验收重点 |
|---|---|
| Gmail Web | 隐藏 preheader、间距、圆角、正文宽度 |
| Apple Mail | 系统字体、长文本、颜色和响应式布局 |
| Outlook 桌面 | MSO 固定宽度、表格列宽、边框与内边距 |
| iOS Mail | 390px 下无页面横向滚动、字号可读 |
| Android Gmail | 单列重排、状态区和日期列不挤压 |

不要依赖以下能力：

- JavaScript
- Web Font
- CSS Grid 作为邮件主体布局
- SVG 图标
- 外部图片才能理解核心内容
- 客户端自动深色模式

## 15. 测试清单

### 15.1 单元测试

- [ ] 三种 `email_type` 均能选择正确模板。
- [ ] 未知 `email_type` 直接失败。
- [ ] 必填字段缺失时不发送。
- [ ] 空字符串按空值处理。
- [ ] `daily_plans` 不是 7 项时失败。
- [ ] `activity_kind=rest` 不生成训练步骤。
- [ ] 不可靠心率区间不生成 `heart_rate_guidance`。
- [ ] `red_flag=true` 且无 `safety_note` 时失败。
- [ ] 非法 `revision_status` 时失败。
- [ ] 计划尚未完成分析时不存在“修改已经完成”。
- [ ] 所有用户文本已转义。
- [ ] 最终 HTML 不包含未处理的 `data-*` 绑定标记。
- [ ] subject、text、html 不包含内部字段。

### 15.2 快照测试

每种邮件至少保存以下快照：

- 完整数据
- 最少必填数据
- 数据不完整
- 安全提醒
- 超长中文
- 中英文混排

每周计划额外覆盖：

- 全部跑步日
- 包含休息日
- 目标时间为空
- 部分日程无距离或时长

回复邮件额外覆盖：

- 普通问答
- 等待分析
- 已生成修订建议
- 需要用户补充信息
- 红旗信号并暂停运动

### 15.3 视觉与投递测试

- [ ] 360 / 390 / 430px 无页面横向滚动。
- [ ] 640px 桌面骨架居中。
- [ ] 长主题不会进入正文或破坏头部。
- [ ] 长段落不会溢出容器。
- [ ] 可选区块删除后无空标题或异常间距。
- [ ] Gmail、Apple Mail、Outlook、iOS、Android 完成真实投递。

## 16. 接入顺序

1. 定义判别联合类型与枚举。
2. 实现 payload 校验和内部字段拦截。
3. 先接入 `daily_report`，完成单值、重复和可选区块渲染。
4. 接入 `weekly_report`，实现固定七项和 `running/rest` 变体。
5. 接入 `mail_reply`，实现线程回复、修订状态和安全逻辑。
6. 生成纯文本版本与安全主题。
7. 清理所有绑定属性。
8. 完成快照测试。
9. 完成真实投递测试。

## 17. Definition of Done

满足以下条件后才视为接入完成：

- 三类邮件都由真实 payload 渲染，不再依赖示例文字。
- 所有目标字段均已明确展示、合并或作为渲染条件使用。
- 可选字段为空时不会产生空白模块。
- 每周计划始终为七项，休息日结构正确。
- 邮件回复不会提前声明计划修改完成。
- 心率和安全提醒严格按可靠性与风险状态出现。
- HTML 与纯文本内容一致。
- 内部字段在主题、正文、页脚、注释和属性中均不存在。
- 五类目标邮件客户端已完成真实投递验收。
