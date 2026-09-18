# TrainLab source

当前实现本地工程底座、FIT/SQLite 基础层、采样查询、报告存储、Garmin 同步/认证/调度的可测试合成底座，以及兼容 AI API 工具循环、三模式 Context 和报告服务的合成接线；不做真实 Garmin 网络联调、真实调度守护或真实 AI Provider 请求，不读取正式私人实例。

## 目录与安装

- `source/skills/_shared/scripts/trainlab/`：共享合同、JSON 校验、时间、数据库协调门和架构检查。
- `source/skills/fit-store/scripts/`：实际 FIT 解码、消息映射、activities/records 唯一写入者。
- `source/skills/local-web/scripts/`：最小 FastAPI 应用；`web/` 是 React 生成目录。
- `source/schemas/`：公开 JSON Schema 及合法示例；所有验证入口引用同一份 Schema。
- `source/tools/README.md`：能力说明，不放执行脚本。
- `source/frontend/`、`source/tests/`：前端与合成测试。

Python 包名仍为 `trainlab`，由 `source/pyproject.toml` 的 setuptools 映射到上述物理目录。无需也不允许运行时修改 `sys.path`。Schema 同时打包为资源，正常 wheel 安装后可离开工程目录导入。

使用仓库外独立 Python 3.12 环境；不要全局安装或创建仓库 `.venv`。预先将 `UV_PROJECT_ENVIRONMENT` 设置为该仓库外环境，按锁文件安装（在项目根运行）：

```bash
: "${UV_PROJECT_ENVIRONMENT:?请先指向仓库外独立环境}"
uv sync --project source --python 3.12 --locked --extra dev --no-editable
```

检查使用实际安装的非 editable 包。修改产品后先重新执行安装，防止检查到旧 wheel。`source/uv.lock` 固定全部解析后的依赖；SDK 为 `garmin-fit-sdk==21.214.0`，Schema 验证器为 `jsonschema==4.26.0`。

## 本地检查

在激活上述环境后，从 `source/` 运行：

```bash
python -m pytest tests -q -p no:cacheprovider
python -m ruff check --no-cache .
python -m mypy -p trainlab -p tests --no-incremental
python -m compileall -q skills schemas tests
python -m trainlab.check_architecture
```

架构门检查运行实现的物理路径以及sys.path写入（含直接赋值、切片/下标写入、常见导入别名和原地修改）；tools仅供文档，shell/shebang文件也属于实现。读取sys.path、正常前端/测试/Schema资源不因本检查被禁止。这是静态检查，不承诺识别任意动态反射或混淆代码。

mypy 显式检查已安装产品包及当前测试。原 `trainlab skills tools tests` 物理路径检查改为包检查；原 `tools/check_b0_static.py` 改为共享包模块入口，原检查覆盖保留并增加违规目录/导入补丁检查。

前端在 `source/frontend/`：

```bash
npm ci
npm run lint
npm run typecheck
npm test
npm run build
```

构建直接输出 `source/skills/local-web/web/`，不清空相邻 scripts。仅最小 health/静态应用已接线；其他业务路由不伪造成功结果。

## Garmin 同步合成底座

`trainlab.garmin_sync.run_garmin_sync(instance_root, client, now_utc=...)` 通过宿主注入的客户端协议执行同步：读取实例内 `states/verification/garmin.json`，刷新可用认证，按首次七天/后三小时判断列活动，分页去重，下载 FIT 或单 FIT ZIP，按 `YYYYMMDD-SHA256.fit` 或 `unknown-SHA256.fit` 原子写入 `states/activities/`，再调用 FIT 导入入口。状态保存在 `states/garmin-sync.json`，只记录同步时间、远端活动ID和公开文件相对路径，不记录认证秘密。

本模块测试全部使用 `/tmp` 合成认证文件和 fake Garmin 客户端；不会读取真实 `states/verification/garmin.json`，不会联网、登录或绕过 MFA。若刷新需要人工登录/MFA，返回明确失败；真实适配器仍需后续受控联调验证。

## FIT 基础层

`trainlab.fit.import_fit_file(instance_root, fit_path)` 默认调用实际解析器，不需要注入 decoder。只在完整解码和 JSON/引用校验后建库、整场事务写入。实例及 FIT 路径必须由受信宿主提供；测试全部使用临时合成实例。

同 SHA 普通导入不修改已有有效数据、原路径、解析时间或报告。维护必须显式调用 `trainlab.fit.storage.reparse_fit_file`：读取原入库路径、核验原件 SHA、完整解析，再取得单进程协调门更新；无变化不写，有活动报告且依赖事实变化则 `REPARSE_CONFLICT`，失败保留五表数据。内部 `replace_activity` 只供 FIT 仓储与合成测试使用，不是模型/Web 工具。

默认事实接口 `get_activity_facts` 只返回批准的123容器和其所需字段/来源闭包，不整体返回第四类。12/4/3/3业务列及config三列不变；没有自动付费补报或重解析UI。

解析能力、SDK适配与完整性细则见 [FIT基础层说明](skills/fit-store/README.md)。采样查询、报告存储、Garmin 同步合成底座和 AI/Context 合成接线已有受控离线接口；同步模块只通过宿主注入的 Garmin 客户端协议和合成测试运行，AI 模块只通过 fake 客户端或显式配置的兼容 HTTP 客户端运行。真实 pygarminconnect、真实 AI Provider、自动报告策略和完整 Web 业务仍待后续阶段验证，不能把本轮自查当整个系统验收。
