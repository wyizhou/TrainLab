# 执行计划：M11 v4 内容优先日报、技术周报与固定周计划

- 状态：`cancelled`
- 负责人：主协调 Agent
- Roadmap ID：`M11-0016..M11-0019`
- 阶段/子项目：`M11/email-presentation`
- Batch ID：`serial-m11-v4`
- 返工来源：`docs/exec-plans/completed/M11-email-presentation-0001-readable-cid.md`
- 开始日期：2026-08-24
- 最后更新：2026-09-05

## M12 替代记录

用户批准 FIT-only 每周系统后，本计划尚未完成的 M11-0018/0019 已取消，不继续 r19 模型
调用或 OpenDesign 交接。下方冻结合同、实现记录和失败证据原样保留；取消不等于通过。
后续工作仅由 M12 active plan 和 A-021 管理，旧模型/邮件授权不得继承。

## 目标与验收标准

以 A-018 取代 v2 日报动态改课和压缩周报输入：日报保留健康/恢复分析、昨日全部运动事实和
今日固定课程；周报分析七天全部实际运动与健康、有界 FIT 技术证据和简短计划对比，生成唯一
固定七日计划。由同一 Reader Content Model 生成一致 Markdown 与扁平低保真 HTML；代码门和
独立验证通过后执行一次隔离真实周报 Codex 调用，最终形成 OpenDesign 内容交接包。

完成必须证明：旧 v1/v2/v3 输出、Candidate、邮件与远端证据不变；正式 `source/state` 不变；
Garmin、Gmail、Workout、Sites、cron、MIME 和部署调用均为零；真实模型调用最多一次且不重试；
Git 只包含公开合成内容，私人报告和证据只存在于 owner-only 仓库外 Candidate。

## 范围与非目标

- 范围：A-018、M11 Roadmap/运行说明、版本化证据/AI/课表/Reader Schema，确定性 FIT 技术摘要，
  Prompt、Markdown、低保真 HTML、合成测试、一次真实周报、OpenDesign 内容交接。
- 非目标：OpenDesign 高保真、CID/PNG/MIME、Gmail/SMTP/MCP、Garmin/Workout、Sites、cron、
  `auto.txt` 切换、正式 state 写入、提交、推送、部署。

## 适用规则与参考资料

- 已批准规则：A-001、A-004、A-008～A-010、A-013～A-019。
- 参考：本地 `weekly-fitness-summary` 技术分析边界；Course Coach 的结论先行、全活动清单、
  FIT 技术发现、跑攀联合负荷与下周课表结构。旧报告中的私人数字不进入 Git。

## 冻结验证合同

- 合同版本：`VC-010`
- 合同状态：`frozen`
- 冻结依据：用户已批准的 M11 v4、最终证据闭包、v4-r09、ADHOC-0015 legacy transition、
  v4-r10三状态健康合同、v4-r11结构化目标、v4-r12有限矩阵、VC-006目标模板/故障矩阵，
  2026-08-25明确批准的VC-007模型输入双视图和ASCII-only大小写规则，以及同日批准的
  VC-008结构化VO₂ Max单位精确例外和Host技术限制文案收敛，以及同日批准的
  VC-009仓库外隔离模型工作目录与Codex Git检查命令合同，以及用户于2026-08-25批准的
  v4-r18 Prompt、Schema、Host envelope与字段级心率边界同构修正。
- 冻结时点：2026-08-25；VC-010只约束其后实施与验证，不追溯裁决历史M11 Validator。

### 验收标准

| ID | 必须满足的结果 |
| --- | --- |
| `AC-001` | 日报 D 使用 D-1 全部活动/非睡眠健康、醒来日 D 的睡眠和 D 的固定课程；周报使用精确七份观察，计划覆盖 2026-08-19..25。 |
| `AC-002` | 日报保留健康分析但不调整课程；今日课程逐字绑定已验证周计划 ID/SHA；周报覆盖计划内外全部活动并生成唯一固定七日计划。 |
| `AC-003` | 技术复盘最多三项关键跑步；每条结论的方法、覆盖率、置信度、局限和证据闭合，每个被引用活动分别拥有自己的 available 指标。 |
| `AC-004` | 模型 Context 只接受六类健康、四类技术指标和 `training_goal_v1` 的严格结构，拒绝未声明字段、隐私内容及任何相对/绝对文件路径；Prompt、Context 与权威 Schema 独立绑定。 |
| `AC-005` | r16/r17失败证据永久不可变且不得重试、finalize或转为成功；r18只使用全新Candidate，按公开合成canary最多一次→成功后私人周报最多一次的顺序生成七份日报/一份周报 Markdown 与扁平低保真 HTML。 |
| `AC-006` | Reader 输出遵循冻结顺序、图表上限、单层可见容器和 375/390/430/600/672px 低保真验收，并形成 OpenDesign 内容交接包。 |
| `AC-007` | 每个健康日恰好包含 sleep、RHR、HRV、全天心率、VO₂ Max、体重六项唯一事实；每项严格使用 available、missing、insufficient_data 三状态及其合法 value、单位、日期、原因和 raw 血缘组合。 |
| `AC-008` | Host 按公开 `goal.module.md` 的1个文档标题、5个章节和19个固定字段确定性解析私人 `goal.md`；模型只接收结构化业务值，不接收源 Markdown、标题、路径或未声明字段。 |
| `AC-009` | 仓库外模型工作目录保持owner-only且不属于Git worktree；Codex命令必须精确包含一次`--skip-git-repo-check`，同时保留`--ephemeral`、`--ignore-user-config`、只读沙箱和冻结Schema。 |
| `AC-010` | 模型只输出`weekly_model_decision_v1`；不得输出period、课程日期或Host成功状态。Host从已验证Context确定性注入活动/睡眠/计划周期和`day_1..day_7`对应日期，生成`weekly_ai_result_v4`。 |
| `AC-011` | 模型计划恰好包含`day_1..day_7`七槽位。跑步/攀岩各自必须包含`warmup/main/recovery/cooldown`四个必填步骤对象，休息必须且只能包含`checklist`；Host只按固定顺序组装，不补写课程内容。 |
| `AC-012` | 模型自由文本与计划树不得重复数字BPM或生成心率区间、Z1–Z5、最大心率/阈值/目标BPM处方；Reader只从已验证健康/活动证据确定性展示历史RHR、平均/最高心率、日期与raw血缘。 |
| `AC-013` | 业务Schema是模型结构唯一来源；wire投影只允许删除`$schema`、`$id`、`minLength`、`maxLength`、`minItems`、`maxItems`、`pattern`、`format`、`minimum`、`maximum`十个关键词。业务Schema出现其他wire不支持关键词时投影必须失败；字段、required、variants、enum/const及本地`$ref`拓扑必须同构并由自动parity检查证明。 |
| `AC-014` | Runner固定执行wire校验→Host注入→业务校验→Reader安全校验→不可变落库；保存`wire-result.json`，仅全链成功生成`ai-result.json`。Finalizer只读取Candidate内验证结果，不接受外部结果路径。 |
| `AC-015` | Code Validator PASS后先执行一次公开合成Codex canary；四层校验通过后才执行一次私人周报Codex。两次均不自动重试，canary失败时私人调用数为0。 |

### 行为不变量

| ID | 必须始终成立的行为 |
| --- | --- |
| `INV-001` | 旧 v1/v2/v3 Schema、AI 输出、Candidate、邮件、Gmail/RAW 证据和 SHA 不可修改。 |
| `INV-002` | 周报只消费七份版本化每日观察和最多四份历史周总结，不重新读取 raw；日报/周报证据必须闭合全部实际活动。 |
| `INV-003` | 不从心率采样重新划区、推算阈值/目标 BPM 或用分区时长计算训练负荷；不把健康和表现相关性写成因果。 |
| `INV-004` | 不删除、skip/xfail、降低测试或改变正确预期来取得 PASS；模型失败不自动重试。 |
| `INV-005` | 正式 `source/state` 不变；Garmin、Gmail、Workout、Sites、cron 和其他外部动作调用均为零。 |
| `INV-006` | `--skip-git-repo-check`只用于已隔离的非Git模型工作目录，不改变只读沙箱、输入隐私前检、Schema绑定、Provider边界或外部动作授权。 |
| `INV-007` | r16/r17 Candidate、Prompt、Schema、回执、stdout/stderr和失败SHA永久不可变；旧v1–v3 Schema与输出不得被v4新合同覆盖或静默消费。 |

### 威胁模型

| ID | 范围内风险 |
| --- | --- |
| `TM-001` | Candidate 内 Prompt、Context、manifest 或复制 Schema 被修改，试图绕过权威 Schema、规范 Prompt 或隐私前检。 |
| `TM-002` | Context 含邮箱、Token、凭据、GPS/经纬度、活动名称、相对/绝对路径、文件名、未知字段或错误 status/value 组合；仅普通 `跑步/攀岩`、`RHR/HRV`、`min/km`，以及 Schema 验证后 `max_metrics:vo2_max` available 事实的 `unit`/`value.unit` 精确值 `ml/kg/min` 可保留斜线。 |
| `TM-003` | 一条技术结论复用其他活动证据、引用不可用指标、重复 activity_ref，或 AI 置信度高于 Host 证据最低置信度。 |
| `TM-004` | 周证据漏掉计划外活动、跨日期取数、重新读取 raw，或将计划/实际匹配作为过滤条件。 |
| `TM-005` | Runner 在 pending 前未重新验证 Context/Prompt/Schema，或失败/重放增加模型或外部调用。 |
| `TM-006` | Candidate隔离目录不是Git worktree时，Runner遗漏或重复`--skip-git-repo-check`，或因跳过Git检查而放宽沙箱、Schema或输入边界。 |
| `TM-007` | 模型夹带period/date/status、遗漏课程槽位/必需步骤、使用错误course variant，或wire/business拓扑漂移后仍进入Host组装。 |
| `TM-008` | 历史BPM事实被误当训练处方，或未经证据绑定的BPM数值通过Reader显示；训练计划/未来行动文字出现BPM、心率区间或Z1–Z5。 |
| `TM-009` | Finalizer读取Candidate外结果、失败后自动重试、canary未闭合即运行私人模型，或成功重放增加模型/SQLite/外部调用。 |

### 明确排除项

| ID | 不属于当前交付的场景 |
| --- | --- |
| `EX-001` | 新的高保真 OpenDesign、CID/MIME、邮件投递、Garmin Workout、Sites、cron、部署、提交或推送。 |
| `EX-002` | root、内核、硬件、恶意同 UID 进程或冻结合同未授权的新攻击模型。 |
| `EX-003` | 更改日期、真实数据范围、训练规则或A-018正确预期；VC-010仅新增公开合成canary 1次和私人周报1次授权，禁止任何自动重试或第三次调用。 |
| `EX-004` | 本 legacy transition 自身不追溯裁决历史 Validator 正误；该归因属于后续 Failure Analyst。 |

