# Garmin FIT 解析参考

- **用途**：理解 FIT 协议、核查活动文件实际内容、比较运动类型的字段差异，为之后选择解析器和设计数据模型提供依据。
- **记录 / 复核日期**：2026-09-15。
- **资料基线**：Garmin 官方 FIT 网站；官方 FIT SDK Tools **21.214.0**（2026-08-25 发布）的 `Profile.xlsx`；官方 Python SDK 仓库提交 `f0d86b18195dbdf9c5b2f135aad5d6ae541f5fbb`。
- **性质**：对公开资料的自主概括，不是完整 Profile 副本、可执行实现或新增项目规则。下文“分析建议”不是已经批准的产品合同。
- **本轮边界**：没有读取或解析私人 FIT，没有安装或运行 SDK，没有验证 TrainLab 旧解析器。本文不包含用户活动、GPS、目标、认证或数据库内容。

## 1. 先记住的结论

1. **FIT 是可扩展的二进制消息格式，不是一张固定列数的运动表。** 除活动外，还支持课程、路线、设置及其他文件类型。[S1][S2]
2. **同为活动 FIT，不保证拥有相同字段。** 实际内容取决于运动类型、设备/固件、传感器、记录设置，以及是否执行课程或跟随路线。[S3][S4]
3. **Profile 定义“某字段是什么意思”，文件中的 Definition 定义“这一批消息写了哪些字段”。** 某字段被协议支持，不代表某文件存在；被定义也不代表有有效数值。[S2]
4. **不能只读第一条 `record`，也不能只看 `record`。** 字段可能中途出现或消失；摘要、游泳池长、力量组数、压缩心率和开发者字段各有自己的消息位置。[S3][S4]
5. **成功解码、CRC 完整和业务可用是不同结论。** 能恢复部分数据，不等于完整活动，更不证明这是真实发生过的运动。[S2][S7]

## 2. 官方资料各自解决什么问题

| 资料 | 主要用途 |
| --- | --- |
| Overview、Protocol [S1][S2] | 文件结构、消息定义、字节序、数据类型、无效值、压缩与扩展机制。 |
| Activity File [S3] | 活动文件的必需/常见消息、单运动和多运动结构。 |
| Decoding Activity Files [S4] | 先完整读取再组织 session、采样变化、游泳和压缩心率等处理思路。 |
| Durations、Date Time [S5][S6] | elapsed/timer/moving 的区别，FIT Epoch 和本地时间。 |
| Integrity、Developer Data [S7][S8] | 完整性与恢复的差别、自描述开发者字段。 |
| `Profile.xlsx` [S11] | **字段、枚举及单位的完整查表入口**；不能用网页示例代替全部字段定义。 |
| Python SDK、FitCSVTool [S10][S12] | 当前工具 API、解码选项和 CSV 行为；不同版本/语言不能机械套用。 |

### 如何查 Profile

- `Types` 工作表：查 `sport`、`sub_sport`、`file`、`event` 等枚举名称和数值。
- `Messages` 工作表：先定位消息，再查字段编号、名称、类型、数组、Scale、Offset、Units，以及 Components、Bits、Accumulate、引用字段/值和注释。
- **字段编号仅在所属消息内解释**；没有独立编号的 subfield 依赖主字段及条件，不能当成另一个直接存储字段。
- 消息顺序、字段存在性、字段有效性仍须回到具体 FIT 验证。Profile 是解释字典，不是每个文件的内容清单。

## 3. 二进制结构与解码顺序

依据 Protocol [S2]：

- 基本结构是 `File Header → Data Records → 2-byte CRC`。
- 先读取头长度；传统头为 12 字节，推荐头为 14 字节，协议允许以后扩展。不要硬编码所有文件头都等于 14。
- 头包含 Protocol Version、Profile Version、Data Size；偏移 8–11 是 ASCII `.FIT`。Data Size 不含头和末尾 CRC。
- 14 字节头可带头 CRC；头 CRC 为 `0x0000` 是允许的，不能直接判坏。末尾文件 CRC 与可选头 CRC 不是同一检查。
- **协议版本与 Profile 版本不同**：前者管编码机制，后者管消息/字段字典。新 Profile 不一定意味着新协议。

### Definition 与 Data

