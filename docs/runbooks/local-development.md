# 本地开发运行手册

## 首次启动

```bash
backend/scripts/compose.sh up --build -d db backend
TRAINLAB_DEV_PASSWORD=useradmin backend/scripts/compose.sh exec -T \
  -e TRAINLAB_DEV_PASSWORD backend trainlab set-development-owner \
  --username useradmin --password-env TRAINLAB_DEV_PASSWORD
```

本手册是开发默认凭据规则与安全边界的权威来源：账号 `useradmin`，密码 `useradmin`。账号和密码均必须大于 6 位，验证码输入登录页右侧显示的 4 位数字。这是一组公开、仅供本机开发使用的凭据，禁止用于 `production`、公网、共享主机或任何可被其他设备访问的环境；不得复制到生产 secret、镜像或日志中。

`set-development-owner` 仅在 `TRAINLAB_ENVIRONMENT=development` 时可运行。全新数据库会创建唯一 owner；已有数据库会保留原 owner UUID、活动、导入记录和私有文件归属，在同一事务中更新用户名和 Argon2 密码哈希并撤销全部旧会话。目标用户名被其他用户占用或事务失败时会完整回滚。命令可重复运行以恢复开发默认凭据，不会创建第二个 owner。Compose 只把应用绑定到 `127.0.0.1:8000`；这是本机 HTTP，不具备公网暴露、TLS 或高可用边界。

首次上传 FIT 时 Compose 会创建两个持久卷：`trainlab-db` 保存数据库，`trainlab-private-files` 保存私有原文件。容器重建不会删除卷；上传后可重建 `backend` 容器，再刷新运动记录验证数据和下载仍可用。

## 常用诊断

```bash
backend/scripts/compose.sh ps
backend/scripts/compose.sh logs -f backend
curl -i http://localhost:8000/healthz
curl -i http://localhost:8000/readyz
```

`healthz` 正常但 `readyz` 失败，通常代表数据库未启动、连接配置错误、迁移未完成，或私有存储根不可访问/不可写。readiness 的临时写探针不会把存储路径返回给客户端，也不会留下永久探针文件。应用容器启动时会先自动运行 `alembic upgrade head`。

## 密码恢复与会话撤销

忘记本地登录密码时，在服务器终端重置指定用户；默认使用隐藏交互输入，并同时撤销该用户全部既有会话：

```bash
backend/scripts/compose.sh exec backend trainlab reset-password --username useradmin
```

自动化场景可由受控环境变量传入，不要把明文密码写在命令参数、脚本、日志或 Git 中：

```bash
backend/scripts/compose.sh exec -T -e TRAINLAB_NEW_PASSWORD backend \
  trainlab reset-password --username useradmin --password-env TRAINLAB_NEW_PASSWORD
```

只撤销全部会话而不修改密码：

```bash
backend/scripts/compose.sh exec backend trainlab revoke-sessions --username useradmin
```

重复撤销是幂等操作。`create-owner`、`create-user`、`reset-password` 和 `set-development-owner` 均执行账号和密码大于 6 位的统一规则；非 development 环境还会拒绝开发主人账号命令。密码重置和会话撤销在同一数据库事务中完成；登录从凭据验证到会话插入持有同一用户行锁，因此管理命令要么先于登录读取凭据，要么在登录提交会话后再统一撤销，不会遗漏命令执行前已经验证、执行后才写入的会话。任一步失败不会留下“新密码但旧会话仍有效”的部分状态。登录失败限流是 backend 进程内状态，若重置前已触发临时锁定，可在确认没有在途请求后运行 `backend/scripts/compose.sh restart backend` 清除该失败窗口；该操作保留数据库和私有卷。

恢复旧备份会同时恢复备份时的用户名和密码哈希。恢复完成后如需继续本机开发，应重新运行本节开头的 `set-development-owner` 命令，再用 `useradmin / useradmin` 登录。

FIT 导入问题先按请求返回的稳定 `code` 判断。`partial` 可以重试；`failed` 会保留原文件供重放；超过配置时限的 `processing` 可安全恢复；原文件丢失会落为 `failed/raw_file_unavailable`，不会永久卡在处理中。`storage_quota_exceeded` 只表示当前用户已登记字节数或文件数达到配置上限；`delete_incomplete` 可通过重复同一 DELETE 恢复。日志和工单中不得粘贴 GPS、健康数据、设备序列号、原文件或服务端存储路径。

查看和清理崩溃残留：

```bash
backend/scripts/compose.sh exec backend trainlab reconcile-storage
backend/scripts/compose.sh exec backend trainlab reconcile-storage --apply
```

第一条只审计；第二条才会删除超过 `TRAINLAB_STORAGE_STAGING_GRACE_MINUTES` 且无数据库引用的生成文件。运行 `--apply` 前先备份数据库和私有卷，并确认没有正在执行的维护任务。命令按用户取得行锁，合法在途文件不会被清理。

完整双卷备份、破坏性恢复和发布回滚命令见 `docs/runbooks/backup-restore.md`。不要手工只备份 PostgreSQL 后将其当作完整恢复点。

## 数据库迁移

```bash
backend/scripts/compose.sh exec backend alembic current
backend/scripts/compose.sh exec backend alembic upgrade head
backend/scripts/compose.sh exec backend alembic downgrade -1
```

生产或含真实数据的环境在降级前必须先备份并评估迁移是否可逆。

## 停止与清理

```bash
backend/scripts/compose.sh down
```

该命令保留两个命名卷。`backend/scripts/compose.sh down -v` 会永久删除本地 PostgreSQL 数据和所有私有 FIT 原文件，只能在明确需要重建环境且已完成备份时使用。