### Lint/Test 与静态门禁

| ID | 命令或检查 | 预期结果 |
| --- | --- | --- |
| `GATE-001` | `pytest tests/code` | 全部既有和新增测试通过，无 skip/xfail 增量 |
| `GATE-002` | Ruff check/format-check、mypy、只读 AST/compile | 全部通过 |
| `GATE-003` | 全部 JSON Schema、Skill metadata、AI 布局、Markdown、权限、隐私、Git ignore、`git diff --check` | 全部通过 |
| `GATE-004` | 模型输入前检、Schema parity、Host envelope、逐活动证据、字段级心率边界、VC-009命令合同及零调用重放 | 全部通过 |
| `GATE-005` | 全新 Code、AI/Coaching、Information Architecture、Data/Privacy Validator | 适用阶段全部 `PASS` |

### 合同修订记录

| 版本 | 状态 | 变更、理由与受影响标准 | 人工批准依据 |
| --- | --- | --- | --- |
| `VC-001` | `superseded` | 将既有 M11 v4/r09 范围映射为 v0.4.4 合同；Failure Analyst 后续确认六类健康缺失状态语义不足 | 用户批准 v4-r10 后升级为 VC-002 |
| `VC-002` | `frozen` | 保留 VC-001 全部业务目标；新增六类健康三状态矩阵、逐活动规范证据身份和合法中文斜线样例 | 用户于 2026-08-24 明确选择三状态并批准 v4-r10 |
| `VC-003` | `frozen` | 保留VC-002全部日期、健康、技术和训练目标；以结构化 `training_goal_v1` 与 Context v2 替代整份 `goal.md` 自由字符串，并禁止模型输入含任何文件路径 | 用户于2026-08-24批准v4-r11完整执行计划；Failure Analyst确认F04为IMPLEMENTATION_DEFECT且safe_auto_fix=true |
| `VC-004` | `superseded` | 继承VC-003；源目标强度接受精确整数或`N/5，非空说明`且只输出整数N；有限矩阵和Prompt权威SHA仍有词法/门禁基线歧义 | 用户批准VC-005后替代 |
| `VC-005` | `superseded` | 继承VC-004全部业务目标；把强度Unicode计数、邮箱/秘密/GPS/路径/文件名词法、Prompt字节拓扑和703节点测试基线写成机器规则；章节、活动标签、坐标/Unicode邮箱、故障点及节点规范化仍有歧义 | 用户批准VC-006后替代 |
| `VC-006` | `superseded` | 继承VC-005全部业务目标；逐字冻结目标模板、有限隐私词法、VC-006故障注入点和703节点规范化算法；未逐类定义NFKC与raw视图优先级 | 用户批准VC-007后替代 |
| `VC-007` | `superseded` | 继承VC-006全部业务目标；逐检测器冻结raw/NFKC双视图、ASCII-only大小写、Unicode空白advisory矩阵及757节点基线；未允许Schema强制要求的VO₂ Max单位 | 用户批准VC-008后替代 |
| `VC-008` | `superseded` | 继承VC-007全部业务目标；仅在严格Schema验证后允许`max_metrics:vo2_max`且`status=available`事实的`unit`与`value.unit`同时为精确`ml/kg/min`；Host固定限制改为“不得用整场均值、速度或心率替代”；其余斜杠规则不变 | 用户批准VC-009后替代 |
| `VC-009` | `superseded` | 继承VC-008全部业务目标；仓库外owner-only模型工作目录保持非Git隔离，Runner命令精确增加一次`--skip-git-repo-check`并绑定intent，不改只读沙箱、输入、Schema或外部边界；r16不重试，r17全新Candidate最多一次调用 | 用户批准VC-010后替代；r17失败证据保持不可变 |
| `VC-010` | `frozen` | 继承VC-009全部日期、隐私、证据、命令和零外部动作边界；模型仅输出决策，Host注入period/date/status；七槽位和三类课程使用强结构；历史BPM由Reader从证据展示；business→wire确定性投影并强制parity；新增公开canary 1次和私人周报1次且均不重试 | 用户于2026-08-25明确批准“M11 v4-r18：Prompt、Schema 与业务校验同构修正”完整计划 |

### VC-002 健康状态矩阵

每个 health day 的 `health_facts` 必须恰好含以下六个唯一 `metric_code`：
`sleep:main_sleep`、`rhr:resting_heart_rate`、`hrv:hrv`、
`heart_rates:heart_rate`、`max_metrics:vo2_max`、`weigh_ins:weight`。

| 状态 | value / 单位 / 日期 | raw 血缘 | 原因码 |
| --- | --- | --- | --- |
| `available` | value 必须匹配该 metric 的既有严格结构；单位相容；睡眠醒来日为 D，其余精确指标为 D-1；VO₂ Max/体重不得晚于 D-1 | `raw_refs` 恰好包含被选中的完整 raw ID/SHA | 原因为 `null` |
| `missing` | value、单位和 observed date 为 `null` | `raw_refs=[]` | 精确日期指标只可 `not_found`；VO₂ Max/体重可为 `not_found` 或 `outside_lookback` |
| `insufficient_data` | value、单位和 observed date 为 `null` | `raw_refs` 至少一项并覆盖导致不可用的已登记 raw | `parse_error`、`incomplete`、`date_mismatch`、`unit_invalid` 或 `conflicting_records` |

VO₂ Max 选择截至 D-1 最近 30 个日历日内的最新有效值，体重选择最近 14 个日历日；
`exact_date` 的 age 为 0，`latest_prior` 分别不得超过 30/14。`health_inventory.complete=true`
表示独立查询已闭合且六种状态全部写出，不表示六项都 available。状态本身不改变既有日报阻断和
安全规则。

### VC-003 结构化训练目标合同

Host 只读取与公开模板同形的私人 `goal.md`，不得修改该文件。输入必须恰好包含6个模板章节、
19个唯一标签且没有其他非空行；缺失、重复、未知标签或强度值不是1–5时，在Context/pending前
以稳定错误阻断。当前私人文件已只读确认结构与模板一致，未输出或保存私人字段内容。

`training_goal_v1` 固定为以下结构：

- `current_goal`：比赛目标与日期、当前训练重点、长期跑量/频率/长跑规则；
- `weekly_availability`：周一至周日七个固定字段；
- `training_preferences`：强度偏好整数1–5、进阶规则、硬负荷规则、漏课/距离强度规则；
- `constraints`：已知限制、恢复信号、红旗处理偏好；
- `temporary_adjustment`：临时调整及有效周期。

除强度整数外，值必须为非空有界字符串；模板中的“无”作为显式业务值保留。Host只把规范化
对象写入 `m11_v4_weekly_model_context_v2`。`goal.md` 原字节、Markdown标题、字段标签之外的文本、
源路径和内部Candidate路径不得进入Prompt/Context。项目资源以 `source/` 为运行根解析；Host可在
系统调用边界解析私有绝对路径，但只能存在于控制层，不能硬编码或进入模型输入。

所有Context字符串先按NFKC规范化；仅精确业务词 `跑步/攀岩`、`RHR/HRV`、`min/km` 可含斜线，
其余 `/`、`\\`、盘符、UNC、`../`、相对路径和常见文件名后缀一律拒绝。失败时模型调用0、无
pending。旧Context v1 Schema与历史失败证据原字节保留；新的r11 Candidate只接受Context v2。

### VC-004 有限输入矩阵

VC-004继承的固定日期逐字为：活动`2026-08-11..2026-08-17`、睡眠醒来日
`2026-08-12..2026-08-18`、下周计划`2026-08-19..2026-08-25`。四类技术指标逐字为
`provider_hr_zone_duration_v1`、`explicit_work_lap_stability_v1`、
`aerobic_decoupling_power_hr_v1`、`running_dynamics_front_back_v1`。“只接受六类健康和四类技术”
只约束嵌套证据类别，不删除Context根部的日期、活动事实、inventory/lineage、覆盖率和计划字段。

目标解析以“章节→有序字段”状态机执行；字段必须位于对应章节并保持模板顺序。强度只接受
NFKC后的精确`N`或`N/5,非空说明`、`N/5;非空说明`（N为1..5，说明1..200字符）；后一种
只保留整数N，说明不保存且不进入Context。`3.5`、`3x`、裸`3/5`、越界值、字段错置或乱序
均阻断。

共享Context前检在VC-003基础上固定增加：Bearer/Authorization秘密、`活动名称：`/
`activity_name`/`activity name`、合法范围十进制经纬度对；固定文件名`README`、`Dockerfile`、
`Makefile`、`CMakeLists.txt`、`pyproject.toml`、`requirements.txt`、`.env`、`goal.md`、`email.json`；
固定后缀`.md/.json/.fit/.gpx/.tcx/.sqlite/.db/.toml/.yaml/.yml/.txt/.env/.ini/.cfg/.conf/.pem/.key`。
上述集合是本批次完整阻塞矩阵，新增类别只能进入advisory或范围变更候选。

有限矩阵词法逐字为：大小写不敏感的`Bearer`加至少一个空白和非空值；`Authorization`后接
`:`或`=`及非空值；`活动名称`后接`：/:/=`，或`activity_name`/`activity name`后接`:`/`=`；
十进制坐标必须是逗号分隔的`纬度,经度`，纬度-90..90、经度-180..180，二者各含4..8位小数。
广义隐私/文件名说明与本有限矩阵冲突时，以本矩阵为唯一阻塞标准。

`weekly-content-v4-v2.txt`以当前SHA `15828d08b13876b183cc6091e960da9395d89ad788ba08c1c331c4b49ce4dab5`
只绑定模板原字节，作为权威Prompt根。Builder只能从权威合同取得模板路径/SHA；manifest分别
记录权威模板SHA、Context SHA、最终Prompt SHA和Schema SHA。最终Prompt固定为模板原字节、一个
换行、`canonical_json(Context)`、一个换行。Runner在pending前独立复验以上各项；模板、规范
Prompt与manifest即使同步漂移，也必须阻断并保持模型调用0。

VC-004代码门逐字为：`pytest tests/code -q`不少于703项且无新增skip/xfail；
`ruff --config skills/_shared/ruff.toml check skills tests/code`；
`ruff format --check skills tests/code`；
`mypy --config-file skills/_shared/mypy.ini skills tests/code`；只读AST/compile；全部JSON Schema；
Skill metadata、`tests/ai`布局、Markdown链接、owner/mode、隐私、Git ignore、根`git diff --check`；
正式state指纹保持`7cc9f67d5e31c4aa16d5fa2eaacdf3b20b7f2f5515a093d9623db32f35030f43`，
模型、Provider与外部动作调用均为0。

### VC-005 机器词法与基线

目标每行先NFKC再strip；强度只匹配`^[1-5]$`或
`^([1-5])/5[,;][ \t]*(\S(?:.*\S)?)$`。说明按Unicode code point计数1..200；换行、纯空白、
裸`N/5`无效，只输出整数N，说明不保存、不进入Context。

