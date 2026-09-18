# ADHOC-0031 B0 Developer 报告

## 摘要

已完成 ADHOC-0031 B0 / 0031-T1、0031-T2 的最小可检查工程底座：

- 新增 `source/` 产品工程骨架。
- 新增 Python 公共合同模块：路径、私有配置引用、UTC/北京时间调度、错误外壳、SQLite Schema、内存会话和 Web 静态目录安全合同。
- 新增目录 A 对应位置：`source/skills/_shared/scripts/`、`source/skills/local-web/scripts/`、`source/skills/local-web/web/`、`source/frontend/`、`source/tools/README.md`。
- 新增 B0 级 Python/Node 测试和静态合同检查。
- 未读取 `states/ai.json`、未读取私人 FIT、未写 `states/data.db`、未启动定时器、未调用真实 Garmin 或 AI Provider。

## 修改文件

B0 本轮新增/修改：

- `source/README.md`
- `source/pyproject.toml`
- `source/trainlab/__init__.py`
- `source/trainlab/py.typed`
- `source/trainlab/contracts/__init__.py`
- `source/trainlab/contracts/config.py`
- `source/trainlab/contracts/errors.py`
- `source/trainlab/contracts/paths.py`
- `source/trainlab/contracts/schema.py`
- `source/trainlab/contracts/session.py`
- `source/trainlab/contracts/time.py`
- `source/trainlab/contracts/web.py`
- `source/skills/_shared/scripts/contracts.py`
- `source/skills/local-web/scripts/server.py`
- `source/skills/local-web/web/index.html`
- `source/skills/local-web/web/assets/main.css`
- `source/tools/README.md`
- `source/tools/check_b0_static.py`
- `source/frontend/package.json`
- `source/frontend/scripts/build.mjs`
- `source/frontend/src/app-contract.mjs`
- `source/frontend/tests/app-contract.test.mjs`
- `source/tests/__init__.py`
- `source/tests/contracts/__init__.py`
- `source/tests/contracts/test_b0_contracts.py`
- `exec-plans/evidence/ADHOC-0031/developer-b0-report.md`

工作区还存在主Agent协调记录未提交改动：`PLAN.md`、`MEMORY.md`、`exec-plans/active/ADHOC-0024..0028`、`exec-plans/active/ADHOC-0031-local-web-system.md` 及既有规划证据；这些不属于本轮 B0 产品实现范围。

## 合同覆盖

- D31-01：`activity_fit_name()` 固定 `YYYYMMDD-SHA256.fit` / `unknown-SHA256.fit`；`initial_sync_window()` 固定首次最近七天。
- D31-02：`AI_CONFIG_CONTRACT` 和 `ai_config_reference()` 只公开 `states/ai.json` 路径与字段合同，不读取/打印秘密。
- D31-03：`next_activity_report_run_utc()` 固定中国时区每日 4 点；`NO_ACTIVITY_WEEKLY_SUMMARY` 固定为 `本周无任何运动记录`；`InMemoryConversationHistory.persistence_target` 固定为 `None`。
- Schema：四张业务表仍为 `activities`、`records`、`activties_report`、`weekly_report`；新增 `config` 仅为系统参数表，不计入业务表。
- Web：静态目录固定为 `source/skills/local-web/web`，`validate_static_mount()` 拒绝挂载 `states` 或非授权目录。

## 实际命令与结果

| 命令 | 结果 | 说明 |
| --- | --- | --- |
| `pwd && git status --short --branch && git rev-parse --abbrev-ref HEAD && python3.12 --version && uv --version && node --version && npm --version && python3.12 -m pytest --version || true && python3.12 -m ruff --version || true && python3.12 -m mypy --version || true` | 通过，部分工具未安装 | 确认目录、分支、Python3.12.13、uv0.12.3、Node26.5.0、npm11.17.0；系统 Python 无 pytest/ruff/mypy。 |
| `PYTHONPATH=source python3.12 -m compileall -q source/trainlab source/skills source/tests source/tools/check_b0_static.py` | 通过 | Python 语法检查。 |
| `PYTHONPATH=source python3.12 -m unittest discover -s source/tests -p 'test_*.py'` | 通过 | 9 个 Python 合同测试通过。 |
| `PYTHONPATH=source python3.12 source/tools/check_b0_static.py` | 通过 | B0 静态合同检查通过。 |
| `uvx ruff check source --config source/pyproject.toml` | 通过 | 首次运行发现 import/typing/style 问题，修复后通过；uvx 使用工具缓存，未创建仓库 `.venv`。 |
| `uvx mypy --config-file source/pyproject.toml source/trainlab source/skills source/tests source/tools/check_b0_static.py` | 通过 | 首次运行发现 FastAPI optional import 类型问题，改为 importlib 后通过。 |
| `cd source/frontend && npm test && npm run build` | 通过 | Node 内置测试 3 项通过；构建输出到 `source/skills/local-web/web`。 |
| `git diff --check && git diff --name-only --cached && git status --short` | 通过 | diff 空白检查通过；无 staged 文件；工作区仍有未提交改动。 |

## 未运行/未做事项

- 未安装项目运行依赖到仓库环境，未创建 `.venv`。
- 未运行真实 FastAPI 服务；`create_app()` 已有 B0 占位工厂，实际运行需安装 `source/pyproject.toml` 声明的 FastAPI/uvicorn 依赖。
- 未实现 FIT 解析、records 查询、报告生成、Garmin 同步、AI Provider 调用或长期定时器；这些属于 B1～B7。
- 未执行独立 Validator 或主Agent最终验收。

## 风险与后续

- B0 前端为无外部依赖的静态壳和合同测试，不是完整 React/Vite 应用；后续 B6 需要接入正式 React 构建链。
- FastAPI 运行依赖已在 `source/pyproject.toml` 声明，但本轮未安装和启动，后续后端实现阶段需验证真实服务运行。
- `config` 表仅冻结系统参数表骨架；后续 Web 设置接入时仍需定义具体参数键和值 Schema。
