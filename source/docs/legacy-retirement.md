# 旧功能与测试退役

现行依据为[产品合同](../../docs/product-contract.md)中的RUN-VC-001、RET-001/002及A-021–023。历史VC-005、RET-004/005和M12-000系列只作来源，不再构成第二套合同。
[逐项清单](legacy-test-mapping.json)覆盖原39份测试的528个基线函数，保留原SHA、参数、循环输入、断言和例外上下文；每个保留/迁移场景指向当前实际节点及其断言摘要，取消项明确当前批准理由。
清单不是独立验收结论，也不要求永久保持测试总数。
原编号和原取消说明只保存在 `baseline_criterion_ids`、`baseline_reason` 等来源字段；当前依据以 `criterion_ids` 和当前说明为准。

| 旧范围 | 当前承接 | 退出内容 |
| --- | --- | --- |
| state、备份、raw索引 | 新SQLite事务/权限/SHA与显式只读FIT导入 | 六表执行器、原地换库、自动扫描正式旧state |
| Garmin live/rolling、有界raw | 完整FIT分页、持久预算、缓存guard、分段和细读 | 健康睡眠、GPX/TCX首层、固定私人日期批次 |
| Candidate/attempt/Coach | 独立plan后summary，各一次、真实进程监督和原capture恢复 | 单阶段新执行、日报AI、attempt链、旧批次授权 |
| 课程与展示 | 跑步固定七日、完整步骤/RPE、来源、Markdown/PDF与修订封存 | 每日改课、强制SOS、非跑步改课、HTML/CID样式 |
| Gmail | 官方REST、显式OAuth维护、原子刷新、实际ID/RAW/解码PDF与send-once | 固定8/16封、canary门、自动重发、回退渠道 |
| Garmin课程 | 精确自有ID、真步骤重复组、创建与排期读回 | 按名称认领删除、固定GTS批次 |
| resolver/auto | 统一入口、香港22:00/周日15:00、锁与恢复 | 中午槽位、旧auto提示及第二执行器 |

有来源活动BPM和session分区时长可显示，课程处方禁令仍有效；原健康RHR/HRV、GPS全词禁令不继承。
现行输出和本地修订拒绝明确凭据/邮箱/主机路径，同时允许运动地点。零值、未知与缺失分别表达。
旧成功/unknown/预算按已保存格式只读复用，不能因版本或搬迁获得新资格。

旧 formal-state Candidate 的源锁、checkpoint 和交换执行器已退出。现行显式历史导入只读核验选定归档、文件权限、完整清单与 immutable 恢复库；未声明的 WAL/SHM 和导入期间的源变化必须拒绝，不删除 sidecar，也不打开正式旧库。新实例的 writer 锁另由当前存储与发布测试验证。

邮件旧 capture 的八种损坏在清单中逐项说明：重复写预约、跨动作 capture、请求/捕获摘要、HTTP 方法、官方 URL、非成功响应、非法 ID 和数据库权限。当前 capture 只保存已验证 ID，方法和 URL 由固定工具产生；只读恢复核验唯一 Gmail 身份与实际 RAW，不重发已占用的请求。

公开退役字节及原权限已保存在忽略归档并实际恢复核对，见[归档说明](legacy-archive.md)。
字体许可和来源保留原文。新入口及活动测试必须在无旧代码、旧测试、旧归档和原仓库路径兜底的副本完成导入、同步、双进程、报告、邮件与课程、恢复和搬迁检查。

R6-5/R6-6 的实施、专项/完整本地检查、独立/Main验收及实际安装CLI离线能力证据见[M12 执行计划](../../exec-plans/active/M12-fit-weekly.md)，当前协作与交付遵循根[AGENTS.md](../../AGENTS.md)。真实模型/Provider、首次周报和正式实例切换需R7精确授权。
历史失败原文不改写；旧M9停止确认原因仍不能据新测试通过追溯判定。
