# 第五层本机部署基线与切换边界（2026-07-31）

结论：**本机观察基线可继续，远程生产切换仍未获授权。** 本记录描述当前代码与
本机单 Supervisor 的部署边界，不是 S5-19 真实副作用验收，也不是 S5-20
生产 Go。

2026-07-27 的
[本机受控验收 No-Go](S5-local-acceptance-2026-07-27.md) 仍是当时 Garmin
数据质量门的有效历史证据。本记录不删除、不覆盖，也不宣称已经消除其中的 40 类
未知字段签名和两条 FIT 缺口。它只取代“当前仓库没有可运行 Supervisor”或“当前
launchd 已退役”这类已经过时的实现描述。

## 本次范围

- 只修改并验证本机仓库；未安装、启用或切换远程服务器服务。
- 变更前唯一的本机 Supervisor 已被精确识别并正常请求停止，修改和测试期间没有
  第二个调度者。
- 最终发布后只恢复一个脱离终端的本机 Supervisor，并做一次进程、lease、状态和
  日志权限确认；之后不持续监控。
- 未通过本记录新增真实 Garmin、Gmail 或 Codex 业务副作用，也未删除数据库、原始
  数据、凭据或历史验收材料。

## 当前运行与验证模型

1. `foundation status` 只读取 ready marker、受支持 Schema 版本和固定路径/权限，
   不打开 SQLite。对当前约 3.7GB 数据库的实测耗时为约 0.774 秒。
2. `foundation verify` 和 Supervisor 启动时的幂等 `foundation init` 保留完整
   Schema、迁移收据、`PRAGMA integrity_check` 与外键验证。它们可能扫描大数据库，
   不能用作每分钟健康轮询。
3. 每次健康周期只运行 SQLite readiness；完整 integrity/foreign-key 检查在首次
   观察或距上次记录至少 24 小时时运行。
4. workflow 失败 incident 使用稳定键去重。后续成功只恢复仍为 `open` 且
   `error_code=workflow_execution_failed` 的严格匹配项：
   - mail：同一 subject 的更早失败；
   - health-check：同类更早失败；
   - morning/weekly：终态失败不由 scheduler 自动重做；已审计的人工 `retry`
     保留原失败 run，追加带 parent 引用的新 manual run。新 run 成功后只恢复同一
     subject、同一逻辑日期的更早失败。
5. `acknowledged`、`suppressed`、安全、数据质量、其他错误类型或较新的失败不会
   自动关闭。一次成功会分页处理全部严格匹配项，不以 200 条静默截断。恢复通知
   使用独立幂等投递键；通知失败不撤销已经持久化的恢复状态。

## 已完成的本机证据

- Foundation 快速/深度路径、恢复边界和健康深检节流的针对性回归通过。
- workflow incident 的 subject、逻辑日期、状态、类别、错误码和先后顺序筛选回归
  通过；Supervisor 的 open/recovery 通知分流与既有字符串兼容回归通过。
- 当前 Linux 容器上的完整离线测试套件通过；只排除了必须由 macOS `plutil`
  执行的 LaunchAgent 文件。S5-06 真实子进程测试在清理旧字节码并兼容容器 PID 1
  不回收 zombie 的宿主语义后通过，仍然保持“只把可执行成员视为存活”的严格边界。
- 冻结契约哈希、本地 Markdown 链接、邮件模板同步、Ruff、mypy、compileall 和
  `git diff --check` 全部通过。macOS LaunchAgent 由 CI 的独立 macOS job 覆盖，
  不冒充本 Linux 容器的本地实测。
- Git 提交/推送标识和本机 Supervisor 的单次启动验活属于交付时运行证据，由最终
  交接记录单独报告；它们不扩大本基线为远程生产 Go。

## 仍然保留的门禁

- 远程 systemd 模板没有在本次变更中安装或启动。大数据库启动仍包含完整只读
  bootstrap，因此模板的启动时限必须在目标服务器受控验收中实测，不能由本机结果
  推断。
- 2026-07-27 Garmin 数据质量问题、S5-19 真实端到端验收和 S5-20 生产切换均保持
  未完成。未来服务器部署仍需单独授权、备份、唯一调度者证明和回滚窗口。
- macOS 当前支持的是唯一 label 的单 Supervisor LaunchAgent；退役的是旧下层独立
  launchd/多服务调度，不是当前 `deploy/launchd` 资产。
