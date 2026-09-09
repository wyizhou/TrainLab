# R2 两阶段周任务接线

这是已实现的内部 Host 接线，不是可直接上线的完整教练命令。业务 Schema、课程和证据校验见 [R3 周报](weekly-coaching.md)；本地输出见 [R4 周报](weekly-reports.md)，真实发布仍由后续模块实现。这里没有生产空校验器或 Fake 回退。

## 调用与恢复

`weekly_stages.run(root, period_end, *, plan, summary, validate_history)` 接收两份
`StageContract(response_schema, validate_result, prepare_adapter, recover=None)`。
`prepare_adapter(payload, scope_sha256)` 仅在该阶段从未领取 intent 时调用；
`recover(payload, scope_sha256)` 是可选的本地恢复回调，不得启动模型。已成功/失败结果先直接
走同一个 model_job 恢复路径，未知时才调用恢复回调，并重新读取账本，不相信回调的成功宣称。
执行与恢复均必须通过原 Schema 和 `ResultValidator(output, payload)`，无默认业务验证器。

| 阶段 | 输入 | 细读权限 | 失败时 |
| --- | --- | --- | --- |
| plan | 本周 running session、最多四份成功历史中的独立跑步分析/计划、目标快照、Host 日期 | 仅完全落在跑步 session 内的窗口，缓存命中前也核验 | 不冻结总结输入、不创建总结 intent |
| summary | 本周全部运动、最多四份完整成功 M12 历史、原目标和本次已验证固定计划 | 本周全部冻结运动 | 保留计划，report 为 null，publishable 为 false |

两阶段各最多一次无状态调用，分别保存输入、request/intent/capture/result。它们共享原周 scope、
20 次细读预算、每次 1200 秒及同请求缓存，失败细读和中断预留不退还；阶段、路径、版本和重启不清零。
`model_job.run/recover(..., stage="plan"|"summary")`、`codex_adapter.prepare/recover`、
`Runtime.stage` 和 stdio 的 `--stage` 必须一致。新启动的能力证明绑定同一阶段的运行身份。
旧无 stage 记录只能读取/本地恢复；缺少原 intent 不可新建，旧周被占用不转换为两阶段新额度。

## 冻结与来源

`weekly_context.freeze` 保留原 v1/v2 保存格式，作为内部全周原料冻结能力，不再是单阶段模型入口。
`stage_context` 生成 `fit_weekly_stage_input_v1`，模型前重新核验原料、Schema 和精确投影。
规划不含全运动统计、未知无 FIT 清单、混合历史全文或整个 FIT 的混合位置/活动名称。
混合 FIT 只包含 running session 的摘要/圈段/分段；保留 FIT SHA、原点时间与 session 身份用于细读，
不增加运动分类或计算算法。单独非跑步活动和全周审计摘要不影响规划 payload。
混合 FIT 的原字节 SHA 仍是来源标识，不能为了让摘要不变而伪造 SHA。

总结固定计划绑定本周、计划 request/capture/result SHA 与原结果内容；冻结总结输入前和模型前
都验证原成功计划，不能换用另一周计划。合并结果永远采用原计划，不接受总结改写。
无跑步时运行列表为空，不造跑步证据或旧课。晚到活动和目标/历史编辑不改写原周快照。

## R3 共享接口与历史

总结业务 Schema 必须声明顶层独立 `running_analysis` 必填字段；其内部训练结构及逐项来源由 R3 业务校验。
合并结果 `running` 固定为 `{analysis: summary.running_analysis, plan: 原plan结果}`。
完整历史 `fit_weekly_history_v2` 从原两阶段 request/capture/result 重新验证这两个字段和 SHA；
Host 的历史 ResultValidator 按保存阶段/格式分派，不猜字段，不从混合自由正文提取。
旧 `fit_weekly_history_v1` 无这一独立来源结构，只进入总结，不整篇传给规划。
R2 只验证结构、来源、顺序与不可替换；`publishable` 是已通过所提供业务合同的合并状态，
不是邮件/PDF/Garmin 已发送，也不证明自由文字语义或真实训练已验收。

回归：[两阶段](../tests/code/contract/test_m12_weekly_stages.py)、
[阶段细读/真实 stdio](../tests/code/contract/test_m12_stage_detail.py)、
[无归档闭包](../tests/code/contract/test_m12_resource_closure.py)。
