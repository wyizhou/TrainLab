# M12 周任务受限 FIT 细读

这是内部 Python 数据接口，已连接本地单工具 MCP；完整真实周流程尚未交付。
沿用[新解析器](fit-parsing.md)，不导入旧每日细读器、旧库或归档。

## Host 与 AI 的边界

Host 在模型启动前使用 `freeze_scope(instance_root, period_end, members)`，冻结本次周任务
的活动引用和 FIT SHA；该接口不是模型工具。每项活动都须在新库登记、原字节闭合并通过解析，
按结束时间落入香港时间周日15:00至下周日15:00的半开窗口。
周任务 Builder 负责选择本期全部活动，本模块负责绑定并限制可细读范围，不能把“范围已冻结”
说成“完整周 inventory 已核验”。同周范围不能通过重新打开 Host 改写或获得新预算。

模型工具只可映射预绑定的 `DetailHost(..., stage="plan"|"summary").read(request)`：
两阶段共享本周scope、20次/1200秒及原缓存；plan仅允许完全属于跑步session的窗口。
混合FIT中的非跑步或跨运动窗口即使已有summary缓存也拒绝；授权检查先于缓存返回。

| 请求字段 | 接受的内容 |
| --- | --- |
| activity_ref | 当前冻结范围的一项活动 |
| view | summary、laps 或 series |
| start_offset_seconds / end_offset_seconds | 相对该活动起点的整数秒，正长度且不越界 |
| resolution_seconds | 1 或 5；series 的统计窗口，不代表设备真实采样频率 |

不接受文件名、路径、SQL、命令、GPS 参数或额外字段。实例位置、周截止点和范围 SHA
只能由 Host 配置，不能由模型请求指定。

## 预算、失败和恢复

- 默认每周最多20个不同的合法请求，单次最长1200秒；使用现有新库 writer lock 串行领取。
- 调用前先持久化 intent，再做本地解析。成功或已完成的失败响应均缓存；重复请求返回原结果。
- 改变活动、范围、视图或粒度属于新请求。非法或范围外请求不读取 FIT、不领取预算。
- 进程在 intent 后退出，已有请求保持计数；重新执行只完成同一只读请求，不再扣一次预算。
- 正常解析错误只返回固定的 detail_read_failed，不暴露文件路径或异常原文；结果写入失败不假装成功。
- 搬迁后的同一实例沿用原账本。已缓存响应返回前仍复核 FIT 和解析来源，漂移时停止。
- 20个请求上限约束的是本地细读；模型启动次数和实际可用工具还须后续 AI Adapter 单独验收。

## 输出与落库

scope、intent、result 是现有 documents 表中的版本化 weekly_input 文档，使用独立 detail 前缀；
不新增原始逐秒记录表，不改变现有存储 Schema。每项结果绑定 scope、request、活动和 FIT SHA。

新版 `fit_detail_v2` 使用本地 `fit_activity_v2` Schema；旧 scope 继续生成 v1，均不联网解析引用。
v2 表示为 `time_weighted_bins_with_actual_location_endpoints`：每个窗口包含真实点数、有效秒数、各指标覆盖率、
距离和配速。若设备每10秒记录一次，1秒统计窗口可能没有实际点；不会声称生成了新的实测值。
圈段视图保留 work/recovery 等设备角色，截取了部分圈段会明确标记 clipped_lap。
多个 session 分开输出，不把中间空档补成运动。v2 另给窗口内首尾实际定位点、时间及缺失信息，
不平均、插值或把定位端点说成完整路线。无原 FIT 字节、无关个人/设备标识或凭据。
GPS 是返回事实，不是允许模型指定任意地理资源的第六个参数；五参数与预算保持不变。

[细读测试](../tests/code/contract/test_m12_fit_detail.py)覆盖范围/类型、预算、同请求缓存、
真实进程退出、并发最后一次额度、结果事务失败、SHA漂移、跨目录重放、圈段截取和多运动空档。
所有输入均为合成，未发生模型或业务 Provider 调用。
