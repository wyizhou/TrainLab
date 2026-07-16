# PostgreSQL 备份与恢复

当前 Compose 数据库服务名为 `db`，数据库、用户均为 `trainlab`。

## 备份

```bash
mkdir -p backups
backend/scripts/compose.sh exec -T db pg_dump -U trainlab -d trainlab -Fc > backups/trainlab.dump
```

备份文件包含账号和会话数据，应视为敏感信息，不提交到 Git。生产环境应使用受控存储、加密、保留周期和恢复演练。

## 恢复到空数据库

先停止后端写入，再确认目标数据库可以被覆盖：

```bash
backend/scripts/compose.sh exec -T db dropdb -U trainlab --if-exists trainlab
backend/scripts/compose.sh exec -T db createdb -U trainlab trainlab
backend/scripts/compose.sh exec -T db pg_restore -U trainlab -d trainlab --clean --if-exists < backups/trainlab.dump
backend/scripts/compose.sh exec backend alembic upgrade head
```

恢复是破坏性操作，必须核对环境、备份文件和数据库名称。恢复后检查 `/readyz`、登录和迁移版本。
