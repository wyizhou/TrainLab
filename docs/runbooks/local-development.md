# 本地开发运行手册

## 首次启动

```bash
backend/scripts/compose.sh up --build -d db backend
backend/scripts/compose.sh exec backend trainlab create-owner --username owner-user
```

输入大于 6 位的密码后打开 `http://localhost:8000/`。重复以相同用户名初始化是幂等操作；若已有主人账号，系统会拒绝创建第二个。

首次上传 FIT 时 Compose 会创建两个持久卷：`trainlab-db` 保存数据库，`trainlab-private-files` 保存私有原文件。容器重建不会删除卷；上传后可重建 `backend` 容器，再刷新运动记录验证数据和下载仍可用。

## 常用诊断

```bash
backend/scripts/compose.sh ps
backend/scripts/compose.sh logs -f backend
curl -i http://localhost:8000/healthz
curl -i http://localhost:8000/readyz
```

`healthz` 正常但 `readyz` 失败，通常代表数据库未启动、连接配置错误或迁移未完成。应用容器启动时会先自动运行 `alembic upgrade head`。

FIT 导入问题先按请求返回的稳定 `code` 判断。`partial` 可以重试；`failed` 会保留原文件供重放；超过配置时限的 `processing` 可安全恢复；原文件丢失会落为 `failed/raw_file_unavailable`，不会永久卡在处理中。日志和工单中不得粘贴 GPS、健康数据、设备序列号、原文件或服务端存储路径。

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