字段名先NFKC、小写并移除非ASCII字母数字；包含`latitude/longitude/gps/activityname/email/token/
credential/password/clientsecret`任一片段即阻断。字符串阻断规则仅为：ASCII邮箱
`[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,63}`（忽略大小写）；
`token/password/credential/client[ _-]?secret`后接`:`/`=`和非空值；Bearer加空白和非空值；
Authorization后接`:`/`=`和非空值；独立ASCII词`GPS`；VC-004活动名称标签和十进制坐标对。
替换`跑步/攀岩`、`RHR/HRV`、`min/km`后，剩余任意`/`或反斜线均阻断。VC-004固定文件名/
后缀保持不变。Unicode邮箱、孤立`token`、`foo.py`及矩阵外类别只能advisory。

Prompt模板SHA仍为`15828d08b13876b183cc6091e960da9395d89ad788ba08c1c331c4b49ce4dab5`；
最终字节精确为`template_bytes + b"\n" + canonical_json(context).encode() + b"\n"`。模板自身
已有结尾LF，双LF属于冻结合同。

实施前基线固定为703个pytest节点；原collect输出去除摘要后的SHA为
`b77b1c92f39d5478725065783237477d5d43396c9d708874bd40750ccf130648`（含一个空行），去除空行后的
规范节点清单SHA为`56a354474bbbbf055f72ad42968778b5455353cdcbee12173a10313d698f16f8`；skip/xfail标记0、
Python文件99、JSON Schema 78、Skill metadata 6、Markdown 80。实施后原703节点必须为新节点集合
子集；检查目标精确使用`source/skills/**/*.py`、`source/tests/code/**/*.py`、
`source/skills/_shared/schemas/*.schema.json`、`source/skills/*/SKILL.md`、根Markdown及
`docs/**/*.md`/`source/**/*.md`。正式state指纹和VC-004完整命令保持不变。
owner-only基线位于`/private/tmp/trainlab-m11-vc005-baseline.pb9cUV/`，目录0700、文件0600；
仅含公开测试节点名称，不含私人健康数据。

### VC-006 目标模板、有限词法与故障门

`source/goal.module.md`权威SHA固定为
`362c6dba4a7b0f3668da8a2d8c37e6325efe5498845b77f3f1002b8eb56be136`。NFKC后必须依次出现：

1. 文档标题`# 我的训练目标`；
2. 章节`## 当前目标`，字段`比赛目标与日期`、`当前训练重点`、`周跑量、跑步频率和长跑距离的长期规则`；
3. 章节`## 每周可训练安排`，字段`周一`至`周日`；
4. 章节`## 训练偏好`，字段`训练强度偏好`、`进阶方式`、`硬负荷上限与最小间隔`、
   `错过课程与距离/强度调整规则`；
5. 章节`## 身体限制与恢复关注`，字段`已知伤病、疼痛或其他限制`、`需要特别关注的恢复信号`、
   `出现红旗时的处理偏好`；
6. 章节`## 临时要求`，字段`当前长期目标之外的临时调整`、`临时调整的有效周期`。

以上是1个文档标题、5个章节和19个字段；旧称“力量训练经验”只表示现有`训练强度偏好`，不得
新增字段。每行先NFKC再strip。强度只匹配`^[1-5]$`或
`^([1-5])/5[,;][ \t]*(\S(?:.*\S)?)$`；说明1..200个Unicode code point且不得换行或全空白。
序列化只保留整数N，说明丢弃且不得进入Context/Prompt/报告。私人`goal.md`只读验证，不得修改。

有限隐私阻断矩阵在VC-005基础上逐字澄清：

- 活动名称标签仅为`activity_name`、`activity name`、`activity-name`、`activityName`、`活动名称`、
  `活动名`；NFKC后标签接`:`、`：`或`=`及非空值时阻断；dict key仍按VC-005归一化片段规则阻断。
- 经纬度只匹配纬度在前、经度在后的成对十进制数；可带正负号，使用`,`或`;`分隔并允许ASCII
  空白，两者各含4..8位小数，纬度范围-90..90、经度范围-180..180，数值两侧不得紧邻数字或`.`。
- ASCII邮箱按VC-005正则匹配；若匹配片段左右任一侧紧邻Unicode字母或数字，则该命中不阻断，
  因此`éfoo@example.com`属于advisory。普通独立ASCII邮箱继续阻断。
- VC-005秘密、Bearer、Authorization、独立ASCII词GPS、固定文件名/后缀规则继续生效；精确替换
  `跑步/攀岩`、`RHR/HRV`、`min/km`后，剩余任意`/`或`\\`阻断。矩阵外词法只可advisory。

Prompt模板SHA和最终字节公式沿用VC-005。VC-006新增故障注入范围只包含：Goal、Context、Prompt
模板、Schema、manifest的读取/解析/哈希，以及pending intent临时创建、写入、fsync、同文件系统
原子改名。输入前检失败必须模型调用0且无pending；pending持久化失败必须模型调用0，临时文件
不得被下游采用。既有子进程启动、stdin、超时、终止和结果落盘测试继续保留，但本批次不新增
进程威胁要求。

703节点规范清单固定算法：在`source/`执行`pytest tests/code --collect-only -q`；仅保留以
`tests/code/`开头且含`::`的行；保持pytest发射顺序，不排序；UTF-8编码、每行一个节点、无空行，
末尾恰好一个LF。该清单SHA为
`56a354474bbbbf055f72ad42968778b5455353cdcbee12173a10313d698f16f8`。实施后允许新增节点，但原
703个节点必须全部存在。静态不得存在`pytest.mark.skip/skipif/xfail`，完整结果不得出现
skipped/xfailed/xpassed。其余GATE沿用VC-005。

### VC-007 模型输入双视图合同

结构名称与业务文本分离处理：Context dict key继续先NFKC、小写并移除非ASCII字母数字；Goal标题、
章节、字段和强度继续按VC-006整行NFKC解析。除此之外，隐私检测器接收Context中实际存储的原始
字符串，不再对整串执行NFKC。

| 检测器 | 固定输入视图与大小写语义 |
| --- | --- |
| ASCII email及Unicode邻接 | raw；邮箱正则保持ASCII；左右邻接仍以原始Unicode `isalnum()`判断 |
| secret assignment、Bearer、Authorization、独立GPS | raw；仅ASCII A-Z大小写等价；既有`\\s`空白语义不变 |
| activity label | 只对原始分隔符前的候选标签做NFKC及ASCII大小写；原始分隔符仅`:`、`：`、`=`，值按raw检查非空 |
| coordinate | raw；仅ASCII数字/点/`,`/`;`和SP/HT/LF/VT/FF/CR，既有范围、小数位和边界不变 |
| fixed filename/suffix | raw；仅ASCII A-Z大小写等价；不得使用Unicode casefold扩大命中 |
| slash/path | raw；精确替换`跑步/攀岩`、`RHR/HRV`、`min/km`后检查剩余ASCII`/`或`\\` |

本节中的raw是“进入Context验证器时实际存储的Unicode code point序列”；已经由Goal Parser按
VC-006明确规范化的值不回溯原Markdown。ASCII大小写等价固定为只把`U+0041..U+005A`映射到
`U+0061..U+007A`，其他code point原样保留。activity label逐个扫描raw中的`:`、`：`、`=`：
分隔符后经现有Unicode空白`lstrip`必须非空；分隔符前经`rstrip`、NFKC和上述ASCII映射后，必须
以六个冻结标签之一结尾。分隔符本身及值不得NFKC。

`U+00A0`、`U+2000..U+200A`、`U+202F`、`U+205F`、`U+3000`等会被NFKC折叠为SP的
15种Unicode空白，在坐标检测中只能advisory。全角邮箱、全角secret/GPS、全角文件名/后缀、
全角斜杠、全角坐标数字/逗号以及Unicode兼容大小写也只能advisory；但原始字符串中仍存在冻结
ASCII敏感片段时继续阻断，例如`Ⓐtoken:x`、`ⒶBearer x`、`ⒶGPS`和`ｍｉｎ/km`。

Builder和Runner必须调用同一共享验证器。阻断时fake模型调用0且无pending/final attempt；
advisory样例必须允许进入一次fake模型调用。Schema、错误码、Prompt、Goal模板、公开接口和模型
状态机不变。实施前现有757节点的规范清单SHA为
`669db17d73f8625effc29f2031bf479bdb9fa489cebe9abbed92788e191d8fa5`；原703节点及SHA
`56a354474bbbbf055f72ad42968778b5455353cdcbee12173a10313d698f16f8`继续保留。

### VC-008 结构化斜杠例外

Context必须先通过权威`m11_v4_weekly_model_context_v2` Schema、字段白名单和类型验证，再执行
共享隐私检查。仅当一个健康事实同时满足`metric_code=max_metrics:vo2_max`、`status=available`、
顶层`unit`与`value.unit`均为原始精确字符串`ml/kg/min`时，验证器可以在这两个结构化字段中临时
移除该词元后继续执行VC-007斜杠/路径检查。错误metric、错误status、仅一处匹配、单位不一致、
变形值、附加后缀、未知字段或普通文本中的同一词元一律不得豁免。

Host技术限制固定文字由`不得用整场均值或速度/心率替代`改为
`不得用整场均值、速度或心率替代`；语义、指标、证据、Prompt模板和业务Schema不变。任何其他
技术限制文字中的`/`或`\\`继续按VC-007阻断。Builder和Runner仍只调用同一共享验证器；拒绝时
模型调用0且无pending/final，合法输入的fake模型恰好调用一次。

实施前r16工作树共有860个pytest节点，owner-only规范清单位于
`/private/tmp/trainlab-m11-vc008-baseline.AQL8Pc/nodes.txt`，SHA为
`081da17858e6f92cc05e858969acb147dc521c270a08edec54b0b568ca74937c`；它包含r15的857项与F06A/B
新增的3项SQLite回归。原703/757节点及其冻结SHA继续保持，禁止删除、弱化、skip或xfail。

### VC-009 仓库外模型工作目录命令合同

r16保证了模型输入不直接读取Candidate，因此`ai_work_root`故意位于仓库外、Candidate外，
权限为owner-only，且不是Git worktree。Codex CLI 0.147.0对该合法隔离目录默认执行Git信任
检查；Runner必须在原命令中精确加入一次`--skip-git-repo-check`。intent的
`command_contract.skip_git_repo_check` 必须为`true`，并继续绑定`ephemeral=true`、
`ignore_user_config=true`、`sandbox=read-only`和权威输出Schema。

该参数只表示“已知当前隔离目录不是Git仓库，继续执行已冻结的只读模型任务”，不允许
改变Context/Prompt/Schema/Goal、沙箱、权限、Provider或external action边界。r16失败目录
与回执永久保留，不重放；r17必须从已验证父Candidate建立全新owner-only Candidate，
完整门和全新只读Code Validator PASS后才可使用用户新授权的一次调用，失败不自动重试。

