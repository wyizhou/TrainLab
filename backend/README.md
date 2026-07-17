# TrainLab Backend

TrainLab 后端采用 Python 3.12、FastAPI、SQLAlchemy 2、PostgreSQL、Alembic 和 uv。当前实现主人账号、Cookie 会话，以及登录用户私有的本地 FIT 上传、解析、活动列表、通用详情和原文件下载。佳明在线同步、TCX/GPX 后端导入、AI、公开注册和后台队列不在当前范围。

## 推荐：Docker Compose

在仓库根目录运行：

```bash
cp backend/.env.example backend/.env
backend/scripts/compose.sh up --build -d db backend
backend/scripts/compose.sh exec backend trainlab create-owner --username owner-user
```

命令会交互式读取密码，不写入 shell 历史。账号和密码都必须大于 6 位。随后访问 `http://localhost:8000/`，FastAPI 会同时提供 React 单页应用和 `/api/v1`。连接器页上传 FIT 后，运动会持久出现在运动记录和 v3.4 共用详情中。

需要验证或预置多用户隔离时，可由服务器管理员在容器内创建普通用户；该命令不开放 HTTP 注册：

```bash
backend/scripts/compose.sh exec backend trainlab create-user --username peer-user
```

Compose 将数据库写入 `trainlab-db`，将私有 FIT 原文件写入独立的 `trainlab-private-files` 命名卷。应用只用服务端生成的用户/导入 UUID 存储键，不使用上传文件名拼路径。

查看状态与日志：

```bash
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
backend/scripts/compose.sh logs -f backend
```

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
npm --prefix frontend run e2e:fullstack
```

`check.sh` 在本机有 uv 时执行格式、静态检查、类型检查和测试；没有 uv 时自动使用 Compose 测试环境。测试数据库名必须以 `_test` 结尾，防止误清理开发或生产库。

FIT 导入限制为单文件 50 MB；同一用户按 SHA-256 幂等，用户之间不共享导入记录。解析状态支持 `complete`、`partial`、`failed` 和安全重试；同文件重传可以恢复 pending/陈旧 processing，新鲜 processing 返回冲突，异常状态不会返回空活动的伪成功。私有存储读取同时校验 key 中的用户 UUID 与当前所有者。API 契约与运维说明见 `docs/api/` 和 `docs/runbooks/`。
