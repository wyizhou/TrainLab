# M12 FIT 解析与分段

这是内部离线模块，不是已启用的同步、AI 或发布入口。只消费新实例登记的 FIT，
不依赖旧 SQLite、旧 AI、旧归档或测试目录。

## 输入、存储和重放

`skills._shared.fit_weekly.fit_parse.parse_registered(db, instance_root, activity_ref, fit_sha)`
核对新库、活动绑定、相对路径、文件权限/大小/SHA 和 FIT CRC，再生成
`fit_activity_v1`。结果经[严格 Schema](../skills/_shared/schemas/fit_activity_v1.schema.json)
校验，按 FIT SHA 与 `fit-summary-1` 解析版本写入不可变 `parses`；原始秒级点不落库。
同输入重放不增加记录；事务失败不发布部分解析。实例搬迁不改变业务身份。

输出包含活动和 session 起止、设备摘要、程序摘要、圈段、分段、覆盖率和局限。
多运动 FIT 的 session 分开解析；跨 session 或重叠圈段不用于 SOS 分类。
没有可用记录点时保留设备摘要，不把设备整场平均数复制成每段数据。

## 分段规则

| FIT 实际证据 | 分段 |
| --- | --- |
| 跑步，不能明确识别质量结构（包含无明确标签的 Easy） | 固定 2 分钟；类型记 unknown，不猜 Easy/SOS |
| 完整相邻圈段含明确 interval/work 和 recovery/rest | 保留每个 work/recovery 及热身/放松圈段 |
| 完整热身、唯一明确 interval/work 主段、放松，无 recovery | 连续主段每 1 分钟；保留热身/放松 |
| 其他运动，包括徒步、攀岩、力量 | 固定 5 分钟 |

FIT `active` 只表示活动阶段，不自动等同 SOS。缺失、重复、交叉或不覆盖全程的圈段
不能用于猜测间歇结构；仍保留合资格事实，回到普通时间分段。

## 时间与数值方法

- 经过时长来自 session 起止。设备 timer 总量单独保存。
- 有效时间来自完整 timer 事件；无 timer 事件但设备 timer 与经过时长一致时可确认无暂停。
  只有短于经过时长的 timer 总量、缺少暂停位置或事件冲突时，有效时间及暂停位置标未知。
- 连续指标采用前一个有效采样值在相邻采样之间的有效时间加权，不做按点简单平均。
  每项指标分别记录覆盖秒数；min/max 指参与这些有效时间区间的样本极值，不冒充设备整场极值。
- `fit-summary-1` 的确定性采样上限为相邻 30 秒；更长间隔不填充，记为缺口。
  这是解析质量规则，随输出的方法元数据公开，不是训练阈值。
- 距离只使用非递减的相邻距离样本；跨暂停的距离增量无法准确分配，整对不用于距离或配速。
  同一无暂停样本对跨分段边界时可按时间比例拆分。距离回退、缺失和覆盖秒数均披露。
- 配速 = 有距离证据的有效秒数 × 1000 / 对应米数，不平均设备瞬时配速。
  部分覆盖的距离是“有证据部分”，不是整场总距离；整场设备距离保留在 provider_summary。
- sample_count 包含区间两端可用的真实样本；边界样本可被相邻段共同引用，因此不相加求全场点数。
  加权时长及距离不重复计算。
- fitdecode 已按 FIT profile 解码单位。步幅为 mm、触地时间为 ms、垂直振幅为 mm，
  不重复缩放；设备 cadence 保持 rpm，不擅自转换成总步数/分钟。

## 隐私与设备分区

解析逐字段投影，不保存原始 record 字典。GPS、坐标、路线、活动/Workout 名称、
个人和设备序列号不进入解析结果。原始 FIT 继续只留在私有实例。

仅展示唯一 `time_in_zone` 且 `reference_mesg=session`、session index 可绑定的
`time_in_hr_zone` 有效时长向量；保留设备原始位置，不自行改写成五区定义。
lap/split 向量不替代 session。重复、错误索引、无效值、零总量或超过 session 有效总量
的向量隐藏，不从心率采样重新计算；百分比标记 `derived_from_provider_duration`。
结果绑定活动引用和 FIT SHA，不产生目标 BPM 或分区处方。

## 测试对应

[合成 FIT 工厂](../tests/code/fixtures/m12_fit_factory.py)生成真正 CRC 合法的二进制；
[解析回归](../tests/code/contract/test_m12_fit_parse.py)覆盖实际解码、时间加权、暂停/缺口、
边界分摊、Easy/未知/SOS/其他运动、多 session、圈段/分区冲突、单位、字段剔除、
Schema 白名单、SHA/CRC、事务失败、重复执行和实例搬迁。
所有测试只用公开合成值，业务 Provider 和模型调用均为 0。
