# FIT 汇总时间与精度

默认解析版本 `fit-summary-3` 使用 session/lap 的 `start_time + total_elapsed_time`
确定结束时间，支持汇总消息在采样之前或之后。汇总 `timestamp` 不参与结束时间计算；
record 与 timer event 的 `timestamp` 仍表示采样或事件发生时间。经过时长必须是有限正数，
不以 timer 时长、汇总 timestamp 或采样范围替代缺失值。

当前生产读取库锁定为 `fitdecode==0.11.0`，不是 Garmin 官方 SDK；启用严格 CRC 与解析错误
检查，读取库已按 Profile 缩放的字段值，业务层不重复除以 scale。官方独立对照采用
[`garmin-fit-sdk 21.214.0` 的 Profile](https://github.com/garmin/fit-python-sdk/blob/21.214.0/garmin_fit_sdk/profile.py)
（commit `f0d86b18195dbdf9c5b2f135aad5d6ae541f5fbb`），入口说明见
[Garmin FIT SDK](https://developer.garmin.com/fit/overview/)。SDK 仅用于独立验收，不替换生产依赖。
该版本引用本身不代表已通过 SDK 解码对照，实际结果由独立验收记录给出。

该 Profile 的 session/lap 字段 7、8 分别为 `total_elapsed_time`、`total_timer_time`，
均为 uint32、scale 1000、offset 0、单位秒；经过时长包含暂停，timer 时长不包含暂停。
字段 2 `start_time` 与字段 253 `timestamp` 为 date_time/uint32、scale 1、offset 0。
按这些字段语义，用开始时间加经过时长确定汇总区间；不能用 timer 时长确定结束位置。
CRC 校验仅检查文件完整性，字段尺度、事件与派生统计仍须独立对照。

`fit-summary-3` 对 record 的现用数值（包括距离）先读取文件中的有效原字段；速度和海拔
沿用增强字段优先、普通字段回退的顺序。仅在原候选字段缺失或无效时使用合法组件值，
避免普通字段或压缩字段展开的同名值遮住原增强值或显式距离，不受字段排列顺序影响。
组件的缩放和距离累计仍由读取库完成，业务层不重复转换。`fit-summary-1/2` 保留原有
字段选择及重放结果。匿名官方 Encoder 夹具和原字段对照见
[字段来源回归说明](../tests/code/fixtures/m12_fit_field_sources.md)及
[永久回归](../tests/code/contract/test_m12_fit_field_sources.py)。

整秒开始时间与毫秒时长相加可能使相邻圈略有重叠、末圈略超出 session。仅有唯一
session 归属、正常顺序且差值严格小于 1 秒的圈允许精度相容，保留公式给出的原端点，
并标明 `lap_time_precision_compatible`。这是依据字段精度采用的实现边界，不是 FIT
官方规定的容差。重复圈、同起点、跨 session、逆序精度冲突及大于等于 1 秒的重叠仍披露
`laps_conflicting`。间隙不填补，非完整分区不据此推断 SOS 类型。

圈统计只使用所属 session 的采样和有效时间；共有交界点归后一个 session。圈细读按
请求及 session 边界裁剪，保留 `clipped_lap` 与精度相容标志。timer event 的整秒端点
不被移动；其有效时间与设备 timer 总时长相差不到 1 秒时标明
`timer_total_precision_difference`。这类差值不能据此断言发生了对应长度的真实暂停。

FIT 的 UTC 时间允许小数秒，周归属以精确结束时间落入左闭右开周窗口为准；活动按时间值
排序。调度、授权开始和截止仍使用原整秒 UTC 合同。v3 细读支持有限、非负、最多三位
小数的秒偏移，可读取不足一秒的尾段；每次不超过 1200 秒，resolution 仍只能为整数
1 或 5。周共享 20 次额度、阶段权限、同请求缓存及越界拒绝保持。

活动、细读、传输与周证据增加 v3 Schema；周上下文增加 v3 身份，阶段输入使用 v2 Schema。
报告、发布及动作账本格式不升级。v1/v2 的解析、Schema、冻结周、scope、缓存及未缓存
细读按原版本重放，新解析以同一 FIT SHA 和新版本追加，不改写旧快照或返还预算。
v2/v3 都保留有来源的 GPS、活动名称和原隐私过滤。
报告仅投影既有 methods 字段；v3 的时间依据进入报告现有 limitations，并为圈段精度相容
及设备计时差异提供文字说明，保持冻结 FIT 输入和报告 Schema 不变。

毫秒请求另有 `fit_detail_request_v2` 与独立工具定义指纹；旧工具定义仍只用于原材料恢复。
新工具定义的合成夹具证明代码绑定与拒绝边界，不声称已完成新版本的真实 CLI 能力探针。
当前新模型启动仍需与运行源码和工具指纹匹配的能力证据，旧证明不能自动升级。

回归见 [时间边界合成测试](../tests/code/contract/test_m12_fit_time_bounds.py)。测试不读取
私人 FIT、目标或凭据，也不调用模型、Garmin 或 Gmail。
