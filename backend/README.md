# TrainLab Backend

TrainLab 后端采用 Python 3.12、FastAPI、SQLAlchemy 2、PostgreSQL、Alembic 和 uv。组件基线为 v0.3，参与产品 `v0.1.0` 发布。当前实现主人账号、Cookie 会话，以及登录用户私有的本地 FIT 上传、解析、活动列表、通用详情、原文件下载、活动重命名、导入记录、可恢复删除和存储配额。佳明在线同步、TCX/GPX 后端导入、AI、公开注册和后台队列不在当前范围。

## 推荐：Docker Compose

在仓库根目录运行：

```bash
cp backend/.env.example backend/.env
backend/scripts/compose.sh up --build -d db backend
backend/scripts/compose.sh exec backend trainlab create-owner --username owner-user
```

命令会交互式读取密码，不写入 shell 历史。账号和密码都必须大于 6 位。随后访问 `http://localhost:8000/`，FastAPI 会同时提供 React 单页应用和 `/api/v1`。Compose 端口只绑定 `127.0.0.1`；v0.1.0 只支持本机 HTTP，不具备公网、TLS 或高可用边界。连接器页上传 FIT 后，运动会持久出现在运动记录和 v3.4 共用详情中。

需要验证或预置多用户隔离时，可由服务器管理员在容器内创建普通用户；该命令不开放 HTTP 注册：

```bash
backend/scripts/compose.sh exec backend trainlab create-user --username peer-user
```

## 账号运维

重置指定用户密码会使用现有 Argon2 规则，并在同一事务中撤销该用户全部会话：

```bash
backend/scripts/compose.sh exec backend trainlab reset-password --username owner-user
```

只撤销会话而不改变密码：

```bash
backend/scripts/compose.sh exec backend trainlab revoke-sessions --username owner-user
```

自动化可使用 `--password-env`，但环境变量必须由受控 secret 注入，不能把明文密码放入参数、日志或仓库。CLI 成功、输入错误、未知用户和数据库失败分别使用退出码 0、2、3、4。登录的凭据验证与会话插入、密码重置和会话撤销均通过同一用户行锁串行化，管理命令不会遗漏已经验证但尚未提交的并发登录会话。进程内登录限流不会被数据库密码重置清除；已触发锁定时可安全重启 backend，详见 `docs/runbooks/local-development.md`。

Compose 将数据库写入 `trainlab-db`，将私有 FIT 原文件写入独立的 `trainlab-private-files` 命名卷。应用只用服务端生成的用户/导入 UUID 存储键，不使用上传文件名拼路径。

默认每个用户最多登记 5 GiB、10,000 个原文件，分别由 `TRAINLAB_USER_STORAGE_MAX_BYTES` 和 `TRAINLAB_USER_STORAGE_MAX_FILES` 调整；两者必须为正整数。单文件 50 MB 限制优先于用户配额。上传使用用户隔离的 `.staging` 临时目录、同用户数据库行锁和原子提升，重复 SHA-256 不重复计费。

查看状态与日志：

```bash
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
backend/scripts/compose.sh logs -f backend
backend/scripts/compose.sh exec backend trainlab reconcile-storage
```

`reconcile-storage` 默认只报告超过宽限期且没有数据库引用的生成文件数量和字节数，不输出路径。确认数据库与私有卷已经取得同一时间点备份后，才可显式清理：

```bash
backend/scripts/compose.sh exec backend trainlab reconcile-storage --apply
```

默认宽限期为 60 分钟，由 `TRAINLAB_STORAGE_STAGING_GRACE_MINUTES` 配置。命令会按用户取得数据库行锁，避免删除合法的在途上传文件。

可执行双卷备份和恢复入口：

```bash
mkdir -p backups
chmod 700 backups
python3 backend/scripts/backup_release.py --project trainlab --output backups/trainlab-v0.1.0
python3 backend/scripts/restore_release.py --project trainlab --backup backups/trainlab-v0.1.0 --confirm RESTORE:trainlab
```

恢复是破坏性操作；工具会先校验 manifest、SHA-256、PostgreSQL dump 和 tar 安全边界，恢复后撤销所有旧会话。完整流程、加密保存要求和回滚策略见 `docs/runbooks/backup-restore.md`。

停止服务并保留数据库与私有原文件：

```bash
backend/scripts/compose.sh down
```

只有明确准备同时清空数据库和私有原文件时才使用 `down -v`。

## 本机开发

需要 Python 3.12、uv 与 PostgreSQL。先创建测试库并配置 `TRAINLAB_DATABASE_URL`，然后：

```bash
cd backend
uv sync --frozen --extra dev
uv run alembic upgrade head
uv run trainlab create-owner --username owner-user
uv run uvicorn trainlab.main:app --reload --port 8000
```

本机开发默认把私有原文件写入 `backend/data/private`，可用 `TRAINLAB_PRIVATE_STORAGE_ROOT` 改为受控目录。该目录不得由前端静态服务直接暴露，也不得提交到 Git。

前端开发服务器运行于另一个终端，Vite 会把 `/api` 代理到后端：

```bash
npm --prefix frontend ci
npm --prefix frontend run dev
```

## 验证

```bash
backend/scripts/check.sh
backend/scripts/compose.sh --profile test run --rm backend-test
python3 backend/scripts/test_release_backup_tools.py
npm --prefix frontend run e2e:fullstack
```

`check.sh` 在本机有 uv 时执行格式、静态检查、类型检查和测试；没有 uv 时自动使用 Compose 测试环境。测试数据库名必须以 `_test` 结尾，防止误清理开发或生产库。

FIT 导入限制为单文件 50 MB；同一用户按 SHA-256 幂等，用户之间不共享导入记录。解析状态支持 `complete`、`partial`、`failed` 和安全重试；同文件重传可以恢复 pending/陈旧 processing，新鲜 processing 返回冲突，异常状态不会返回空活动的伪成功。删除会先进入可恢复状态，再幂等删除原文件并硬删数据库导入；失败可由同一 DELETE 重试。解析 attempt 通过 token 和行锁隔离，旧解析不能覆盖删除状态或复活活动。私有存储读取同时校验 key 中的用户 UUID 与当前所有者。API 契约与运维说明见 `docs/api/` 和 `docs/runbooks/`。
