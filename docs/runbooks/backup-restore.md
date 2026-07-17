# v0.1.0 数据库与私有 FIT 备份恢复

TrainLab 的完整用户数据分布在两个持久卷：PostgreSQL 保存账号、会话、活动和解析结果，`trainlab-private-files` 保存可重放的私有 FIT 原文件。只备份其中一个不能形成可恢复版本。

本流程仅支持本机 Docker Compose。备份和恢复制品包含账号、GPS、健康指标、设备信息和原文件，必须存放在加密介质或受控的加密备份系统中，不得提交到 Git、放入公开同步目录或粘贴到日志和工单。

## 创建同一停写点备份

从仓库根目录执行，并为每次备份使用一个尚不存在的新目录：

```bash
python3 backend/scripts/backup_release.py \
  --project trainlab \
  --output backups/trainlab-v0.1.0-before-change
```

工具会：

1. 检查 Compose 项目和迁移头为 `0003_activity_data_lifecycle`。
2. 若 backend 正在运行，先停止 backend，阻止新的 API 写入。
3. 确认私有源卷已经存在；缺失时立即失败，不会让 Docker 静默创建空源卷。
4. 在同一停写窗口生成 PostgreSQL custom dump 和私有卷 tar 归档。
5. 由宿主创建权限为 `0600` 的制品并接收容器 stdout；容器不能直接写宿主备份目录。
6. 最后生成 `manifest.json`，记录产品版本、迁移头、UTC 时间、相对文件名、字节数和 SHA-256。
7. 成功或普通失败后恢复此前正在运行的 backend；重启失败时保持明确报错，需先检查日志。

备份目录权限为 `0700`，三个制品为 `0600`。manifest 不包含密码、Cookie、本机绝对路径或健康数据摘要，但数据库和 FIT 归档本身仍是高度敏感数据。工具只处理由它新建的目录；失败时会删除不完整目录，不会覆盖既有备份。

## 校验并破坏性恢复

恢复会覆盖指定 Compose 项目的数据库和私有文件卷。先保留当前环境的完整双卷备份，再使用精确确认字符串：

```bash
python3 backend/scripts/restore_release.py \
  --project trainlab \
  --backup backups/trainlab-v0.1.0-before-change \
  --confirm RESTORE:trainlab
```

工具在停止或写入任何服务前完成：manifest 严格 schema、产品版本、迁移头、相对文件名、普通单链接文件、尺寸、SHA-256、tar 路径穿越/链接/特殊文件/重复项，以及 PostgreSQL custom dump 预检。任一校验失败都不会开始破坏性恢复。

确认和预检通过后，工具按以下顺序执行：停止 backend → 恢复数据库 → 清空并恢复私有卷 → `alembic upgrade head` → 核对迁移头 → 删除全部已有登录会话 → 启动并等待 backend ready。恢复失败会让 backend 保持停止，避免对外提供数据库与私有卷不一致的服务；修正原因后可用同一已验证备份重新执行。

恢复后所有旧 Cookie 都会失效。用当前密码重新登录，并检查：

```bash
curl --fail http://localhost:8000/readyz
backend/scripts/compose.sh exec backend trainlab reconcile-storage
```

随后人工抽查活动列表、详情、存储用量和原文件下载。`reconcile-storage` 默认只读；确认恢复点完整且已另存恢复前备份后，才可运行 `--apply`。

## 发布回滚

含用户数据的版本只通过发布前取得的同停写点双卷备份回滚。Alembic downgrade 可用于隔离迁移测试，不能替代数据回滚；只回退代码或只恢复数据库都会造成数据库、解析结果和原文件不一致。

推荐顺序：

1. 在发布前运行备份工具并把整个目录复制到加密介质。
2. 完成版本变更后验证 readiness、登录和核心 FIT 旅程。
3. 需要回滚时停止使用当前环境，保留故障现场双卷备份。
4. 切回与目标备份兼容的代码，再运行恢复工具。
5. 使用新会话完成列表、详情、下载 SHA-256 和重复启动验证。

## 隔离恢复演练

发布门禁使用仓库内合成 fixture，并强制限制为专用 Compose project；它会创建并最终删除自己的数据库和私有卷：

```bash
python3 backend/scripts/test_release_backup_tools.py
python3 backend/scripts/drill_release_restore.py \
  --project trainlab_release_v010_u2_local \
  --host-port 18103
```

演练覆盖上传 → 备份 → `down -v` 全毁 → 恢复 → 旧会话 401 → 新登录 → 列表/详情/用量/下载 SHA-256 → 重建 → 重复创建 owner 不重复数据。项目名必须使用脚本规定的隔离前缀，不能指向默认 `trainlab` 项目。

## 保留与销毁

在线删除不会追溯修改离线备份，已经删除的用户数据可能仍存在于旧备份。必须为备份建立独立的访问控制、保留期限和安全销毁规则；删除 manifest 不能视为删除数据库 dump 或 FIT 归档。