### VC-010 Prompt、Schema 与业务校验同构合同

正式 Failure Analyst 将 r17 的8项业务错误归因为 `M11-V4-F07A/B/C`：Prompt/wire未约束
period机器格式、steps数组未表达必需阶段集合，以及全局BPM扫描误伤历史健康事实。诊断未发现
不同根因或环境故障；r16/r17失败终态永久保留，VC-010使用全新版本和全新Candidate。

模型输出固定为`weekly_model_decision_v1`，不得含`period`、任何`date`或Host运行`status`。
训练计划为`day_1..day_7`七个必填槽位；running/climbing的`steps`是
`warmup/main/recovery/cooldown`四个必填对象，rest的`steps`只有`checklist`。Host按Context中
已经验证的活动/睡眠周期和`next_plan_dates`建立`weekly_ai_result_v4`，不补写模型课程内容。

`weekly_model_decision_v1.schema.json`是唯一结构来源，
`weekly_model_decision_v1_codex.schema.json`只能由确定性投影生成；投影只剥离
`$schema`、`$id`、`minLength`、`maxLength`、`minItems`、`maxItems`、`pattern`、`format`、
`minimum`、`maximum`十个关键词；遇到其他wire不支持关键词必须失败，且不能改变properties、
required、anyOf variants、enum/const或本地`$ref`拓扑。Prompt明确列出相同
槽位、课程variants、步骤和禁用字段，自动parity测试负责防止三层再次漂移。

模型自由文本不重复任何数字BPM；课程、技术结论的未来行动和计划含义继续禁止目标BPM、心率
区间、Z1–Z5、最大心率或阈值推算。`weekly_reader_content_v2`仅从已验证`health_days`和
`all_activities`类型字段确定性显示历史RHR、活动平均/最高心率、日期及raw血缘；设备分区事实
仍须具备对应Host技术证据。

Candidate、attempt intent和receipt升级为v3并绑定Prompt、Context、business/wire Schema、
Host assembler和Reader合同SHA。Runner必须保存`wire-result.json`，随后完成Host envelope、
业务和Reader安全校验；只有全部通过才保存`ai-result.json`。Finalizer取消外部`--ai-result`
入口，只能读取Candidate内已验证结果。公开合成canary和私人周报各最多一次，无自动重试。

## 依赖与隔离

- 显式依赖：M11-0015 completed；M11 v3 r06 与 live r01 历史证据保持不可变。
- 共享接口和冻结依据：A-018；固定日报 D/D-1 日期语义；真实窗口复用日报 2026-08-12..18，
  活动覆盖 2026-08-11..17，睡眠醒来覆盖 2026-08-12..18，计划覆盖 2026-08-19..25。
- 任务分支/Worktree/集成分支：不适用——用户禁止提交且阶段严格串行，沿用当前受保护工作树。
- 允许写入：治理文档、`source/skills` v4 版本化代码/Schema、`source/tests/code`、
  `source/tests/ai` 公开合成材料、仓库外 owner-only v4 Candidate。
- 禁止写入：正式 `source/state`、旧 Candidate、`goal.md`、凭据、Token、邮箱配置、历史输出，
  OpenDesign 外部设计目录、Git index/commit/remote。

## 功能与测试映射

| 功能 | Feature slug | 测试目录 | 必须满足的行为 |
| --- | --- | --- | --- |
| 每日完整观察证据 | `daily-completed-observation-v1` | `source/tests/code/{unit,contract}` | 多活动/计划外活动、inventory/raw/SHA、日期与缺失闭合 |
| FIT 技术摘要 | `activity-technical-evidence-v1` | `source/tests/code/{unit,contract}` | 圈段/覆盖/方法/置信度；分区只读；不合资格为not_applicable |
| v4 日报健康与固定课程 | `daily-health-analysis-v3` | `source/tests/code/{contract,integration}` | 无adjustment/effective/替代课；计划ID/SHA原样引用；红旗独立 |
| v4 周证据与AI结果 | `weekly-training-evidence-v2` | `source/tests/code/{unit,contract,integration}` | 七日全部活动/健康、简短计划对比、最多三项技术复盘、固定课表 |
| Reader Markdown/HTML | `reader-content-v1` | `source/tests/code/{contract,integration}` | 同源同序同字；2/3图上限；单层容器；五视口和状态分支 |
| AI语义验收 | `m11-v4-content` | `source/tests/ai` | 日报无运动建议；周报不漏计划外活动、不编造、计划有SOS和备注 |

## 工具采用情况

- Python 3.11、pytest、Ruff、mypy、JSON Schema、Markdown/HTML 静态与隐私检查。
- 完整门：`cd source && PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/code -q`；Ruff check/
  format-check；mypy；只读 compile/AST；全部 Schema；Skill metadata；Markdown 链接；权限、
  Git ignore、tracked-private、布局和根 `git diff --check`。

## Subagent 派发