- Definition Message 将本地消息号绑定到全局消息类型，并声明字节序、字段编号/大小/基础类型，以及可选 Developer Fields。
- 后续 Data Message 按当前有效的 Definition 解读；字段顺序跟随 Definition，不要求字段编号递增。
- 本地消息号可在同一文件内重新定义，不是永久对应某个消息；同名消息也可有多套字段组合。
- 多字节字段按 Definition 的 architecture 解读；数组不能只取第一个元素。
- 未知 Profile 字段不应使结构完整的文件无法被遍历；但“旧解码器忽略未知内容”不等于这些内容不存在。分析时宜记录未知编号及其出现次数。

### 压缩与链式文件

- Compressed Timestamp Header 用 5 位时间信息，结合前一完整时间戳并处理 32 秒回绕；它不是“相邻两条固定差 1 秒”。
- components 可将多个逻辑值打包在一个字段中，解码器可展开为额外字段；含累积语义的组件还需处理回绕/累积。
- FIT 允许多个完整的 `header + records + CRC` 链接在一个物理文件内。游泳心率“先存后传”可能产生这种结构，不能把第一段之后的数据一律当垃圾。[S4]
- **分析建议**：区分原文件直接字段、组件展开字段、HR 合并字段与应用自行计算字段；否则会高估设备原始记录量。

## 4. Activity 文件的数据层次

按官方 Activity File 指南 [S3]，正常活动应有首条 `file_id`（`type=4/activity`，含 manufacturer）、一个 `activity`、至少一个 `session`；每个 session 应至少有一个 `lap`。`record` 被列为必需消息类型，每条要求时间戳及至少一个其他值。现实中的截断文件可能缺少尾部摘要；应披露不符合，而不是伪称全部满足。

| 消息 | 表示什么 | 核查重点 |
| --- | --- | --- |
| `file_id` | 文件类型及创建设备/平台 | `type` 是判断 Activity/Workout/Course 的依据；仅存在 `record` 或 `workout` 不能确定文件类型。 |
| `activity` | 整个活动容器 | session 数量、本地时间信息；常写在文件末尾，截断时可能缺失。 |
| `session` | 一次单运动阶段的摘要 | `sport/sub_sport`、起点和时长、距离、心率/功率等统计；字段集合随设备与运动变化。 |
| `lap` | 圈、手动/自动分段或课程阶段 | 范围、触发原因、强度、课程步骤关联；不是所有 lap 都是间歇训练。 |
| `record` | 瞬时采样 | GPS、速度、距离、心率、步频/踏频、功率等；采样可能不规则，字段也可变化。 |
| `event` | 某时刻发生的事件，可选 | 计时器开始/停止、课程步骤完成、换挡等；不是每条 event 都是 timer。 |
| `device_info` | 创建端及附件/传感器，可选 | 型号、软件版本、来源、设备索引和电量等；不保证每个字段都有。 |
| `length` | 固定长度单元，可选 | 泳池一趟或跑道等；含 active/idle 类别，不应看到 length 就认定游泳。 |
| `set` | 训练组，可选 | 次数、重量、组类型、动作类别、时间；字段见 Profile，而非仅网页常用消息表。[S11] |
| `workout` / `workout_step` | 关联的结构化课程，可选 | 课程意图及步骤不等于全部实际完成；可用 lap 的 `wkt_step_index` 关联。 |
| `hr` / `hrv` | 压缩心率 / RR 间期，可选 | `hr` 需适当展开/合并；`hrv` 的 RR 数组没有自身时间戳，不能当成逐秒 bpm。 |
| `developer_data_id` / `field_description` | 自定义字段元数据，可选 | 来源、名称、基础类型、单位及原生字段关联。 |
| `user_profile` / `zones_target` 等 | 记录时的个体参数，可选 | 可能有体重、年龄、心率等敏感信息；格式支持不等于项目允许公开或用于处方。 |

消息可能采用 **summary first** 或 **summary last** 顺序。多运动活动中，游泳、骑行、跑步甚至转换区可分别成为 session。[S3][S4]

**分析建议**：完整读取后按时间范围及有效索引组织 `activity → session → lap → length`，结合实际消息关联；不要按消息相邻顺序猜归属。`first_lap_index/num_laps` 存在时可辅助归属，缺失时须说明采用了什么时间关联方法及边界歧义。

