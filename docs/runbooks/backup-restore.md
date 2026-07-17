# 数据库与私有 FIT 备份恢复

当前 Compose 数据库服务名为 `db`，数据库、用户均为 `trainlab`。

## 备份

```bash
mkdir -p backups
backend/scripts/compose.sh exec -T db pg_dump -U trainlab -d trainlab -Fc > backups/trainlab.dump
```

数据库备份包含账号、会话、活动、GPS 和健康相关运动指标，应视为敏感信息，不提交到 Git。

数据库只保存原文件元数据，私有 FIT 位于独立 `trainlab-private-files` 卷。完整恢复必须在停止后端写入后同时备份该卷，例如使用受控的卷快照或临时容器归档；归档中包含原始 GPS、健康和设备数据，必须加密保存。不要只备份数据库后误认为可以重放全部导入。

## 恢复到空数据库

先停止后端写入，再确认目标数据库可以被覆盖：

```bash
backend/scripts/compose.sh exec -T db dropdb -U trainlab --if-exists trainlab
backend/scripts/compose.sh exec -T db createdb -U trainlab trainlab
backend/scripts/compose.sh exec -T db pg_restore -U trainlab -d trainlab --clean --if-exists < backups/trainlab.dump
backend/scripts/compose.sh exec backend alembic upgrade head
```

恢复私有卷时必须保持数据库 `storage_key` 对应的相对目录结构，并拒绝任何逃逸目标根目录的路径。恢复是破坏性操作，必须核对环境、数据库备份和私有卷快照属于同一时间点。恢复后检查 `/readyz`、登录、迁移版本、活动列表以及所有者原文件下载；抽查不得把内容写入日志。