| Attempt | Agent 角色/任务 ID | 风险与复杂度 | 模型档位 | 推理档位 | 选档理由 | 平台支持 | 写入边界 | 产物与门禁 | 结果 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Contract Validator / M11-0016 | 高：规则替代、日期、训练与安全边界 | high | high | 实现前必须冻结无冲突合同 | available | 只读 | A-018/AGENTS/Skills/plan 一致性 | 首轮FAIL保留；全新终验 PASS |
| 2 | Code Validator / M11-0017..18 | 高：FIT、Schema、旧版本兼容和一次真实调用前门 | high | high | 跨模块与私人数据边界 | available | 只读 | 完整代码门、合成Candidate、Provider=0 | FAIL：发现5项冻结范围内闭包缺口，真实调用未开始 |
| 3 | Final Code Validator / M11-0017..18 | 高：集中修正后的完整终验 | high | high | 首轮FAIL后只允许一个集中修正批次和全新终验 | available | 只读 | 独立inventory、技术排除、AI引用、课程lineage、模型隔离 | FAIL：启动前隐私复验及逐活动技术证据绑定仍有2项缺口 |
| 4 | Closure Code Validator / M11-0017..18 | 高：用户批准的两项最终闭包终验 | high | high | 只验收启动前隐私复验与逐活动技术证据绑定，PASS前禁止真实调用 | available | 只读 | 完整代码门、两项闭包、旧版本隔离、模型调用仍为0 | FAIL：逐活动绑定PASS；任意绝对路径、开放value子字段及Schema同步漂移仍可在启动前绕过 |
| 5 | r09 Closure Code Validator / M11-0017..18 | 高：最终输入边界、严格Schema与独立权威绑定 | high | high | 用户批准一次性关闭三项已知绕过，PASS前禁止真实调用 | available | 只读 | 绝对路径、开放value、Candidate Schema漂移及完整门 | FAIL：跨活动证据复用、健康status/value合同缺失、普通中文路径误判；模型调用0 |
| 6 | AI/Coaching Content Validator / M11-0018 | 高：真实周报语义、技术置信度与课表 | high | high | 真实健康/训练内容高风险 | available | 只读 | 日报/周报内容与A-018 | pending |
| 7 | Information Architecture Validator / M11-0018 | 中高：双格式、层级和多视口 | high | medium | 内容结构独立验收 | available | 只读 | MD/HTML一致、读时、单层容器 | pending |
| 8 | Data/Privacy Validator / M11-0019 | 高：私人Candidate、正式state和模型输入 | high | high | 最终隐私与边界验收 | available | 只读 | SHA/权限/manifest/零越界调用 | pending |
| 9 | Failure Analyst / M11-v4 diagnosis | 高：多轮实现与验证未收敛 | high | high | A-019 要求先区分实现、合同和历史验证问题 | available | 只读 | F01/F02/F03 固定诊断输出 | completed：F01实现缺陷；F02拆分为路径实现缺陷与健康合同歧义；F03历史责任不追溯 |
| 10 | Contract Validator / M11-v4-r10 VC-002 | 高：健康三状态、证据身份和路径合法样例 | high | high | 合同升级必须先独立确认一致性 | available | 只读 | 仅 VC-002、A-018/A-019 与当前仓库事实 | PASS：合同完整、无冲突、无 blocker |
| 11 | Closure Code Validator / M11-v4-r10 VC-002 | 高：三状态、逐活动身份、输入前检与权威绑定 | high | high | 真实模型前的最终代码门；不得接收历史 Validator 结论 | available | 只读 | 仅 VC-002、A-018/A-019、适用规则与当前结果 | FAIL：中文紧邻的 POSIX 绝对路径漏检，可在 pending 前进入 fake 模型调用；其余代码门PASS |
| 12 | Failure Analyst / M11-v4-r11 path boundary | 高：区分单点实现缺陷与自由文本接口设计缺陷 | high | high | 当前已进入A-019诊断门，实施前必须独立归因 | available | 只读 | B-001、VC-002、当前Context/Builder/Runner与失败证据 | completed：M11-V4-F04=IMPLEMENTATION_DEFECT，safe_auto_fix=true，confidence=0.98；结构化收敛需VC-003 |
| 13 | Closure Code Validator / M11-v4-r11 VC-003 | 高：结构化目标、完整隐私边界和Prompt独立绑定 | high | high | 真实模型前必须独立验收VC-003 | available | 只读 | 仅VC-003、A-018/A-019与当前结果 | FAIL：章节/强度、敏感值和Prompt独立冻结三项缺口；703项门PASS，模型调用0 |
| 14 | Failure Analyst / M11-v4-r12 | 高：统一归因三个VC-003失败特征 | high | high | 当前处于DIAGNOSIS_PENDING；实施前必须确认是否可安全自动修复 | available | 只读 | VC-003、三项失败证据、当前Parser/Context/Runner | completed：F05A/B/C均为IMPLEMENTATION_DEFECT且safe_auto_fix=true；仅强度源语法需VC-004 |
| 15 | Contract Validator / M11-v4-r12 VC-004 | 高：强度兼容格式、有限隐私矩阵与Prompt权威根 | high | high | 合同升级后实施前必须独立确认无冲突 | available | 只读 | 仅VC-004、A-018/A-019与当前事实 | INCONCLUSIVE：无有效blocking finding；日期/四类技术、有限矩阵词法、Prompt拓扑和GATE入口未逐字闭合 |
| 16 | Final Contract Validator / M11-v4-r12 VC-004 | 高：澄清后的完整合同终验 | high | high | 用户逐字批准补齐日期/技术/词法/Prompt拓扑/GATE | available | 只读 | 仅完整VC-004、A-018/A-019与当前事实 | INCONCLUSIVE：A-018/Prompt拓扑PASS；Unicode说明、既有隐私词法及复合GATE基线仍有多解 |
| 17 | Contract Validator / M11-v4-r13 VC-005 | 高：最终机器词法、有限矩阵及测试节点基线 | high | high | 用户批准将全部剩余歧义形式化；实现前最后合同门 | available | 只读 | 仅VC-005、A-018/A-019与当前事实 | INCONCLUSIVE：AC-01、AC-02、TM-01、GATE-01仍存在机器解释歧义；无blocking finding，未修改文件 |
| 18 | Contract Validator / M11-v4-r13 VC-006 | 高：目标模板、有限隐私词法、故障矩阵和节点算法 | high | high | 用户逐字批准消除VC-005剩余多解；实现前必须独立确认 | available | 只读 | 仅VC-006、A-018/A-019与当前事实 | PASS：全部AC/INV/TM/EX/GATE与A-018/A-019一致，无blocking/unknown；未修改文件 |
| 19 | Closure Code Validator / M11-v4-r13 VC-006 | 高：目标Parser、有限隐私词法、Prompt/目标权威绑定和完整门 | high | high | 真实模型前必须由全新Agent独立复验当前快照 | available | 只读 | 仅VC-006、A-018/A-019、适用规则与当前仓库结果 | FAIL：`AC-004/TM-006`；LF 属于合同允许的 ASCII 空白，但坐标正则只接受空格/Tab，`坐标 22.1234,\n114.1234`进入 fake 模型一次；其余门PASS |
| 20 | Final Closure Code Validator / M11-v4-r14 VC-006 | 高：六种ASCII空白坐标、模型前阻断和完整门 | high | high | 用户批准只修`AC-004/TM-006`；PASS前不得建立Candidate或调用真实模型 | available | 只读 | 仅VC-006、A-018/A-019、适用规则与当前仓库结果 | FAIL：六种ASCII空白全部闭合；但NFKC把NBSP/EM SPACE折叠为SP，矩阵外Unicode空白坐标被错误阻断，绑定`AC-004/TM-002/GATE-004` |
| 21 | Contract Validator / M11-v4-r15 VC-007 | 高：逐检测器raw/NFKC、ASCII-only大小写与advisory矩阵 | high | high | 合同升级后实现前必须独立确认无冲突和多解 | available | 只读 | 仅VC-007、A-018/A-019与当前仓库事实 | PASS：全部适用AC/INV/TM/EX/GATE一致且可测试；757/703节点SHA、15种Unicode空白和Builder/Runner共享入口均独立复核 |
| 22 | Closure Code Validator / M11-v4-r15 VC-007 | 高：双视图实现、正反例、零调用与完整门 | high | high | Contract PASS且实现门全过后独立终验 | available | 只读 | 仅VC-007、A-018/A-019、适用规则与当前仓库结果 | PASS：857 tests、全部静态门、757/703旧节点、正式state与零外部调用独立复核，无blocking finding |
| 23 | Failure Analyst / M11-v4-r15 Candidate preflight | 高：真实结构化健康/技术内容与VC-007有限斜杠矩阵冲突 | high | high | 两个冻结目标疑似无法同时满足，A-019要求先独立归因 | available | 只读 | VC-007、两类合法字段路径、三次Candidate准备证据与当前实现 | completed：F06A/B=IMPLEMENTATION_DEFECT且safe_auto_fix=true；F06C=PLAN_CONTRACT_CONFLICT，必须人工批准VC-008，confidence=0.995 |
| 24 | Contract Validator / M11-v4-r16 VC-008 | 高：Schema感知精确单位例外、其余路径边界和既有业务合同 | high | high | 合同升级后实现前必须独立确认结构路径、精确值和测试边界无多解 | available | 只读 | 仅VC-008、A-018/A-019与当前仓库事实 | PASS：AC/INV/TM/EX/GATE与A-018/A-019一致且可测试；860节点和SHA独立复核；无blocking/unknown |
| 25 | Closure Code Validator / M11-v4-r16 VC-008 | 高：共享验证器、SQLite修正、完整门和零调用 | high | high | Contract PASS且实现门全过后独立终验 | available | 只读 | 仅VC-008、A-018/A-019、适用规则与当前仓库结果 | PASS：869 tests、冻结860节点、12项专项、Ruff/format/mypy、100 AST/compile、78 Schema、正式state与零调用全部独立闭合 |
| 26 | Closure Code Validator / M11-v4-r17 VC-009 | 高：仓库外隔离目录、Codex命令安全参数与单次授权 | high | high | 真实模型调用前必须独立复验新命令合同与所有原边界 | available | 只读 | 仅VC-009、A-018/A-019、适用规则和当前仓库结果 | PASS：19项VC-009专项、870 tests、Ruff/format/mypy、100 AST/compile、78 Schema、正式state、r16终态与零调用全部独立闭合 |
| 27 | Failure Analyst / M11-v4-r18 | 高：真实模型wire通过而业务层集中失败 | high | high | 触发DIAGNOSIS_PENDING，必须先区分实现、合同和环境问题 | available | 只读 | VC-009、r16/r17不可变证据和当前三层实现 | completed：F07A/B/C均确认三层不同步；无不同根因或环境故障 |
| 28 | Contract Validator / M11-v4-r18 VC-010 | 高：模型/Host职责、强结构课程、BPM字段边界和双调用门 | high | high | 合同升级后实现前必须独立确认无冲突 | available | 只读 | 仅VC-010、A-018/A-019、适用规则和当前仓库事实 | INCONCLUSIVE：AC-005残留r17成功要求；Schema投影删除集合含“等”而未穷举；无blocking finding |
| 29 | Code Validator / M11-v4-r18 VC-010 | 高：Schema投影、Runner v3、Reader证据绑定和重放 | high | high | 公开/私人模型前必须独立复验完整代码门 | available | 只读 | 仅VC-010、A-018/A-019、适用规则和当前结果 | FAIL：Finalizer仍回读Candidate外Context；私人调用未绑定canary成功凭据；活动心率事实缺日期；均绑定AC-012/014/015与TM-008/009 |
| 30 | Final Contract Validator / M11-v4-r18 VC-010 | 高：修正后的r17不可变语义和Schema投影闭集 | high | high | 原批准计划的映射修正后必须由全新Agent确认无冲突 | available | 只读 | 仅完整VC-010、A-018/A-019、适用规则和当前仓库事实 | PASS：全部AC/INV/TM/EX/GATE内部一致、可实现且可测试，无blocking/advisory/unknown |
| 31 | Final Code Validator / M11-v4-r18 VC-010 | 高：Candidate内结果闭包、canary门、活动日期与完整代码门 | high | high | 首次FAIL后的唯一集中修正必须由全新Agent独立终验 | available | 只读 | 仅VC-010、A-018/A-019、适用规则和当前仓库结果 | FAIL：AC-013/GATE-004；business→wire parity已闭合，但缺少Prompt槽位、variant、步骤和禁用字段与Schema的自动语义parity |
| 32 | Failure Analyst / M11-v4-r19 Prompt parity | 高：区分Prompt语义parity缺口的实现、合同或验证责任 | high | high | r18最终验证后进入DIAGNOSIS_PENDING；r19实施前必须正式归因 | available | 只读 | VC-010、A-018/A-019、当前Prompt/Schema/parity实现与失败特征 | completed：M11-V4-F08=`IMPLEMENTATION_DEFECT`、`safe_auto_fix=true`、`contract_change_required=false`、confidence=0.995；允许在VC-010内实施一次针对性修正 |
| 33 | Code Validator / M11-v4-r19 VC-010 | 高：Prompt/business/wire/Host三层parity与完整模型前门 | high | high | 公开canary前必须独立复验当前快照 | available | 只读 | 仅VC-010、A-018/A-019、适用规则和当前仓库结果 | PASS：909 tests、39项专项、Ruff/format/mypy、AST/Schema/Markdown/隐私/diff、正式state与零调用均闭合；无blocking finding |

Validator 只按冻结合同验收，不得临时扩张威胁模型。首次 FAIL 只汇总一个修正批次并交全新
最终 Validator；最终仍 FAIL/INCONCLUSIVE 时停止，不循环补丁或执行真实模型调用。

## 工作分解

| 步骤 | 状态 | 证据 |
| --- | --- | --- |
| M11-0016-01 冻结 A-018、Roadmap、运行说明和 active plan | completed | 用户批准计划；Git基线 `b172f95`，工作树摘要已记录；首轮FAIL后集中消除4项治理歧义 |
| M11-0016-02 全新 Contract Validator | completed | 首轮FAIL证据保留；集中修正后全新终验 PASS |
| M11-0017-01 测试先行定义 v4 Schema、日期与技术矩阵 | completed | 红灯确认后转绿；旧测试未删除/skip/xfail |
| M11-0017-02 实现全量观察、技术摘要、Prompt与固定课表 | completed | 唯一共享Context验证器由builder/runner共同使用；runner在pending/模型前复验完整Context及规范Prompt；每个activity_ref分别绑定available指标 |
| M11-0018-01 同源生成MD/低保真HTML和公开合成样例 | completed | 五视口、图表上限、单层结构及公开样例测试通过 |
| M11-0018-02 完整门与全新 Code Validator | blocked | 主协调690 tests及全部静态门PASS；全新Closure Code Validator复现中文紧邻POSIX绝对路径漏检并绑定AC-004/TM-002/TM-005/GATE-004，依冻结停止条款恢复诊断门 |
| M11-0017-03 Failure Analyst 归因与 VC-002 冻结 | completed | Failure Analyst 已完成；用户批准六类健康三状态；全新 Contract Validator PASS |
| M11-0017-04 v4-r10 测试先行与受限实现修正 | completed | 六类健康三状态、逐活动规范证据身份、Unicode/词元路径边界和四份权威Schema独立绑定已转绿；真实模型调用仍为0 |
| M11-0017-05 v4-r11 结构化训练目标与Context v2 | blocked | 703项门PASS，但全新Closure Code Validator返回FAIL：章节归属/强度格式、敏感值覆盖及Prompt独立冻结仍不满足VC-003；进入DIAGNOSIS_PENDING |
| M11-0017-06 v4-r12 输入合同一次性收敛 | completed | Failure Analyst闭合F05A/B/C；两次Contract Validator的INCONCLUSIVE推动合同词法形式化，不进入代码实现 |
| M11-0017-07 v4-r13 VC-006实现与原闭环续跑 | blocked | 25项旧缺口红灯后完成修正；743 tests及全部静态门PASS；Closure Code Validator复现换行坐标漏检并绑定`AC-004/TM-006`，依批准停止条款不自动修补 |
| M11-0017-08 v4-r14 ASCII空白坐标闭包 | blocked | 六种ASCII空白已闭合且757项门PASS；Final Closure发现NFKC把NBSP/EM SPACE折叠为SP，违反矩阵外Unicode空白仅advisory的冻结边界；依停止条款不自动修补 |
| M11-0017-09 v4-r15 双视图输入边界收敛 | completed | Contract与Closure Code Validator均PASS；52项旧实现缺口红灯后转绿，857项及全部静态门闭合 |
| M11-0017-10 v4-r16 VC-008结构化斜杠例外与SQLite兼容闭包 | completed | Contract与Closure Code Validator均PASS；869项及全部静态门独立闭合，模型调用0 |
| M11-0018-03 建立owner-only Candidate并执行一次真实周报 | blocked | r16 Candidate prepare完整闭合；唯一CLI调用因仓库外模型目录缺少`--skip-git-repo-check`在模型请求前失败；终态证据已保存，禁止重试 |
| M11-0018-04 v4-r17命令合同修正与原闭环续跑 | blocked | 命令修正与Validator均PASS；唯一模型调用已返回，wire Schema通过但业务合同因period、课程phase集和事实bpm误判共8项失败，依冻结规则停止且不重试 |
| M11-0018-05 v4-r18三层同构修正与公开canary | blocked | 首次3项缺口已修复且896 tests/静态门PASS；Final Code Validator发现Prompt与Schema缺少自动语义parity，绑定AC-013/GATE-004；依冻结停止规则不再修补或调用模型 |
| M11-0018-06 v4-r19 Prompt语义同构闭包与原流程续跑 | blocked | Code Validator PASS后唯一公开canary完成1次模型调用；wire通过，但day_3/day_6休息课的`technique_notes=[]`违反业务Schema `minItems:1`，终态`model_failed`；依计划不重试，私人调用0 |
| M11-0019-01 三类最终内容/架构/数据验证 | pending | 全部PASS |
| M11-0019-02 交付预览与OpenDesign内容包，等待用户确认 | pending | 不执行高保真或邮件 |

