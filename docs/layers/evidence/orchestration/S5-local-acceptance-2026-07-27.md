# 第五层本机受控验收记录（2026-07-27）

结论：**No-Go**。验收在 Garmin 数据质量门停止；未进入分析、邮件发送、常驻服务或生产切换。

## 验收边界

- 环境：本机开发目录
- 代码基线：`05c65c7`
- 日期窗：截至 `2026-07-26`，禁止 full
- 不启用 Supervisor、systemd、旧调度切换或并行同步
- 不删除、覆盖或清理已同步原始数据

## 已完成证据

1. `supervisor doctor`：Foundation、冻结契约、调度配置、活动主体和当前环境
   `gmail` 绑定均为 ready。
2. Gmail 只读认证探测：`gmail_mcp_authenticated`。
3. Garmin 重新认证：成功。
4. Morning 首次调用在 Garmin 增量阶段遇到旧认证失败，没有进入分析或发送邮件。
5. Morning 第二次调用暴露第五层固定 300 秒超时过短；子进程被受控终止，无残留进程，
   Garmin run 与已完成 item 均保留。
6. 使用相同下层 invocation 断点续跑成功完成。Garmin 游标推进到
   `2026-07-26`，有效回看窗为 `2026-07-12` 至 `2026-07-26`；receipt 为
   `partial`、coverage 为 `complete`。
7. 单日 audit 成功执行并形成质量证据。

## No-Go 原因

- audit 发现 40 类 `unmapped_field_signature`。这些字段尚未经过第二层字段映射或
  `known_passthrough/ignored_with_reason` 审核，不能由第五层擅自放行。
- 另有 2 条 `2025-05-11` 的 `activity_fit/fit_missing` 历史缺口。
- 当前质量门不能证明分析输入已满足发布要求，因此没有运行 daily、weekly、邮件处理、
  运维测试发信或 Supervisor 重启模拟。

## 本次产生的修正

- Garmin 下层固定超时调整为按模式设置：incremental/repair 3600 秒、audit 1800 秒、
  snapshot 900 秒、status 60 秒；full 保留 86400 秒静态上限，但本次没有执行 full。
- 超时仍由第五层固定，不开放 CLI 自定义，不创建后台线程或第二份同步。

## 后续进入条件

1. 第二层逐项审核并处理 40 类未知字段签名，不得批量假定安全。
2. 对两条相同日期 FIT 缺口确认是同一活动的重复 gap、两个不同活动，还是供应商确实
   无 ORIGINAL/FIT；不得删除本地历史数据。
3. 重新运行同一日 audit，确认目标日期窗质量门达到可接受状态。
4. 再从新的 morning workflow identity 继续 S5-19；通过前 S5-19 与 S5-20 均保持未完成。
