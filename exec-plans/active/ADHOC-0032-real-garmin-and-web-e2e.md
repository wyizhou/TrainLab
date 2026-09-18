# 执行计划：ADHOC-0032 真实 Garmin 与 Playwright Chrome Web 验收

## 对应目标

- 功能编号：ADHOC-0032。
- 功能状态：[exec]。
- 总计划对应条目：[功能总览](../../PLAN.md#功能总览)。
- 目标及范围和验收要求的引用：用户2026-09-18确认：AI模型参数先暂停；可以开始真实Garmin；Web必须使用Playwright操作Chrome测试每一个功能是否正确，不能停留在代码或curl。承接ADHOC-0031 PR #21及[真实检查失败记录](../evidence/ADHOC-0031/real-check-2026-09-18.md)。
- 范围：补受控Playwright Chrome E2E入口与实际浏览器验证；补真实Garmin客户端依赖/适配入口并做有界真实同步/下载/入库检查。AI真实Provider检查暂停，不修改`states/ai.json`，不发起真实AI请求。

## 阶段与任务

| 阶段编号 | 状态 | 预期成果 | 依赖 |
| --- | --- | --- | --- |
| G1 | [exec] | 受控Playwright Chrome E2E脚本/夹具及全功能浏览器验收 | PR #21当前代码；临时合成实例；Chrome可用 |
| G2 | [plan] | 真实Garmin客户端依赖、配置适配与最小真实同步/下载/入库检查 | G1可并行；真实`states/verification/garmin.json`；不得泄露secret |
| G3 | [plan] | 独立验证、主验收、记录与PR更新；AI暂停状态记录 | G1/G2完成或客观阻塞 |

| 任务编号 | 所属阶段 | 状态 | 输入输出及错误边界 | 依赖 | 检查方法 | 结果与证据（检查命令或人工方式、退出结果及关键证据） |
| --- | --- | --- | --- | --- | --- | --- |
| 0032-T1 | G1 | [exec] | 输入合成SQLite/状态夹具；输出Playwright用Chrome操作8080的E2E测试。必须覆盖状态卡、服务卡、活动搜索、列表选择、详情、活动报告文本安全显示、周总结、空态、错误态、API envelope与SPA fallback分离。不读取真实`states/`或secret。 | 当前前端/后端静态服务 | `npm run e2e`或等价命令实际启动本地Web并用Playwright channel=chrome；断言所有场景通过 | 待实施 |
| 0032-T2 | G2 | [plan] | 输入真实Garmin认证文件；输出产品级真实client适配和一次有界真实检查。不得打印token/secret，不绕过MFA，不猜私有HTTP；若库不能使用现有配置，应明确`AUTH_REFRESH_REQUIRED`或配置错误。 | Python依赖与Garmin库API核对 | 单元/合成回归＋真实最小list/download/import；失败有错误码和脱敏证据 | 待实施 |
| 0032-T3 | G3 | [plan] | AI暂停只记录；不补模型、不发请求。固定版本做独立验证和主验收；若真实检查未全过，不询问合并。 | G1/G2 | 全新Validator复验；主Agent核对命令、证据、Git状态 | 待实施 |

## 当前检查点

- 工作目录与分支：项目根`.`；分支`work/adhoc-0031-local-web-system`，PR #21。
- 验收要求与受验版本及未提交改动：基准HEAD `6009586`；开始本计划时工作区有本计划及PLAN更新待提交（主Agent协调记录），产品代码未改。
- 最近完成：Planner调整workflow `c28390d7-b91b-4d39-8752-9f1cbdbfbb30`完成，建议P1～P7；主Agent审核采纳为0032-T1～T3。
- 下一动作：派发全新Developer实现0032-T1/T2，AI暂停不实施。
- 暂停原因：无整体暂停；若Garmin库/凭据需要人工MFA或模型配置问题，停止对应真实检查并记录。
- 恢复条件：用户已授权Web Playwright与真实Garmin；AI恢复需另行讨论模型参数。
- PR 与交付情况：PR #21已打开；本计划新增改动后需提交推送更新PR。

## 问题记录

| 稳定问题编号 | 对应要求与实际问题 | 已尝试修法 | 累计失败次数 | 证据及处理结果 |
| --- | --- | --- | --- | --- |
| D31-LIVE-001 | 真实AI检查缺`model`配置 | 用户决定AI模型参数先暂停 | 真实检查失败1；当前暂停不修 | [真实检查](../evidence/ADHOC-0031/real-check-2026-09-18.md)；本计划不处理 |
| D31-LIVE-002 | 真实Garmin缺产品级client依赖/入口，直接探针401 | 尚未修复 | 真实检查失败1；修复0 | 本计划0032-T2处理 |
| D31-LIVE-003 | 浏览器人工8080未完成；HTTP检查不能替代Playwright Chrome | 主Agent临时Playwright探针发现可启动Chrome，但尚未形成受控测试 | 无法判断1；修复0 | 本计划0032-T1处理 |