## 当前检查点

- 当前 Loop：M11 v4-r19 公开canary业务校验阻塞。
- 最近完成：唯一公开canary已调用1次；wire Schema通过，业务Schema因day_3/day_6休息课的空`technique_notes`数组阻断，失败证据原子闭合。
- 当前焦点：保持公开Candidate `/private/tmp/trainlab-m11-v4-r19-canary.NvxQ0X/candidate` 不变，并确认私人模型调用为0。
- 下一动作：依批准计划停止；需要用户批准新的合同/实现修订后，才能建立新canary或调用模型。
- 阻塞项：wire允许移除`minItems`，而当前Prompt语义块未表达该业务层非空数组约束；模型合理地产生空数组后被最终业务校验拒绝。
- blocker_type：`MODEL_BUSINESS_VALIDATION_FAILED`
- 诊断状态：`completed`（M11-V4-F08已关闭；本次新失败尚未进入新诊断批次）
- 已变更文件：本计划、M11 Roadmap/活动指针、v4 Schema/共享健康验证器、Candidate Builder、Codex Runner、内容合同测试及 source 运行/Skill说明。
- 待验证项：新修订授权、全新公开canary、私人周报调用与三类最终Validator。

## 决策与发现

- 当前 Host 已收集每天全部活动，但 `weekly_evidence_digest_v1` 只向周 AI 提供跑量、活动数和
  硬负荷数；问题位于周 AI 输入合同，不是采集缺失。
- 真实预览不重跑七份日报 AI：日报健康分析保持不变；只有周报使用一次新 AI 调用。
- `weekly-fitness-summary` 的技术证据/置信度边界适用，但其旧动态降级建议由 A-018 固定计划
  选择明确替代。

## Validator 结论处理

| Loop | Validator 身份 | 合同版本 | 结论 | 绑定标准与证据 | 主协调 Agent 处理 | 是否触发诊断 | 下一 Validator |
| --- | --- | --- | --- | --- | --- | --- | --- |
| historical | 历史 Contract/Code/Closure Validators | legacy pre-VC-001 | FAIL/PASS 混合 | 只作为失败尝试事实保留，不转交下一 Validator | 映射后保持 blocked | 是：反复修法与验证未收敛 | 不直接派 Validator |
| diagnosis | Failure Analyst | VC-001 | n/a | F01=`IMPLEMENTATION_DEFECT`；F02=路径实现缺陷+健康合同歧义；F03=`UNDETERMINED`历史责任 | 用户升级 VC-002；历史 verdict 不转移 | 已完成 | 全新 VC-002 Contract Validator |
| contract-r10 | fresh Contract Validator | VC-002 | PASS | 全部 AC/INV/TM/EX/GATE 与 A-018/A-019 一致，无阻塞或未知 | 进入唯一受限实现批次 | 否 | 全新 Closure Code Validator |
| closure-r10 | fresh Closure Code Validator | VC-002 | FAIL | `AC-004`、`TM-002`、`TM-005`、`GATE-004`：中文紧邻POSIX绝对路径漏检；fake模型调用1而非0 | 保持真实调用0并恢复DIAGNOSIS_PENDING | 是：新失败特征需先归因 | Failure Analyst或用户批准的后续修订 |

## 失败尝试与诊断

以下记录来自 v0.4.4 合同建立前的历史实施，只用于 Failure Analyst 归因；不得向后续 Validator
提供历史 verdict、推理或新增假设，也不据此预判失败类别。

| Failure ID | 合同版本 | 标准 ID | 失败特征 | 历史尝试 | 当前结果 |
| --- | --- | --- | --- | --- | --- |
| `M11-V4-F01` | legacy → VC-002 | `AC-003`、`TM-003` | 同一规范 evidence ref 可登记给多个活动 | Failure Analyst 复现字符串归属未校验 | `IMPLEMENTATION_DEFECT / safe_auto_fix=true` |
| `M11-V4-F02A` | legacy → VC-002 | `AC-004`、`TM-002` | 普通中文斜线文本被识别为绝对路径 | Failure Analyst 复现正则只认识 ASCII 左边界 | `IMPLEMENTATION_DEFECT / safe_auto_fix=true` |
| `M11-V4-F02B` | VC-001 → VC-002 | `AC-007`、`TM-002` | 六类健康缺失状态、value、原因和 lineage 语义未冻结 | 用户批准 available/missing/insufficient_data 三状态 | `PLAN_CONTRACT_CONFLICT resolved by VC-002` |
| `M11-V4-F03` | legacy → VC-001 | `INV-004`、`GATE-005` | 历史合同形成晚于实现，无法可靠裁决当时责任 | 历史记录保留但不交给新 Validator | `UNDETERMINED / no code action` |

### Failure Analyst 固定输出

后续 Failure Analyst 必须返回 `failure_id`、`failure_class`、`criterion_ids`、
`failure_signature`、`trigger`、`attempts_compared`、`evidence`、`minimal_conflict_set`、
`contract_change_required`、`safe_auto_fix`、`recommended_actions` 和 `confidence`；不得修改文件、
合同或测试，也不得返回 `PASS`。本 ADHOC-0015 不执行该诊断。

## Validator 固定输出

后续 Validator 必须原样包含 `contract_version`、`overall_verdict`、`criterion_results`、
`blocking_findings`、`advisories`、`scope_change_candidates`、`unknowns` 和
`commands_and_evidence`。任何阻塞发现必须绑定 `AC-*`、`INV-*`、`TM-*`、`RULE-*` 或
`GATE-*`；未绑定时整体为 `INCONCLUSIVE`。

## 任务级独立验证

- 逐字冻结合同版本：`VC-010`。
- 中性交接：仅冻结合同、A-018/A-019、适用规则和当前仓库结果；不提供历史 Validator verdict 或实施者辩护。
- 结果：`FAIL`——Final Code Validator绑定`AC-013/GATE-004`确认Prompt与Schema缺少自动语义parity；依批准的停止规则不建立公开或私人Candidate。

## 集成级独立验证

- 集成范围：严格串行，无并行集成；最终 Data/Privacy Validator 作为整体终验。
- 结果：`pending`

## PLANS 回写清单

- [ ] Exec plan 已归档到 `completed/`
- [ ] Roadmap 叶子任务已更新为 `[x] completed`
- [ ] 子项目和阶段状态已重新计算
- [ ] `memory.md` 中的活动计划指针已删除

## 迭代日志