## 5. 数值、单位与时间：容易解析错的地方

### 5.1 无效值不等于零

FIT 不同基础类型有不同 invalid sentinel。例如 `uint16` 的无效值为 `0xFFFF`，`sint32` 为 `0x7FFFFFFF`，而 `uint16z` 是零无效。应先按类型排除 invalid，再做数值换算。普通速度、功率、海拔中的零可能完全有效。[S2]

区分：**字段没有定义、字段有定义但该条无效、解码器不认识、有效值为零**。解码库可能将 invalid 省略或表示为 null；输出中没有键，不能自动证明原文件没有定义。

### 5.2 Scale / Offset 只换算一次

原生数值字段的物理值为 **`raw / scale - offset`**；未声明时无需额外变换。SDK 往往已完成换算，再做一次会把数值缩错。[S2][S12]

下表是 Profile 21.214.0 中部分字段的查表摘记，不是全部字段白名单：[S11]

| 消息.字段 | 原生物理单位 | raw 换算 / 注意事项 |
| --- | --- | --- |
| `record.heart_rate` | bpm | 无额外 scale；不等于 RR 间期。 |
| `record.distance` / `session.total_distance` | m | `/100`；record 距离通常是累计值，不是该秒增量。 |
| `record.speed` / `record.enhanced_speed` | m/s | `/1000`。 |
| `record.altitude` / `record.enhanced_altitude` | m | `/5 - 500`。 |
| `record.cadence` | rpm | 需运动语义；不是统一的“总步数/分钟”。 |
| `record.fractional_cadence` | rpm | `/128`；不能忽略小数部分后声称完整精度。 |
| `record.power` | watts | 不保证骑行或跑步都有功率。 |
| `record.temperature` | °C | 不等于已验证的室外天气。 |
| `record.vertical_oscillation` / `record.step_length` | mm | `/10`。 |
| `record.stance_time` | ms | `/10`。 |
| `record.vertical_ratio` / `record.stance_time_balance` | percent | `/100`。 |
| `record.position_lat/position_long` | semicircles | 转角度为 `value × 180 / 2^31`；不是 Profile scale 换算，先核查库是否已转为度。 |
| `session/lap.total_elapsed_time` / `total_timer_time` | s | `/1000`；整数时间戳不代表时长只能为整数秒。 |
| `session.total_calories` | kcal | 不代表每条 record 都有热量。 |
| `session.total_training_effect` / `total_anaerobic_training_effect` | Profile 未列单位 | `/10`；可记录设备给值，不能凭名称补算缺失值。 |
| `set.weight` | kg | `/16`；显示单位另有字段。 |

- `enhanced_speed/altitude` 使用更宽的基础类型；解码器也可能从旧字段展开同名 enhanced 值。不能只凭 enhanced 键存在就认定原文件直接存了它。
- Dynamic subfield 取决于其他字段。例如 running 条件下 `session.avg_cadence` 可解释为 `avg_running_cadence`（strides/min），`total_cycles` 可解释成不同运动的 strides/strokes/reps 等。先保留原单位与来源；若另算总步频，须明确转换定义，不机械将所有 cadence 乘二。
- 配速属于可推导表达，不能把 m/s 当 min/km。计算时还要注明距离来源和采用 elapsed、timer 还是 moving 时间；零距离/零速度须单独处理。

### 5.3 时间起点、本地时间及相对时间

依据 [S6]：

- 通常的 `date_time` 为从 **1989-12-31 00:00:00 UTC** 起的秒数；转 Unix 秒加 **631065600**。
- 有重要例外：值小于 **`0x10000000`** 时是相对时间；Profile 注释为设备启动后的系统秒数。不能把它硬转成 1990 年前后的活动日期。[S11]
- `local_date_time` 是本地钟面语义，不是另一个可直接当 UTC 使用的时间戳。
- 有效且对应同一时刻的 `activity.local_timestamp - activity.timestamp` 可提供当时 UTC 偏移；偏移不等于 IANA 时区名称，也不足以证明跨时区/夏令时变化过程。
- 本地时间字段缺失时标为未知；官方示例提到 GPS 查时区，但本文不因此授权地图、逆地理或外部服务。

### 5.4 三种时长与真实边界

依据 [S4][S5]：

