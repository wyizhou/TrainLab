# TrainLab Backend

TrainLab 的后端基础采用 Python 3.12、FastAPI、SQLAlchemy 2、PostgreSQL、Alembic 和 uv。当前只实现系统存活检查、主人账号初始化和基于安全 Cookie 的登录会话；运动数据、佳明同步、文件上传、AI 与公共注册均未接入真实后端。

## 推荐：Docker Compose

在仓库根目录运行：

```bash
cp backend/.env.example backend/.env
backend/scripts/compose.sh up --build -d db backend
backend/scripts/compose.sh exec backend trainlab create-owner --username owner-user
```

命令会交互式读取密码，不写入 shell 历史。账号和密码都必须大于 6 位。随后访问 `http://localhost:8000/`，FastAPI 会同时提供 React 单页应用和 `/api/v1`。

查看状态与日志：

```bash
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
backend/scripts/compose.sh logs -f backend
```

停止服务保留数据库：

```bash
backend/scripts/compose.sh down
```

只有明确准备清空本地数据时才使用 `down -v`。

## 本机开发

需要 Python 3.12、uv 与 PostgreSQL。先创建测试库并配置 `TRAINLAB_DATABASE_URL`，然后：

```bash
cd backend
uv sync --frozen --extra dev
uv run alembic upgrade head
uv run trainlab create-owner --username owner-user
uv run uvicorn trainlab.main:app --reload --port 8000
```

前端开发服务器运行于另一个终端，Vite 会把 `/api` 代理到后端：

```bash
npm --prefix frontend ci
npm --prefix frontend run dev
```

## 验证

```bash
backend/scripts/check.sh
backend/scripts/compose.sh --profile test run --rm backend-test
```

`check.sh` 在本机有 uv 时执行格式、静态检查、类型检查和测试；没有 uv 时自动使用 Compose 测试环境。测试数据库名必须以 `_test` 结尾，防止误清理开发或生产库。

API 契约与运维说明见 `docs/api/` 和 `docs/runbooks/`。