| 日期/上下文 | 已完成事项与证据 | 发现 | 下一动作 |
| --- | --- | --- | --- |
| 2026-08-24 / start | 用户批准 M11 v4；Git/工作树/治理文件/Skills 已恢复 | 周AI输入只含压缩汇总，必须版本化完整观察证据 | 冻结A-018并执行Contract Validator |
| 2026-08-24 / contract-fail-01 | 首轮Contract Validator返回FAIL | 后续任务过早ready；v4周报raw fallback、旧日报改课语义和过期Gmail授权仍有歧义 | 保留FAIL；集中修正状态、版本优先级、raw禁令和当前零Gmail授权，交全新终验 |
| 2026-08-24 / contract-pass-02 | 全新最终Contract Validator返回PASS | 冻结合同、日期、安全、raw=0和零外部动作均无未满足项 | 完成M11-0016，进入M11-0017测试先行 |
| 2026-08-24 / code-gates-03 | 627 tests、Ruff/format/mypy、96文件AST、Schema/隐私/布局与diff门通过 | 首轮完整测试发现1个旧M9时序波动，定向与最终完整复跑均PASS；新增AI case补齐verdict/evidence治理列 | 完成M11-0017及合成内容，交全新Code Validator |
| 2026-08-24 / code-validator-fail-04 | 全新Code Validator返回FAIL；真实模型调用保持0 | 活动闭包循环自证、技术前10分钟未真实排除、AI技术引用未绑定、课程lineage缺失、模型目录与raw未物理隔离 | 保留FAIL；在内容合同不变下完成一次集中修正并交全新Final Code Validator |
| 2026-08-24 / final-code-validator-fail-05 | 集中修正后639 tests与全部静态门PASS；全新Final Code Validator仍返回FAIL | runner未在模型启动前重新执行完整Context隐私检查；多activity技术结论可只由其中一项指标支持 | 依批准的停止规则转blocked；真实Candidate和模型调用均未开始，等待用户决定 |
| 2026-08-24 / final-closure-authorized-06 | 用户批准最终证据闭包计划并恢复原M11续跑授权 | 范围严格限定为启动前隐私复验与逐activity证据绑定；真实调用仍未使用 | 测试先行修复，完整门后交全新Closure Code Validator |
| 2026-08-24 / final-closure-gates-07 | 6个新增红灯准确复现；共享验证器和逐activity绑定转绿；646 tests、Ruff/format/mypy、97文件AST及全部治理门PASS | 同步更新已覆盖的Context/Prompt与manifest SHA不能绕过；多活动结论必须逐项提供available指标 | 交全新Closure Code Validator；PASS前真实模型调用保持0 |
| 2026-08-24 / closure-validator-fail-08 | 全新Closure Code Validator完成646 tests及全部静态门并返回FAIL；逐活动证据闭包PASS | `/etc/...`等任意绝对路径、开放value子字段及复制Schema与manifest同步漂移仍可进入fake模型调用 | 依用户冻结规则立即blocked；无Candidate、无真实模型调用，等待新计划授权 |
| 2026-08-24 / r09-authorized-09 | 用户批准M11 v4-r09并恢复同一active plan | 固定只修任意绝对路径、六类健康/四类技术value白名单及Candidate Schema独立绑定；逐活动证据保持闭合 | 测试先行实现，完整门后交全新r09 Closure Code Validator |
| 2026-08-24 / r09-gates-10 | 18项新增入口回归转绿；664 tests及全部静态/Schema/隐私门PASS | 首轮全量中的旧M9时序用例单独与完整复跑均PASS，确认非r09回归；真实Candidate与模型调用仍为0 | 交全新只读r09 Closure Code Validator，PASS前不建立私人Candidate |
| 2026-08-24 / r09-validator-fail-11 | 全新只读high/high Closure Code Validator完成664 tests和完整门并返回FAIL | 跨活动证据复用、健康status/value合同缺失、普通中文路径误判均属于冻结范围；权威Schema绑定与绝对路径阻断本身PASS | 依批准停止规则保持blocked；不建立Candidate、不调用模型，等待用户决定 |
| 2026-08-24 / v044-legacy-transition-12 | 依据 A-019 将既有 M11 v4/r09 要求映射为面向未来的 VC-001 | 合同形成晚于历史实现，不能追溯假定历史已冻结；多轮失败需要独立归因 | 保持 blocked/DIAGNOSIS_PENDING/pending，下一阶段才派 Failure Analyst |
| 2026-08-24 / diagnosis-vc002-13 | 全新 Failure Analyst 完成 F01/F02/F03 归因；用户明确选择三状态并批准 v4-r10 | F01 与路径为实现缺陷；六类健康状态需升级合同；历史责任不追溯 | 冻结 VC-002，交全新 Contract Validator，PASS 后仅实施本批次 |
| 2026-08-24 / vc002-contract-pass-14 | 全新只读 high/high Contract Validator 返回 PASS；全部 AC/INV/TM/EX/GATE 与 A-018/A-019 无冲突 | 既有 v4 内部 Schema 尚未实现三状态，但属于后续实现事实而非合同缺陷 | 恢复 active，先写回归测试，再完成唯一受限修正批次 |
| 2026-08-24 / vc002-gates-15 | 先写失败测试后完成六类健康三状态、逐活动规范证据身份、Unicode路径词元识别及权威Schema独立绑定；73项聚焦和690项完整测试、Ruff/format/mypy/compile、76 Schema、Markdown/AI布局/隐私/权限/diff门PASS | 首次定向红灯18项均对应旧实现缺口；实现后无剩余代码门失败，正式state指纹仍为 `7cc9f67d…`，模型及外部调用0 | 状态转validating，交全新Closure Code Validator；PASS前不建立私人Candidate |
| 2026-08-24 / vc002-validator-fail-16 | 全新只读Closure Code Validator完成690项测试及全部门，返回FAIL | `请读取/Users/private/goal.md`与`路径/etc/passwd`因中文字符被现有左边界判断当成安全文本，前检返回无错误并进入fake模型调用1次；合法斜线样例仍通过 | 真实Candidate/模型调用保持0；按冻结停止条款设为blocked/DIAGNOSIS_PENDING，不自动修补 |
| 2026-08-24 / r11-authorized-17 | 用户批准结构化训练目标、Context v2和原M11续跑计划 | `goal.md`只由Host按公开模板解析；模型Context不得包含文件路径；当前私人文件已只读确认与模板同为6章节/19字段，不输出私人内容 | 保持诊断门，先派全新只读Failure Analyst；归因满足条件后才实施 |
| 2026-08-24 / r11-diagnosis-vc003-18 | 全新只读Failure Analyst返回M11-V4-F04=`IMPLEMENTATION_DEFECT`、safe_auto_fix=true、confidence=0.98 | 最小漏检无需改合同，但整份goal自由字符串长期依赖启发式扫描；结构化收敛需新合同 | 冻结用户已批准的VC-003，恢复active并开始测试先行实现 |
| 2026-08-24 / vc003-gates-19 | 先写回归后完成Host结构化目标、Context/Prompt v2、权威目标Schema绑定和模型前路径阻断；77项聚焦、703项完整测试、Ruff/format/mypy、99文件AST、78 Schema、Markdown/metadata/AI布局/隐私/权限/diff门PASS | 旧Context v1 SHA仍为`79eb9ef5…`；正式state指纹仍为`7cc9f67d…`，Candidate、模型及外部调用0 | 状态转validating；交全新Closure Code Validator，PASS前不得建立私人Candidate |
| 2026-08-24 / vc003-validator-fail-20 | 全新只读high/high Closure Code Validator复跑703项和全部静态门后返回FAIL | AC-008：标签未绑定所属章节、强度`3.5/3x/3/5`被解析为3；AC-004/TM-002：部分文件名、活动名称、Bearer与坐标可进入fake模型；INV：Prompt与manifest同步漂移缺少权威冻结常量 | 依批准停止规则转blocked/DIAGNOSIS_PENDING；不建立Candidate、不调用真实模型，不自动修补 |
| 2026-08-24 / r12-authorized-21 | 用户批准v4-r12完整续跑，并选择强度输入兼容整数或`N/5，说明`，说明不进入模型 | 固定三个修正簇和有限敏感值/文件名矩阵；不得由后续Validator临时扩张 | 保持DIAGNOSIS_PENDING，先派全新只读Failure Analyst；只有IMPLEMENTATION_DEFECT且safe_auto_fix=true才冻结VC-004并实施 |
| 2026-08-24 / r12-diagnosis-vc004-22 | 全新Failure Analyst分别归因F05A/B/C | 三项均为IMPLEMENTATION_DEFECT且safe_auto_fix=true；703绿属于矩阵缺口；仅强度源语法需合同升级 | 冻结用户批准的VC-004，转validating并派全新Contract Validator，真实模型调用保持0 |
| 2026-08-24 / vc004-contract-inconclusive-23 | 全新只读Contract Validator返回INCONCLUSIVE，无blocking finding | 合同摘要未逐字列出继承日期/四类技术指标；有限矩阵词法、Prompt模板SHA绑定拓扑和GATE入口仍可多解 | 不修改实现；请求用户确认澄清文本，随后用完整同一合同交全新Contract Validator |
| 2026-08-24 / vc004-clarification-authorized-24 | 用户批准合并后的r12完整计划 | 日期/四类技术、AC-004嵌套语义、有限矩阵词法与优先级、Prompt模板SHA拓扑、完整GATE入口已逐字闭合 | 保持VC-004版本不变，交全新Final Contract Validator；PASS前不实施 |
| 2026-08-24 / vc004-final-contract-inconclusive-25 | 全新Final Contract Validator仍返回INCONCLUSIVE，无blocking finding | A-018与Prompt拓扑PASS；强度说明Unicode计数、沿用邮箱/秘密/GPS/路径词法、skip/xfail与复合GATE目标集合仍未形式化 | 不修改实现；请求人工批准仅做词法和门禁基线澄清的VC-005 |
| 2026-08-25 / vc005-authorized-26 | 用户批准M11 v4-r13完整计划 | 机器词法、矩阵外advisory规则、Prompt精确字节、703节点及静态目标集合均冻结 | VC-005生效并交全新Contract Validator；PASS前不实施、不调用模型 |
| 2026-08-25 / vc005-contract-inconclusive-27 | 全新只读 high/high Contract Validator 返回 INCONCLUSIVE；无blocking finding | AC-01未逐字冻结章节/字段及强度字段映射；AC-02未列活动标签、坐标语法和Unicode邮箱优先级；TM-01未枚举故障点；GATE-01未定义节点清单规范化算法 | 依A-019停止实施与模型调用；保持validating，等待用户批准VC-006澄清，不以实现猜测补合同 |
| 2026-08-25 / vc006-authorized-28 | 用户批准M11 v4-r13 VC-006完整执行计划 | 权威目标模板1标题/5章节/19字段、活动标签、坐标与Unicode邮箱优先级、有限故障注入点及节点清单算法已逐字冻结 | 交全新Contract Validator；PASS前不修改生产实现、不建立Candidate、不调用模型 |
| 2026-08-25 / vc006-contract-pass-29 | 全新只读high/high Contract Validator返回PASS | VC-006全部AC/INV/TM/EX/GATE与A-018/A-019内部一致且可测试；703节点清单和两个权威SHA均独立复核 | 恢复active，按测试先行顺序实施；真实Candidate、模型和外部调用保持0 |
| 2026-08-25 / vc006-gates-pass-30 | 先新增40节点，其中25项准确复现旧实现；完成目标章节/字段状态机、精确强度语法、有限隐私词法和Prompt/目标模板独立SHA绑定 | 743 tests两次完整PASS；Ruff/format/mypy、100 AST、78 Schema、6 Skill metadata、80 Markdown、703原节点子集、skip/xfail 0、正式state `7cc9f67d…`与隐私/diff门PASS | 状态转validating，交全新Closure Code Validator；PASS前真实Candidate和模型调用仍为0 |
| 2026-08-25 / vc006-validator-fail-31 | 全新只读high/high Closure Code Validator完成743项及全部静态门并返回FAIL | `AC-004/TM-006`：坐标正则遗漏LF/CR/VT/FF等合同允许的ASCII空白；换行坐标进入fake模型一次；其余标准和门禁PASS | 依用户批准的停止条款转blocked；不自动修补、不建立Candidate、不调用真实模型，等待用户批准小范围修复 |
| 2026-08-25 / r14-authorized-32 | 用户批准M11 v4-r14小范围修复并续跑原M11 | VC-006保持冻结；仅以显式`SP/HT/LF/VT/FF/CR`补齐坐标分隔，矩阵外Unicode空白仍为advisory | 恢复active；测试先行，完整门和全新Final Closure Code Validator PASS前真实Candidate/模型调用保持0 |
| 2026-08-25 / r14-gates-pass-33 | 新增14个ASCII空白坐标节点；旧实现对LF/VT/FF/CR的8个组合如期红灯，显式`[\\x09-\\x0D\\x20]*`修正后全部转绿 | 118项聚焦、757项完整测试、Ruff/format/mypy、100 AST、78 Schema、6 metadata、80 Markdown、原703节点子集、skip/xfail 0、正式state `7cc9f67d…`与隐私/diff门PASS | 状态转validating；交全新Final Closure Code Validator，PASS前真实Candidate/模型调用仍为0 |
| 2026-08-25 / r14-validator-fail-34 | 全新只读high/high Final Closure Code Validator完成757项和全部静态门并返回FAIL | SP/HT/LF/VT/FF/CR均正确阻断；但Context字符串先NFKC，NBSP/EM SPACE被折叠为SP并错误阻断，绑定`AC-004/TM-002/GATE-004` | 依用户批准停止条款转blocked；不自动修补、不建立Candidate、不调用真实模型，等待用户决定 |
| 2026-08-25 / r15-vc007-authorized-35 | 用户批准M11 v4-r15双视图完整计划并续跑原M11 | 逐检测器冻结raw/NFKC、ASCII-only大小写、15种Unicode空白advisory和现有757节点；VC-006被VC-007替代 | 状态转validating；先交全新Contract Validator，PASS前不修改生产实现或测试 |
| 2026-08-25 / r15-gates-pass-36 | 全新Contract Validator PASS后先增加完整双视图矩阵；旧实现52项准确红灯，修正后149项聚焦及857项完整测试PASS | 删除整串/路径重复NFKC；字段名保留NFKC，活动标签仅局部NFKC，其余检测器使用raw与ASCII-only大小写；Ruff/mypy、100 AST、78 Schema、6 metadata、80 Markdown、原703节点、skip/xfail 0、正式state `7cc9f67d…`和Git/隐私门均PASS | 状态转validating；交全新Closure Code Validator，PASS前Candidate、真实模型和外部调用保持0 |
| 2026-08-25 / r15-closure-pass-37 | 全新只读high/high Closure Code Validator按VC-007独立复跑并返回PASS | 857 tests、VC-007专项100项、Ruff/format/mypy、100 AST、78 Schema、6 metadata、80 Markdown、757/703旧节点、正式state与零外部调用全部独立闭合 | 完成M11-0017-09；恢复原M11续跑，建立全新owner-only Candidate并准备唯一一次真实周报调用 |
| 2026-08-25 / r15-candidate-preflight-blocked-38 | 三份全新owner-only Candidate均在模型前确定性停止；前两份分别命中summary需JSON+text、report output kind须使用共享`report_artifact` | 两项SQLite兼容缺口均先新增红灯再修正；第三份Context有17个`path_or_filename`命中，全部位于VO₂ Max单位及Host技术限制文字，真实模型/pending/Provider/external action仍为0 | 发现VC-007三斜杠白名单与六类健康/四类技术输入疑似直接冲突；转DIAGNOSIS_PENDING并派全新Failure Analyst，不静默扩白名单 |
| 2026-08-25 / r15-diagnosis-39 | 全新只读high/high Failure Analyst完成F06A/F06B/F06C独立归因 | F06A、F06B为可安全修复的SQLite实现缺陷；F06C为`PLAN_CONTRACT_CONFLICT`：结构化VO₂ Max单位固定为`ml/kg/min`，但VC-007仅允许三个斜杠词元，二者无法同时满足 | 保留两项测试先行修正；状态改为blocked/PLAN_CONTRACT_CONFLICT，等待人工批准VC-008，真实模型调用仍为0 |
| 2026-08-25 / r16-vc008-authorized-40 | 用户批准M11 v4-r16完整计划；860节点实施前清单已owner-only冻结 | 仅对严格Schema验证后的VO₂ Max available事实两个单位字段放行精确`ml/kg/min`；Host技术说明去除斜杠；其余VC-007边界不变 | 状态转validating并交全新Contract Validator；PASS前不修改生产实现、不建立Candidate、不调用模型 |
| 2026-08-25 / r16-contract-pass-41 | 全新只读high/high Contract Validator按VC-008返回PASS | 精确单位例外与权威health fact常量一致；860节点SHA独立复核；无blocking、unknown或范围变更 | 状态转active；先新增失败测试，再实施共享验证器和Host文案收敛，真实模型调用保持0 |
| 2026-08-25 / r16-gates-pass-42 | 先增加9项VC-008节点；合法单位与Host旧文案2项准确红灯，实施后全部转绿；F06A/B三项SQLite回归继续通过 | 869 tests；Ruff/format/mypy、100项只读AST/compile、78 Schema、6 metadata、80 Markdown、AI布局/隐私/Git ignore/diff门PASS；860基线节点全部保留且skip/xfail 0；正式state `7cc9f67d…`、父Candidate和三份失败证据不变，模型/pending/外部调用0 | 状态转validating；交全新Closure Code Validator，PASS前不建立新Candidate或调用真实模型 |
| 2026-08-25 / r16-closure-pass-43 | 全新只读high/high Closure Code Validator按VC-008独立返回PASS | 869 tests、冻结860节点、12项专项、Ruff/format/mypy、100 AST/compile、78 Schema、metadata/AI/Markdown/权限/隐私/diff、正式state与零调用全部独立闭合 | 完成M11-0017-10；恢复M11-0018-03，建立第四份全新owner-only Candidate并准备唯一真实周报调用 |
| 2026-08-25 / r16-model-cli-blocked-44 | r16 Candidate prepare后完整复验9370 raw、SQLite integrity/FK、86 triggers、权限、Context/Prompt/Schema/Goal及正式state；随后执行唯一Codex CLI调用 | CLI在模型请求前因隔离工作目录不在Git仓库且命令缺少`--skip-git-repo-check`退出；attempt receipt为blocked，ai-result不存在，Provider/external action 0 | 依用户冻结停止规则保留完整终态并停止；r16不得重试，等待新计划修正命令合同并另行授权一次模型调用 |
| 2026-08-25 / r17-vc009-authorized-45 | 用户对“仅加入`--skip-git-repo-check`、补命令回归、交全新Code Validator、PASS后建全新Candidate并执行一次新授权”回复“可以” | r16失败是隔离设计与Codex CLI Git信任前检的实现兼容缺口，不是业务、数据或Schema变更 | VC-009冻结并恢复active；测试先行，全新Validator PASS前不建立Candidate或调用模型 |
| 2026-08-25 / r17-gates-pass-46 | 新测试在旧实现上精确因intent缺少命令绑定而红灯；仅修改Runner命令与intent后转绿 | 870 tests；Ruff/format/mypy、100 AST/compile、78 Schema、6 Skill metadata、80 Markdown、AI布局/隐私/Git ignore/diff门PASS；Codex help确认参数合法；正式state `7cc9f67d…`不变 | 状态转validating；交全新Closure Code Validator，PASS前不建Candidate或调用模型 |
| 2026-08-25 / r17-closure-pass-47 | 全新只读high/high Closure Code Validator按VC-009返回PASS | 19项专项、870 tests、冻结860节点、Ruff/format/mypy、100 AST/compile、78 Schema、正式state、r16不可变终态与零调用全部独立闭合；无blocking/advisory/unknown | 恢复active；建立全新r17 Candidate，前检PASS后执行一次新授权 |
| 2026-08-25 / r17-model-business-blocked-48 | 全新Candidate完成9370 raw/122730679字节、SQLite/86 triggers、Context/Prompt/Schema/Goal、非Git隔离目录和正式state前检；执行唯一模型调用 | Git修正生效且wire Schema PASS；业务校验返回8项：1个period pattern、6个课程必需phase集、1个健康事实bpm被全局处方规则命中；没有ai-result，Provider/external action 0，正式state `7cc9f67d…`不变 | 依冻结停止规则转blocked/DIAGNOSIS_PENDING；不修改输出、不finalize、不重试，等待用户批准三层合同同步计划和新调用边界 |
| 2026-08-25 / r18-diagnosis-vc010-49 | 用户批准r18完整计划；全新只读Failure Analyst正式归因F07A/B/C | 三项均源自Prompt/wire/business不同步；没有不同根因或环境故障。VC-009下需改冻结Prompt/wire，因此由人工批准的VC-010承载；r16/r17不可变 | 冻结VC-010并交全新Contract Validator；PASS前不改生产实现、不建立Candidate、不调用模型 |
| 2026-08-25 / vc010-contract-inconclusive-50 | 全新Contract Validator返回INCONCLUSIVE且无blocking finding | 写入合同的AC-005错误残留VC-009的r17成功要求；Schema投影删除集合使用“等”造成多解。两项均与用户已批准r18原文不一致 | 按原批准计划修正映射：r16/r17永久失败；穷举十个允许删除关键词；交全新Final Contract Validator |
| 2026-08-25 / vc010-contract-pass-51 | 修正原计划映射后，全新Final Contract Validator返回PASS | AC-005明确r16/r17不可变；AC-013精确穷举十个投影删除关键词；全部标准无blocking/advisory/unknown | 状态转active；测试先行实施，Code Validator PASS前模型调用0 |
| 2026-08-25 / r18-gates-pass-52 | 先以缺少新模块取得预期红灯；完成decision/Host/Reader三层Schema、Prompt v3、wire确定性投影、Candidate/intent/receipt v3、单次Runner与内部Finalizer | 23项r18专项、275项组合回归及893项完整测试PASS；Ruff/format/mypy/compile、85 Schema、6 Skill metadata、Markdown/AI布局/隐私/Git ignore/diff门PASS；正式state仍为`7cc9f67d…`，模型/Provider/外部调用0 | 状态转validating并交全新Code Validator；PASS前不建立公开canary |
| 2026-08-25 / r18-code-validator-fail-53 | 全新Code Validator返回3项绑定VC-010的有效FAIL；其余专项和主协调门均PASS | Finalizer仍读取Candidate外Context；私人Runner缺少公开canary成功凭据；活动平均/最高心率缺活动日期 | 按批准计划只建立一个集中修正批次，不调用模型；完成后交全新Final Code Validator |
| 2026-08-25 / r18-final-gates-pass-54 | 先新增4项红灯；实现`canary-proof.json`哈希闭包、私人前检门、Candidate内receipt/result/SQLite Finalizer及活动日期后转绿 | 26项r18专项、896项完整测试、Ruff/format/mypy、105 AST、86 Schema、metadata/AI布局/Markdown/权限/隐私/Git ignore/diff门PASS；正式state与r16/r17终态不变，模型/Provider/外部调用0 | 状态保持validating；交全新Final Code Validator，PASS前不建立公开canary |
| 2026-08-25 / r18-final-validator-fail-55 | 全新Final Code Validator独立完成896 tests及全部静态门后返回FAIL | `AC-013/GATE-004`：business→wire parity完整，但Prompt只有字节SHA绑定，没有自动证明槽位、课程variants、步骤和禁用字段与Schema同构 | 依冻结停止规则转blocked/DIAGNOSIS_PENDING；不自动修补、不建立canary、不调用模型，等待用户批准小范围方案 |
| 2026-08-25 / r19-authorized-56 | 用户批准Prompt语义同构闭包与原流程续跑计划 | 保留失败版Prompt v3；拟新增Schema派生的v4语义块，VC-010不变；实施条件严格绑定Failure Analyst归因 | 保持blocked/DIAGNOSIS_PENDING并派全新只读Failure Analyst；满足三项固定条件后才实施 |
| 2026-08-25 / r19-diagnosis-and-gates-57 | Failure Analyst确认M11-V4-F08可安全自动修复；v4 Prompt语义parity实现、909 tests/静态门及全新Code Validator均PASS，随后执行唯一公开canary | canary wire通过但业务层返回`training_plan.days.day_3:anyOf`、`day_6:anyOf`；两节rest的`technique_notes=[]`违反业务Schema `minItems:1`。终态receipt SHA `a9c02a82…a760812`，模型1、私人模型0、Provider/外部调用0，正式state不变 | 依固定停止规则转blocked，不重试、不建立私人Candidate；等待用户批准是否把wire不可表达的业务约束纳入下一版自动Prompt语义 |