| 时长 | 是否包含计时器暂停 | 是否包含计时器运行但人未移动 |
| --- | --- | --- |
| `total_elapsed_time` | 包含 | 包含 |
| `total_timer_time` | 不包含 | 包含 |
| `total_moving_time` | 不包含 | 不包含；移动判定可能由平台算法定义 |

- 理论关系为 **`moving ≤ timer ≤ elapsed`**；实际不一致应报告，不自动改写。
- 官方说明 moving time 在设备活动 FIT 中并不常见；平台展示的值可能自行计算，不能假定它在文件里。
- Summary 的时间跨度由 `start_time + total_elapsed_time` 定义；不要用 `start_time + total_timer_time` 代替结束时刻，也不要盲目把汇总消息的 `timestamp` 当精确边界。
- “Stop duration” 不是 Profile 字段；官方示例优先用 elapsed 减 moving，没有 moving 才减 timer。这两种口径不同，输出应注明。
- Smart Recording 会产生不等间隔；“时间戳以秒为分辨率”不等于“每秒都有完整采样”。不能仅凭采样间隙认定暂停；timer events 是另一类证据。
- **分析建议**：设备摘要与自行重算分开保留，披露采样覆盖率、空洞、暂停证据及聚合方法；不要把采样算术平均冒称时间平均。

## 6. 不同运动类型的字段差异

下表是官方 Profile 与活动指南支持的**核查方向**，不是每种运动的强制字段表，也不是用户文件统计。[S3][S4][S11]

| 类型与枚举线索 | 优先核查的数据 | 不能假定 |
| --- | --- | --- |
| 户外跑步：`running`，子类型如 `street/trail/track` | 时间、距离、速度/GPS、心率、cadence；可能有功率及垂直振幅、触地时间、步长等跑姿字段。 | 所有手表/年份都有跑姿或跑步功率；每个 lap 都是训练组。 |
| 室内跑步：`treadmill/indoor_running` | 计时、心率、设备估计的距离/速度、步频；核查传感器来源。 | 无 GPS 就无运动数据；室内距离必然来自 GPS。 |
| 骑行：`cycling`，如 `road/mountain/indoor_cycling` | 速度、踏频、功率；可能有 normalized power、左右平衡、踏板效率、功率相位、换挡事件。 | 未接功率计一定有功率；室内活动一定有路线；功率一定是直接测量而非设备估计。 |
| 泳池：`swimming + lap_swimming` | `session.pool_length`、`length_type`、每趟时长/划水数/泳姿、active 与 idle；lap 可包含多趟。 | 仅解析 record 就完整；每条 length 都代表有效游进距离；显示 yards 就表示 pool_length 原值也是 yards。 |
| 开放水域：`swimming + open_water` | record 的路线/距离与游泳摘要，另检查 hr 及链式数据。 | 必须像泳池一样有逐趟 length；心率缺席 record 就一定没被记录。 |
| 力量：`training + strength_training` | `set` 的 repetitions、weight、set_type、category/category_subtype、duration；心率与活动摘要。 | 每个文件都包含组数/重量或准确动作；用速度/距离足以描述训练负荷。 |
| 徒步/步行：`hiking/walking` | 距离、海拔升降、速度、GPS、心率；可能有 cadence。 | 所有路段有定位；由高程或 GPS 自动确定天气与地形细节。 |
| 攀岩/抱石：`rock_climbing`，如 `indoor_climbing/bouldering` | 先查看实际 session/lap/其他消息和 Developer Fields，核查时间、心率及可能的升降信息。 | 与力量训练使用相同 set 结构；必有路线难度、成功次数等专用指标。 |
| 多运动：多个 session，可能含 `transition` | 分阶段读取 sport/sub_sport、时间范围、lap 和各运动传感器。 | 一个物理 FIT 只代表一种运动；用第一个 session 类型标注全部 records。 |
| 其他运动：如划船、潜水 | 从实际 sport/sub_sport 和消息出发；潜水 Profile 另有 depth、停留时间等字段。 | 所有数据都可塞进跑步字段模型；存在某枚举就意味着本项目已经支持它。 |

泳池 `pool_length` 的物理单位是米，`pool_length_unit` 是显示单位；SWOLF、每划距离等在官方示例中由基础数据计算，不能看到平台有该指标就认定 FIT 直接存了同名值。[S4][S11]

