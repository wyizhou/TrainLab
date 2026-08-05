# TrainLab 更新记录

本文件采用只追加、不覆写历史条目的维护方式。每次代码、配置、运行行为或部署方式发生更新时，都必须在末尾增加一条带日期的记录。

## 2026-08-05：修复容器 PID 耗尽导致的定时任务失败

- 现象：香港时间 09:00 的 morning workflow 在 Garmin `current_snapshot` 阶段返回 `process_start_failed`。
- 根因：容器 PID 上限为 512，检查时已使用 508；共有 437 个由 PID 1 未回收的僵尸进程，其中 401 个来自 Node。cgroup 已记录 69 次 PID 上限命中。
- 关联现象：`gmail-mcp` 的 Node 子进程生成了 core dump；该崩溃发生在 morning workflow 失败约 47 分钟后，不是 morning 的直接失败步骤，但与进程资源压力一致。
- 代码修复：Linux 下的 Gmail MCP stdio 客户端在启动 `npx` 前启用 child subreaper；MCP 进程运行在独立进程组，关闭时终止整个进程组，并回收被收养的后代进程，避免其继续成为 PID 1 下的僵尸进程。
- 安全处理：`core` 与 `core.*` 已加入 `.gitignore`，防止可能包含内存敏感信息的崩溃转储进入 Git。
- 恢复要求：现有僵尸进程无法由 TrainLab 回收，部署修复版本前必须重启当前容器一次；重启后再验证 PID 数、morning workflow、Gmail MCP 和 Supervisor lease。

### 验证记录

- Gmail/MCP 相关针对性测试 49 项通过。
- Ruff 致命错误检查、Python 编译检查、仓库质量门和 Git diff 检查通过。
- 当前 Linux 环境已确认支持并成功启用 child subreaper。
- Supervisor 已停止，避免容器重启前继续消耗剩余 PID 配额。
