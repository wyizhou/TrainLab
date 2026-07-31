# 第五层受控验收与生产切换门禁

本文只定义验收步骤，不授权安装服务、访问真实供应商、发送邮件或切换生产调度。

## 受控真实环境验收（S5-19）

开始前必须由项目所有者单独确认真实副作用范围，并满足：

- Shadow 对账为 `matched`，完整离线测试通过；
- 当前环境存在名称为 `gmail`、包为 `@artymclabin/gmail-mcp` 的已认证服务；
- Garmin 已认证，只使用最多三天的已结束日期窗，禁止 full；
- 收件人来自项目固定配置，不接受命令行覆盖；
- 旧调度保持运行，新 Supervisor 不启用定时领取。

按顺序人工触发并保存脱敏 receipt：一次 morning、一次 Sunday、一封带 TrainLab
标签的测试邮件、一次计划修订、一种 deferred、两种 delivery unknown/reconcile、
一次 Supervisor 重启模拟及一封运维告警。每项必须记录 workflow、invocation、
artifact/delivery ID 和是否产生外部副作用。未知发送结果先 reconcile，禁止重发。

任一身份、日期、receipt 或幂等证据不一致，立即停止；保留数据库、原始数据和审计
记录，不删除、不覆盖。

## 生产切换（S5-20）

只有在受控验收全部通过并再次获得明确切换授权后才能执行：

1. 备份数据库、状态目录和当前服务配置，并验证可读。
2. 停止旧调度，证明没有旧进程、timer、cron 或第二个 lease owner。
3. 安装但暂不启用 Supervisor；运行 `supervisor doctor`。
4. 启用唯一 Supervisor，观察 morning、weekly、mail、health-check 各一个周期。
5. 核对没有重复同步、artifact、计划或邮件。

Go/No-Go 任一项失败时停止新 Supervisor，恢复旧调度和原配置；保留第五层运行、
incident 和 delivery 审计记录。回滚不删除已同步 Garmin 原始数据。

## 当前交付状态

代码、离线测试、Shadow 工具、systemd 模板、部署和回滚步骤可在开发环境完成。
真实 S5-19 与 S5-20 是显式授权的部署操作，不属于普通代码开发的默认权限。
当前本机运行模型和仍保留的门禁记录在
[2026-07-31 本机部署基线](../layers/evidence/orchestration/S5-local-deployment-baseline-2026-07-31.md)；
该记录不会把 2026-07-27 No-Go 或远程生产切换改写为 Go。