**原因归纳**：运动类型影响字段含义；设备/固件和传感器影响能否采集；记录设置影响采样；导出平台和 SDK/Profile 版本影响可见数据。因此按“运动 + 设备/固件 + 来源 + 时期”分组，比只按运动名称分组更能解释差异。

## 7. Developer Fields、未知字段与敏感内容

- Protocol 2.0 支持 Developer Data。`developer_data_id` 标明来源，`field_description` 描述字段，再由 Definition 中的开发者索引/字段编号定位具体数据。[S2][S8]
- 自定义字段名不能当唯一全局键；不同开发者可能同名。宜连同开发者身份、所在消息、字段编号、基础类型和单位保留。
- 原生字段关联（如 `native_field_num`）并不允许再次套用原生 Profile 的 scale/offset。原生覆盖应保持原生单位，官方说明开发者数据应以适当类型记录完整精度；仍需验证元数据及数值，不能盲信名称。[S2]
- 未识别消息/字段可能来自较新 Profile、厂商专用范围或开发者扩展。不能凭数值形状猜“这是 VO₂max/训练负荷”。
- GPS、设备序列号、用户参数、名称等可能在 FIT 中；“技术上可解码”不是“可公开”。TrainLab 的私人数据限制仍以现行 [项目边界](../PLAN.md#项目已有边界与当前设计) 为准。

## 8. 工具选择与资料差异

### 官方 Python SDK

官方包名为 `garmin-fit-sdk`，导入名为 `garmin_fit_sdk`。其 Decoder 可返回按消息类型分组的数据及错误列表；不能只处理 messages 而忽略 errors。[S12]

当前 README 列有 scale/offset、日期/枚举转换、subfield/component 展开、CRC 检查及 HR 合并选项。它们影响输出形态和来源解释；字段盘点应记录 SDK 版本与选项。

**官方资料存在版本差异**：2026-09-15复核时，Get the SDK 网页 [S9] 仍称 Python 仅支持解码，但上述固定提交的 Python README 已提供 **Encoder** 与编码示例 [S12]。因此不能把“Python SDK 永远只能解码”当结论；这里只确认当前仓库文档包含编码接口，未安装、运行或证明任一已发布包具备同样能力。

### FitCSVTool

官方 Java 工具适合查看消息定义和原始字段布局，但 CSV 不天然等于原始完整采样。[S10]

- 可分别查看 definitions 和 data；只查看 definitions 无法证明有多少有效数值。
- 默认会省略 invalid；`-s` / `-se` 可显示 invalid 或空值。
- `-deg` / `-iso8601` 会改变位置/时间表示；不能对结果再重复转换。
- `-re` 可移除组件展开出的字段；原生存储与展开输出需要区分。
- **关键陷阱**：筛选消息生成的 `*_data.csv` 可能用上次值填充缺失项；官方提供 `-g` 保留掉点造成的空洞。盘点缺失率时不能把填充值当设备采样。
- `-u` 会隐藏未知数据；`-e` 的枚举标签输出不适合再转回 FIT。分析输出和无损往返不是同一目标。

本文只记录接口和选项含义，不提供已适配 TrainLab 的运行命令，也没有安装 Java 工具。

### 完整性与损坏恢复

`is_fit` 主要识别头标志，不足以证明完整性。完整性检查通常还涉及尺寸与 CRC；不同 SDK 版本方法的具体检查项应看相应实现。[S7][S12]

官方 Cookbook 允许在特定 Activity 恢复场景中读取损坏文件的可恢复部分，还示范从 records 构造缺失 session。这是**恢复策略示例**，不是所有解析必须跳过 CRC 或补造摘要的规范；本次不修改 TrainLab 的现有严格处理，也不启用恢复。

**分析建议**：将头识别、长度/CRC、解码错误、必需消息缺失、字段覆盖率分项报告；恢复值单列来源，不覆盖原 FIT，不把恢复出的 timer/elapsed 或摘要伪称设备原值。

## 9. 后续分析具体 FIT 的建议输出

以下是后续方法建议，尚未执行，也不冻结产品 Schema：

1. **文件身份与质量**：以实际字节计算的摘要标识文件，记录大小、头/协议/Profile、完整性及解码状态；不以文件名或后缀代替验证。
2. **完整消息目录**：每种消息的数量；所有 Definition 的变化；未知消息/字段及 Developer Fields。必要时区分链式片段。
3. **按 session 分类**：sport/sub_sport、设备来源、时间范围、lap/length/set 等结构；不把多运动压成一种。
4. **字段矩阵**：消息名 + 字段名/编号 + 原单位 + 来源；区分直接字段/展开/合并/应用派生，并统计定义出现、有效/无效/缺失数量与时间覆盖。
5. **按运动比较**：先列各文件实际字段，再求共同字段和差异字段；显示组内样本数、设备/年代差异，不把一份样本推广成某运动全部文件。
6. **分开报告未知**：字段缺失、Profile 未识别、设备未记录与解析器丢弃并非同义。无法区分时就标未知。

准备实跑时另确认输入范围、Python/Java 环境、依赖许可和私有输出位置。当前已有活动入口为 `states/activities/`；不连接旧 SQLite，不读取目标/凭据，不把明细盘点或 GPS 写入 references/Git，也不因本参考自动运行批量解析。

## 10. 未知项与复核条件

### 本文尚未证明

- 用户具体 FIT 的运动分布、消息/字段覆盖、CRC 状态及设备来源。
- TrainLab 现有解析器对上述字段、Developer Data、链式文件和相对时间的实际覆盖。
- 任一 SDK 在当前机器的安装、运行、性能及与目标文件的兼容性。
- Profile 未识别内容的业务含义；厂商/Connect IQ 私有字段仍可能需要对应来源说明。
- FIT 中存在某指标是否意味着 Garmin Connect 页面会采用同一数值；反向也不成立。

### 何时重新查官方资料

- 更新 SDK/Profile，遇到未知消息/枚举/字段，或更换设备/固件/导出来源。
- 改变 CRC、subfield/component、HR 合并、单位/时间转换选项。
- 网页与 SDK 再次不一致，或准备依赖编码/恢复/链式支持等具体能力。
- 将本文建议转成产品行为、数据库/Schema 或验收合同之前。

稳定的协议概念可先复用本文；字段完整列表与新增特性应按固定版本 Profile 复查，不把此文当永不过期的规范镜像。

## 官方来源

全部在 2026-09-15复核。网页正文无统一发布版本；S11/S12 使用下列版本定位。未将网页、Profile 或 SDK 完整副本纳入仓库。

- [S1] [FIT Overview](https://developer.garmin.com/fit/overview/)
- [S2] [FIT Protocol](https://developer.garmin.com/fit/protocol/)
- [S3] [Activity File](https://developer.garmin.com/fit/file-types/activity/)
- [S4] [Decoding Activity Files](https://developer.garmin.com/fit/cookbook/decoding-activity-files/)
- [S5] [Elapsed, Timer, and Moving Durations](https://developer.garmin.com/fit/cookbook/durations/)
- [S6] [Working with Date Time Values](https://developer.garmin.com/fit/cookbook/datetime/)
- [S7] [IsFIT, CheckIntegrity, and Read](https://developer.garmin.com/fit/cookbook/isfit-checkintegrity-read/)
- [S8] [Working with Developer Data Fields](https://developer.garmin.com/fit/cookbook/developer-data/)
- [S9] [Get the SDK](https://developer.garmin.com/fit/get-the-sdk/)
- [S10] [FitCSVTool Command Line Arguments](https://developer.garmin.com/fit/fitcsvtool/commandline/)
- [S11] [官方 FIT SDK Tools 21.214.0 release](https://github.com/garmin/fit-sdk-tools/releases/tag/21.214.0)，附件 [Profile.xlsx](https://github.com/garmin/fit-sdk-tools/releases/download/21.214.0/Profile.xlsx)，核查 `Types` 与 `Messages` 工作表。附件 SHA-256：`01e669a602893edf2d2bff71abefe98f977e96148832fc3f138a8359d1e569da`。
- [S12] [官方 Python SDK README（固定提交）](https://github.com/garmin/fit-python-sdk/blob/f0d86b18195dbdf9c5b2f135aad5d6ae541f5fbb/README.md)，对应提交日期为 2026-08-25；不是对所有历史/未来 PyPI 版本的承诺。
