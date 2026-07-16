# 本地开发运行手册

## 首次启动

```bash
backend/scripts/compose.sh up --build -d db backend
backend/scripts/compose.sh exec backend trainlab create-owner --username owner-user
```

输入大于 6 位的密码后打开 `http://localhost:8000/`。重复以相同用户名初始化是幂等操作；若已有主人账号，系统会拒绝创建第二个。

## 常用诊断

```bash
backend/scripts/compose.sh ps
backend/scripts/compose.sh logs -f backend
curl -i http://localhost:8000/healthz
curl -i http://localhost:8000/readyz
```

`healthz` 正常但 `readyz` 失败，通常代表数据库未启动、连接配置错误或迁移未完成。应用容器启动时会先自动运行 `alembic upgrade head`。

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

该命令保留命名卷。`backend/scripts/compose.sh down -v` 会永久删除本地 PostgreSQL 数据，只能在明确需要重建环境时使用。
