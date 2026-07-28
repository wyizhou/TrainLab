# macOS 本机单 Supervisor 部署

本机只运行一个用户级 LaunchAgent：`com.trainlab.orchestrator-supervisor`。它的唯一长期命令是固定的
`.venv/bin/trainlab supervisor run`；不会创建 Garmin、分析或邮件层自己的 timer、daemon 或轮询进程。

## 发布前检查

在项目根目录完成已批准的离线测试、`trainlab supervisor doctor`、Garmin 状态检查和 Gmail MCP
绑定检查。确认当前 Codex 环境已注册启用名为 `gmail` 的 MCP，且使用 `@artymclabin/gmail-mcp`。
不要把 token、密码、邮箱地址或配置内容写入 plist、日志或发布记录。

安装脚本会把安装时当前受控环境中可用的绝对 PATH 目录写入 LaunchAgent；下层只继承清理后的 `PATH` 与 locale，不继承 HOME、token、密码或其他凭据环境变量。Gmail 仍通过当前环境的 `gmail` MCP 解析，不绑定机器专属的 npx 路径。

## 安装与启动

安装前确认旧的 TrainLab 调度入口已经停止。首次安装执行：

```sh
./deploy/launchd/install-local-supervisor.sh
```

若经过审查后替换同一 label，执行：

```sh
./deploy/launchd/install-local-supervisor.sh --replace
```

脚本仅写入 `~/Library/LaunchAgents/com.trainlab.orchestrator-supervisor.plist`，随后由当前登录用户的
launchd bootstrap 并 kickstart。无需 sudo，也没有 shell wrapper。标准输出和错误日志分别位于项目的
`logs/supervisor.launchd.out.log` 与 `logs/supervisor.launchd.err.log`。

## 人工观察、停止与回滚

用 `launchctl print gui/$(id -u)/com.trainlab.orchestrator-supervisor` 确认服务已加载；再通过
`trainlab orchestrate status --json`、Supervisor 日志、唯一 lease 和收据观察运行。不要同时手工运行第二个
Supervisor。

计划停止或回滚时先停止服务：

```sh
./deploy/launchd/uninstall-local-supervisor.sh
```

该操作只卸载并删除这一个 LaunchAgent 文件；不会删除日志、数据库、原始健康数据、FIT 文件或凭据。修复根因并通过离线与只读检查后，再安装已验证版本。若出现未知的下层结果，先执行既有 reconcile 流程，不要重发或假定失败。
