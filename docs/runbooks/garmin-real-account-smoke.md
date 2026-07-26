# Garmin L2-18 受控真实账号 Smoke Runbook

本 runbook 只用于已获得书面授权的受控 Garmin 测试账号。它不授权生产切换、扩大
日期范围、修改 Garmin Connect 云端内容、关闭 legacy 或启用第五层调度。

## 先决条件与停止条件

开始前必须由账号/迁移负责人登记以下信息，但登记文件只保存受控 ID、日期和 SHA-256：

1. 明确的 `authorization_id`、批准的六个 mode 清单和新加坡日期窗；
2. E-01～E-04 已满足，尤其是 legacy 备份证据 hash 与只读 shadow 对账窗口；
3. 独立的测试根、已验证的回滚步骤、不会打印 payload 的终端/日志环境；
4. 命名操作员、凭据权限检查和 legacy 独立运行证据均已登记，canonical owner 明确
   保持不变；
5. 单一新加坡日期窗覆盖一至十四天，并且是健康与活动的共同起点；另选择一项已上传的
   代表性活动。L2-18 不执行 `full`，也不以它作为授权或验收前提。

本次实际 smoke 的批准窗固定为**三个完整日**，健康与活动使用同一共同起点；evidence
框架仍允许已书面批准的一至十四天窗口。

`full` 的全历史活动 inventory 语义仍由其他离线开发章节和对应测试定义；它不属于本
受控真实 smoke，短日期窗不得借由任何 mode 扩大为全历史访问。

任一条件未满足、身份不匹配、收到非预期权限提示、429 超过内联等待、出现敏感输出、
或任何命令离开批准窗时，立即停止：不扩大重试，不切换 canonical，保存脱敏 receipt
hash 与安全错误码，执行回滚并交由总控处理。

## 操作顺序

1. 在隔离根分别创建 legacy 与 Garmin 数据/状态备份，完成隔离恢复校验；将完整备份、
   恢复 receipt 和双方快照 hash 组成一个脱敏证据包，只在 smoke evidence 中登记该包
   的 SHA-256。确认 legacy 路径仍独立运行。
2. 在不回显 token、账号、URL 或原始响应的环境完成认证。每项操作记录受控
   invocation ID、run ID、request/receipt Schema 校验结论与 SHA-256、状态和退出码，
   绝不复制 receipt 正文。证据 ID 使用随机不可承载文本的固定格式：
   `authz-<32 lowercase hex>`、`inv-<32 lowercase hex>` 和 Garmin 实际
   `gr-<UUID>`；`auth`、`status` 不创建 Garmin run，因此其 `run_id` 必须为 null。
   运行中实时进度只能写到 stderr，且每行仅含 `stage`、`index`、`mode`、`status` 和
   `duration_seconds`；结束时 stderr 仅追加 `total_elapsed_seconds`。不得向 stderr 或
   stdout 打印 receipt、request、数据、ID 以外的响应内容或任何 payload。
3. 仅在批准的共同新加坡日期窗内，按固定八次顺序运行：`auth`、`incremental`、重复
   `incremental`、`snapshot`、重复 `snapshot`、`repair`、`audit`、`status`。不执行
   `full`。`auth`、`status` 不创建 Garmin run，因此其 `run_id` 必须为 null。
4. 对一项已上传活动，只检查布尔结构：summary、FIT、segments、samples、enrichment
   是否存在。不得记录活动 ID、GPS、传感器、健康值、文件路径或 FIT 内容。
5. 检查一个健康资源 capability，只登记状态 `available`、`not_available`、
   `not_enabled` 或 `not_supported`，不登记 resource payload。
6. 对 `incremental` 和 `snapshot` 都立即以相同请求重跑；分别记录 first/repeat 两个
   受控 run ID 与 request/receipt hash，确认每一对 request hash 相同且 repeat 为 no-op。
7. 扫描 receipt、日志和运行表输出是否含凭据或完整 payload；检查临时 ZIP 已删除；
   检查进程退出后无 daemon、后台线程、timer 或监听端口。执行并登记回滚演练。

每项 operation 记录非负有限的 `duration_seconds`，顶层记录非负有限的
`total_elapsed_seconds`。后者是从第一 stage 开始到最后 stage 结束的端到端耗时，允许
包含本地阶段间记账；因此不得小于八项 duration 合计（最多 0.05 秒十进制舍入差）。

## 生成并验证脱敏证据

证据 JSON 只能含 [`garmin_smoke_evidence.schema.json`](../../harness/schemas/garmin_smoke_evidence.schema.json)
的字段。它只保存受控 run ID、日期、状态、布尔结论、整数退出码、计时秒数和 SHA-256；不得含
账户、邮件、token、错误原文、raw/JSON、FIT、健康值、GPS、活动 ID、路径或日志。

在**不调用 Garmin**的验证步骤中执行：

```bash
.venv/bin/python scripts/verify_garmin_smoke.py --evidence /secure/path/garmin-smoke-evidence.json
```

该脚本只读取给定证据 JSON 和仓库 schema，绝不执行 `trainlab garmin`、不读取配置、
token、数据库或 raw 文件。输出仅为 `passed/failed` 与受控错误码。证据 hash 是删除
`evidence_sha256` 后的 canonical JSON SHA-256。

验证器还会要求 prerequisites 全部为真，包括 E-01～E-04、命名操作员、备份恢复、
shadow 窗口、legacy 独立性、凭据权限、`bounded_activity_window_verified` 和
`canonical_owner_unchanged`；并直接比较 incremental 与 snapshot 两组 no-op 的 mode 与
request hash，同时校验八项 stage duration 与端到端 total elapsed 的关系。

通过不等于可切换生产：必须由总控核对 E-01～E-04、L2-18、G-05 和 G-06 的全部证据。
