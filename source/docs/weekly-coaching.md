# R3 周报与固定跑步课程

本模块提供内部业务校验和供后续渲染使用的只读报告。没有新增产品命令、模型执行器、发布器或调度器；Markdown/PDF 与本地修订见 [R4 周报输出](weekly-reports.md)，Gmail 和 Garmin 发布仍由后续模块实现。

## Schema、Prompt 和 Host

`coaching_contract.schema(stage)` 从 `fit_running_plan_v1`、`fit_sports_summary_v1` 业务 Schema 读取结构，总结的证据结构引用计划 Schema。运行时展开局部引用以适配现有 wire 深度限制，`wire(stage)` 仍只调用 `codex_output.wire_schema`。两份 Prompt 的机器说明由同一业务 Schema 生成，`check(stage)` 对照完整内容，不允许手工维护另一个字段答案。新增版本必须保留已保存版本的明确只读策略；不得把未知格式默认接受。

`codex_adapter.files` 对这两份明确业务版本检查 Schema 和 Prompt，再从原冻结 payload 生成 `HOST_FACTS`；规划只生成跑步统计，不带全运动计数或无 FIT 清单。日期、周期和原始指标是 Host 事实，不由模型回显。运行依赖显式列入 `runtime_resources`，无归档、测试目录或旧业务 Schema 扫描。

## 课程结构与校验

计划是七个按周一至周日排序的槽位，模型不能写日期。`coaching_plan.project(output, payload, *, root)` 校验后由 Host 绑定原冻结日期。休息槽位的 workout 为 null；跑步包含目的、总剂量、步骤/重复组、每步 RPE、技术备注、停止条件。同一课程的剂量按米或秒记，所有重复步骤精确合计；不从时长推算距离。

长跑、节奏、间歇或明确 hard 的步骤计为硬负荷；结构中的 hard_load 必须与这些选择一致，最多三次，槽位日期差至少三天。不设置心率或医学强度阈值。SOS 需要有经过来源校验的跑步或目标依据、解释和适用条件，可以首次引入，不要求过去已有 SOS 标签；其训练合理性仍需要语义审查。

比较仅使用紧邻上一周且格式明确的固定跑步计划，来源 SHA 和“计划不等于实际完成”方法显式保留。逐项比较完整距离、硬课次数、主观峰值 RPE、硬课总秒数/米数。任一已知强度维度上升且距离上升即拒绝；单位不一致、基准缺失或未知保持 unknown。某项持平不能证明整体强度没有增加，报告保留方法与这一局限。不新增百分比增长标准或强制 SOS 门槛。

## 全运动总结与证据

总结含核心结论、独立 running_analysis（概览、最多三项技术、简短计划比较）、每个非跑步 session 的说明、数据局限与安全说明。Host 另提供完整全运动清单/统计及唯一原计划，共同组成七部分报告。每个引用逐 activity、FIT SHA、session、字段及原值核验；未知不填造证据。技术解释明确观察方法、适用条件、覆盖/缺失局限；不提供自行计算技术数值的自由接口。

running_analysis 使用重新投影的跑步视图核验，不能引用非跑步活动或混合历史正文。细读证据只能取本周已有成功 intent/result，核对请求 SHA、scope、FIT SHA、session 和窗口；复验不调用 DetailHost.read，不读取 FIT、不补缓存，不新增预算。其他运动仍进入总结，但不能修改或产生另一份计划。

Host 展示已记录的历史心率和 session 分区时长，不用它们生成未来 BPM/区间或阈值处方。明确禁止、缺失说明与停止条件不因包含“心率”“不补课”而被拒绝。结构、来源和有限的明显处方/替代语句检查不能证明任意自由文字、目标解释或训练合理性；不增加第三次生产模型调用，运动表现也不证明没有健康风险。

## 原执行器与只读接口

- `coaching.validator(root, *, legacy=None)` 返回首次结果、恢复和历史共用的 `ResultValidator(output, payload)`。旧政策键是 `(已保存 stage 或 None, 输入版本, 输出版本或 None)`，必须明确提供；没有默认空校验器或未知版本回退。
- `coaching.stage_contract(root, stage, prepare_adapter, *, recover=None)` 组装原 StageContract，适配器由调用方明确提供。
- `coaching.codex_contracts(root, end, *, runtimes, capability_paths, legacy=None)` 使用现有 Codex 适配器和能力证明，返回 plan、summary、history validator。Runtime 的 stage 和同源 prompt_prefix 必须匹配；没有隐式认证、探针或调用授权。
- `weekly_stages.run` 保持原 `fit_weekly_stages_result_v1` 的保存格式和唯一计划绑定；失败/unknown、细读预算及耐久恢复仍走原 model_job。
- `coaching.report(root, end, *, legacy=None)` 从两阶段原请求/捕获重新校验后返回 `fit_coaching_report_v1`，并通过其明确 Host Schema。报告包括日期计划、原模型计划/总结和组合报告 SHA；不重写原输出，不发布内容。R4 应只消费该重新验证结果。旧 R2 组合格式继续按原接口可读，但不会被冒充为这个新版完整报告。

检查使用公开合成夹具：[课程](../tests/code/contract/test_m12_coaching_plan.py)、[证据](../tests/code/contract/test_m12_coaching_evidence.py)、[同源合同](../tests/code/contract/test_m12_coaching_contract.py)、[两阶段与无归档搬迁](../tests/code/integration/test_m12_coaching_stages.py)。测试不读正式目标、state、FIT 或凭据，不调用真实模型和业务服务。
