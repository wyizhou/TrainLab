# ADHOC-0031 真实检查记录（2026-09-18）

用户授权：开始真实 Garmin、真实 AI 和 8080 检查；全部通过后再询问是否合并。

结论：未全部通过，不能进入合并询问。

## 1. 8080 本机 Web/API 检查

命令摘要：使用已安装的本地 wheel 环境启动：

```bash
/tmp/trainlab-pr-venv/bin/python -m uvicorn 'trainlab.local_web.server:create_app' --factory --host 127.0.0.1 --port 8080
curl -fsS http://127.0.0.1:8080/api/health
curl -fsS http://127.0.0.1:8080/api/status
curl -fsS http://127.0.0.1:8080/
```

结果：HTTP 层通过。

- `/api/health` 返回 `ok: true`。
- `/api/status` 返回 `ok: true`。
- `/` 返回 React 静态入口 HTML，长度 402 字节，引用 `/assets/index-CPbYmAtq.js` 与 `/assets/index-CG8UOJ96.css`。

限制：当前工具环境没有真实图形浏览器/MCP browser 工具，因此只能做本机 8080 HTTP/静态入口检查，不能声称完成“人眼浏览器界面验收”。

## 2. 真实 AI 检查

命令摘要：通过产品入口读取 `states/ai.json`：

```bash
/tmp/trainlab-pr-venv/bin/python - <<'PY'
from pathlib import Path
from trainlab.ai import load_ai_config, AIProtocolError
try:
    cfg = load_ai_config(Path('.'))
    print('AI_CONFIG_OK', {'base_url': cfg.base_url, 'model': cfg.model})
except AIProtocolError as e:
    print('AI_CONFIG_ERROR', e.code.value, e.message)
PY
```

结果：失败，未发起真实 Provider 请求。

- 输出：`AI_CONFIG_ERROR DATA_INVALID AI config is incomplete`
- 观察：`states/ai.json` 当前只有 `base_url` 与 `api_key`，产品 `load_ai_config()` 还要求 `model`。
- 为避免擅自修改私人配置或猜模型名，本次未向真实 AI Provider 发送请求。

## 3. 真实 Garmin 检查

命令摘要：读取产品配置、检查真实客户端依赖、做一次不输出 token 的活动列表探针。

```bash
/tmp/trainlab-pr-venv/bin/python - <<'PY'
from pathlib import Path
from trainlab.garmin_sync import load_garmin_auth_config, GarminSyncError
try:
    cfg = load_garmin_auth_config(Path('.'))
    print('GARMIN_CONFIG_OK keys=', sorted(cfg.keys()))
except GarminSyncError as e:
    print('GARMIN_CONFIG_ERROR', e.code.value, e.message)
for mod in ['garminconnect', 'pygarminconnect']:
    try:
        __import__(mod)
        print(mod, 'INSTALLED')
    except Exception as e:
        print(mod, 'IMPORT_ERROR', type(e).__name__)
PY
```

另做直接 Garmin activitylist Bearer 探针，未打印任何 token：

```text
GARMIN_DIRECT_ACTIVITYLIST_HTTP_ERROR 401 Unauthorized
```

结果：失败，未完成产品级真实同步/下载。

- 产品可读取 `states/verification/garmin.json`，键为 `di_client_id`、`di_refresh_token`、`di_token`。
- 当前产品环境未安装 `garminconnect` 或 `pygarminconnect`。
- ADHOC-0031 当前实现的 `PyGarminConnectAdapter` 只是包装宿主传入 client 的薄适配器，PR #21 没有实际构造真实 Garmin client 的入口或依赖。
- 直接用现有 `di_token` 访问 Garmin activitylist API 返回 401，不能证明凭据可用于下载。

## 后续处理建议

需要先修复/补齐以下内容，之后重新做真实验证：

1. 明确并写入 `states/ai.json` 的 `model` 字段，或在产品中定义安全默认模型；再发起最小真实 AI 请求。
2. 为 PR #21 增加真实 Garmin client 依赖与适配入口，或明确使用已存在的受控 Garmin 客户端；之后用真实凭据执行一次有界同步/下载/入库检查。
3. 若需要“浏览器人工 8080”而非 HTTP 检查，需要使用真实浏览器人工打开或提供可用 browser 自动化工具。

因真实 AI 与 Garmin 均未通过，本次不询问合并 PR #21。
