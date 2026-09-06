# 一周一次的模型任务账本

这是 M12 内部 Host 组件，不是可以直接运行的周报命令，也没有启动 Codex。
它复用新 SQLite 的不可变 documents，解决“进程不记得上次做过什么”的问题。

## 状态与恢复

| 已保存的证据 | 本次可以做什么 |
| --- | --- |
| 本周还没有 intent | 输入前检后，在短事务中登记 intent；提交并释放数据库锁后调用 adapter 一次。 |
| 已有 intent，但没有完整 capture | 返回 unknown，不再启动 adapter。原进程可能仍在运行，也可能已中断。 |
| 已有完整 capture，但 SQLite 尚未记录结果 | 重新核对内容和绑定、补持久化屏障，再补账；不调用模型。 |
| 已有终态 | 核对 capture、账本和当前输入；复用成功或明确失败，不产生重复输出。 |

普通 `run` 仍严格遵守上表，不会在原 intent 上重新调用 adapter。Host 另外提供显式
`recover` 路径：只能从已经确认停止且完整保存的进程证据恢复结果，再经过同一输入、
输出和业务校验与不可变补账。当前 Codex 本地接线见[结果恢复](codex-recovery.md)。
这里的恢复不是 `codex exec resume`，没有继续聊天或第二次模型调用。

intent 与真正启动之间中断，可能实际上一次模型也没调用，但仍不会自动补跑。
这里保证的是“最多启动一次”，不是“无论什么故障都保证成功”。不能从一个空结果推断
“肯定没启动过”。未知状态不会抢写永久失败，以免阻止仍在运行的原任务正常落账。

本周逻辑键不包含输入摘要；换提示、目标、Schema 或 adapter 绑定不能获得第二次机会。
摘要绑定完整输入、输出 Schema、预绑定细读范围和 adapter profile。路径和 PID 不进入
业务身份，实例搬迁后仍是原任务。

## 适配接口与校验职责

`model_job.run` 必须同时接收 Host 的输入校验器、结果业务校验器、输出 JSON Schema
及 adapter。没有可省略的“直接相信 AI”默认路径。

- 输入前检先于 intent；Schema 引用限定在同一资源内部，不通过验证器联网解析。
- adapter 接收输入副本、[预绑定 DetailHost](fit-detail.md)和结果 Schema 副本。
  Host 不持有新库 writer.lock 等待 adapter，因此该任务内部的细读可以正常记账。
- adapter 必须确认自身子进程已经停止，才能正常返回或抛普通异常。
  无法确认终止时必须使用 `AdapterInterrupted`；它不会被写成一个已确定的失败终态。
- 可序列化的返回 JSON 即使业务校验失败，也保留在 owner-only capture 中作为失败证据；
  不把它作为成功结果向下游返回。adapter 异常只记固定错误码，不把异常正文写入账本。
  非 JSON 原始日志仍由未来具体 adapter 保存，本组件不会编造这些日志。
- 成功结果须通过 JSON Schema 和调用方的业务校验，重放时也重新核对。
  本组件并未实现训练目标解析、周报证据规则或课程安全校验，不能将它的成功视为
  这些未接入部分已经完成。

`FakeAdapter` 与未来模型 adapter 使用同一接口，但明确标为 `fake`，只供合成验收。
它不是模型不可用时的生产回退。`adapter_attempts` 是一次性领取数；`model_attempts`
对 fake 为 0，对模型 adapter 为保守的启动机会计数，不冒充服务端实际请求数。
`provider_calls=0` 与 `external_actions=0` 指此 Host 不执行 Garmin/Gmail 等业务动作。
具体模型进程的真实请求/错误证据仍须由后续 adapter 独立记录。

## 持久化与边界

capture 在实例内 `model-results/<周标识摘要>/capture.json`，目录 0700、文件 0600。
它先经临时文件、fsync 和原子改名发布，再以短事务写入结果 document。成功、明确失败、
恢复均使用相同不可变结果，不覆盖历史。不从 `.pending-*` 猜测一个已经完成的模型结果。

capture 缺失、损坏、宽权限、链接或与账本不一致时拒绝成功，且不重新调用模型。
有限写入失败保留当前证据；已发布 capture 的恢复再次执行文件和目录 fsync。
永久主机故障、恶意同 UID/root 不扩展为应用层绝对保证。

代码回归：[test_m12_model_job.py](../tests/code/contract/test_m12_model_job.py)。
测试使用合成 FIT、新实例和 Fake adapter；包含真实进程退出、并发领取、细读锁、
持久化失败、损坏结果和搬迁重放，不读取正式数据或启动真实模型。
