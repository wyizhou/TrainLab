# TrainLab source

当前实现本地工程底座、FIT/SQLite、采样查询、报告存储、Garmin 同步和认证维护入口，以及兼容 AI API 工具循环、三模式 Context 和报告服务。本地检查使用隔离的合成实例；真实 Garmin 登录、刷新与同步仍需使用者明确执行和另行验收，AI 实服务验证暂停。

## 目录与安装

- `source/skills/_shared/scripts/trainlab/`：共享合同、JSON 校验、时间、数据库协调门和架构检查。
- `source/skills/fit-store/scripts/`：实际 FIT 解码、消息映射、activities/records 唯一写入者。
- `source/skills/local-web/scripts/`：FastAPI 应用、认证 HTTP/内存会话与运行期维护；`web/` 是 React 生成目录。
- `source/schemas/`：公开 JSON Schema 及合法示例；所有验证入口引用同一份 Schema。
- `source/tools/README.md`：能力说明，不放执行脚本。
- `source/frontend/`、`source/tests/`：前端与合成测试。

Python 包名仍为 `trainlab`，由 `source/pyproject.toml` 的 setuptools 映射到上述物理目录。无需也不允许运行时修改 `sys.path`。Schema 同时打包为资源，正常 wheel 安装后可离开工程目录导入。

使用仓库外独立 Python 3.12 环境；不要全局安装或创建仓库 `.venv`。预先将 `UV_PROJECT_ENVIRONMENT` 设置为该仓库外环境，按锁文件安装（在项目根运行）：

```bash
: "${UV_PROJECT_ENVIRONMENT:?请先指向仓库外独立环境}"
uv sync --project source --python 3.12 --locked --extra dev --no-editable
```

检查使用实际安装的非 editable 包。修改产品后以相同命令加 `--reinstall-package trainlab-source` 强制重新构建安装，防止缓存导致检查到旧 wheel。`source/uv.lock` 固定全部解析后的依赖；SDK 为 `garmin-fit-sdk==21.214.0`，Schema 验证器为 `jsonschema==4.26.0`。

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
: "${UV_PROJECT_ENVIRONMENT:?请先指向已安装的仓库外独立环境}"
npm run e2e
npx playwright test -c playwright.auth.config.ts
```

`npm run e2e` 先构建前端，再由 Playwright 使用系统 Google Chrome 访问本机 8080；直接使用调用者 `UV_PROJECT_ENVIRONMENT` 下的 `bin/python`，不会自动安装或切换环境。环境变量缺失或解释器不可执行时明确失败；环境路径可含空格。运行前按上文安装非 editable 包，修改产品后重新安装。测试拒绝借用已有服务，夹具在临时目录创建合成 SQLite 和同步状态，不读取真实 `states/`、FIT 原件或凭据。

构建直接输出 `source/skills/local-web/web/`，不清空相邻 scripts。认证 Chrome 场景使用真实页面、HTTP、生命周期、认证所有者、锁定 SDK 和仓储，只替换外部 HTTP 传输；子进程拒绝外连。每个场景使用合成临时实例，控制仅走私有进程管道，生产无测试控制路由；trace/HAR/video/自动截图关闭。默认仪表盘和新增认证套件都须执行，离线结果不代表真实 Garmin 已通过。

## Garmin 认证与同步

安装上述环境并构建前端后，在项目根启动产品 Web：

```bash
python -m trainlab.local_web.cli --instance-root . --project-root .
```

打开 `http://127.0.0.1:8080`，在“Garmin 登录与认证维护”面板选择国际区 `com` 或中国区 `cn`，本人输入账号、密码，需要时输入验证码。无需先在 CLI 登录或手写令牌。普通登录直接保存；待验证码可取消、刷新页面后继续（不延长期限），过期或服务重启后需重新开始。账号/密码/验证码提交即清空，应用不写浏览器持久存储、不自动重放；请求中断先看状态，不等于取消后端操作。取消只结束待验证流程，不删除旧认证。

Web 仅支持规范回环地址、单 worker、无 reload；Host、Origin、会话与 CSRF 安全门拒绝跨站/跨端口请求。cookie 只是 HttpOnly、SameSite=Strict 的不透明内存会话标识，不是 Garmin 令牌；闲置30分钟失效，最多32个会话。POST 严格 JSON、16KiB 实际请求体上限；账号320字符、密码1024字符、验证码128字符，不截断密码、不限定六位验证码。不记录敏感请求或原始请求目标；不为公网、代理、多用户或恶意同机进程提供保护，也不承诺内存物理擦除。

页面分开显示本地保存/真实期限、登录流程、维护状态；`server_verified=false` 不代表在线已核验。服务真正启动进入生命周期后，自动在到期前维护；导入/构造应用不读凭据、不启动线程或联网。临时失败最多3次、等待5/10秒后暂停，可点击“重试维护”按真实期限重查；人工/撤销状态绑定当前代次，不能被本地加载成功洗掉，重新登录或外进程提交新代次后才重估。不会启用 AI、活动同步或系统守护任务。

Ctrl-C 关闭服务会停止调度并等待在途 SDK/保存结束后清理。每个 SDK HTTP 请求15秒超时，不是完整登录/关服的总时限；休眠、退出或断网不保证提前维护。正式实例认证与维护仅由使用者明确启动并另行验收。

以下 CLI 仍保留作为显式运维工具，不是 Web 登录的前置条件：

```bash
python -m trainlab.garmin_auth_cli login --instance-root . --region com
python -m trainlab.garmin_auth_cli status --instance-root .
python -m trainlab.garmin_auth_cli maintain --instance-root . --once
python -m trainlab.garmin_auth_cli maintain --instance-root .
python -m trainlab.garmin_auth_cli sync-once --instance-root .
```

- `login` 仅接受本人交互终端，账号、密码和验证码都不回显；不支持通过命令参数、环境或文件传密码/验证码。仅服务确实要求时提示验证码；等待不代表认证成功。EOF/Ctrl-C 取消，不保留待验证会话。不要把任何秘密复制到聊天、日志或公开材料。
- `status` 只检查本地已保存数据，返回实际访问令牌到期时间和建议维护时间；`server_verified=false`，不把“文件存在”说成“服务器已验证”。过期令牌仍可能用真正的 OAuth1 交换，不能凭 OAuth2 refresh token 的期限判断底层授权已经失效。
- `maintain --once` 只检查一次。不加 `--once` 才启动前台循环：最多等60秒重查，到期前窗口为 `min(300秒, max(1秒, expires_in×10%))`，用 SDK 的实际期限执行交换并保存；临时错误最多连续尝试3次（等待5秒、10秒），需要人工登录即停止。Ctrl-C 退出。未启动、机器休眠或持续断网时，不保证到期前执行；不能保证授权无限延长。
- `sync-once` 保留首次最近七天、后三小时判断；未到同步时间或忙碌时不会开始认证联网。下载 FIT/单 FIT ZIP，使用 `YYYYMMDD-SHA256.fit` 或 `unknown-SHA256.fit` 命名，再实际解码、事务入库；状态文件 `states/garmin-sync.json` 不包含认证秘密。

通用接口为 `trainlab.garmin_auth.GarminAuthService` 的 `begin_login(username, password, is_cn=...)`、`submit_mfa(flow_id, code)`、`cancel_login(flow_id)`、`status()`、`maintain_once(now_utc=...)`，结果沿用 `ok/data/error`，用 `to_json()` 获取安全白名单。通用服务不读取终端。默认 MFA 流程在同一服务实例内保存5分钟（单调时钟），只可提交一次；取消、过期或请求异常后重新开始，不自动重放验证码。未知的验证失败不武断称为“验证码输错”。Web 每次生命周期长期持有一个服务实例及一条维护链；HTTP 仅经该所有者操作，浏览器会话与尝试双重绑定，内部 flow/代次不发给浏览器。`/api/garmin/auth` 提供 GET `session`/`status`，POST `login`/`mfa`/`cancel`/`maintenance/retry`；与原10条业务路由共同组成16条接口。状态 GET 只本地观察，维护刷新另由运行态调度。其他 CLI/同步进程经同一仓储锁协调，新代次使旧 MFA 失效。

认证服务是唯一所有者。活动入口 `states/verification/garmin.json` 指向 `states/verification/garmin-tokenstore/` 内完整不可变代次；私有目录0700、文件0600。保存先经真实 SDK dump/load 往返和落盘检查，最后原子切换指针；保留旧完整代次，每次切换前保全旧配置原字节为私有 `garmin-backup-*.json`（包括首次接管）。失败/中断可能留下非活动代次，不自动删除未知文件。旧本地数据保全不保证服务端已轮换的旧授权仍可用。线程和进程锁协调登录、维护、同步；等验证码时释放存储锁，旧流程遇认证代次变化拒绝覆盖；锁持有进程崩溃后由系统释放锁。

旧 DI 三字段配置仅返回 `legacy_auth_requires_login`，不会拼成 OAuth1 或编造期限。已有 SDK `garth_tokenstore`/`tokenstore`（实例内目录或私有编码串）可经校验接管，原件保留；实例外目录、符号链接或损坏数据受控拒绝。同步通过所有者租约取得数据，不读写秘密；SDK 在数据请求中隐式刷新后也由所有者持久化，即使后续数据请求失败。

锁定适配版本为 garminconnect 0.2.40 / garth 0.6.3。模块导入和服务构造不读私人数据、不联网。SDK 导入/操作前拒绝 `GARTH_HOME`、`GARTH_TOKEN`、`GARMINTOKENS` 或开启的 `GARTH_TELEMETRY`，不打印其值也不修改宿主环境。请求含首次 consumer 配置均限制15秒、禁用 SDK 自动重试；consumer URL、代理和 TLS 设置来自锁定 SDK。SDK/HTTP 日志在当前调用上下文内保留级别但隐藏内容与异常堆栈，其他模块/线程不受影响。升级 SDK 需重新核对这些内部接点。

`run_garmin_sync(instance_root, client, now_utc=...)` 的注入协议是安全 `session()` 租约与列表/下载操作；旧 `AuthRefreshResult.updated_config`、配置加载/拼接客户端入口已退出。真实入口 `run_real_garmin_sync(...)` 共用认证所有者。所有开发测试使用临时合成数据和阻断真实 socket 的 HTTP 传输替身；离线通过不代表真实登录、当前401或真实同步已通过。

## FIT 基础层

`trainlab.fit.import_fit_file(instance_root, fit_path)` 默认调用实际解析器，不需要注入 decoder。只在完整解码和 JSON/引用校验后建库、整场事务写入。实例及 FIT 路径必须由受信宿主提供；测试全部使用临时合成实例。

同 SHA 普通导入不修改已有有效数据、原路径、解析时间或报告。维护必须显式调用 `trainlab.fit.storage.reparse_fit_file`：读取原入库路径、核验原件 SHA、完整解析，再取得单进程协调门更新；无变化不写，有活动报告且依赖事实变化则 `REPARSE_CONFLICT`，失败保留五表数据。内部 `replace_activity` 只供 FIT 仓储与合成测试使用，不是模型/Web 工具。

默认事实接口 `get_activity_facts` 只返回批准的123容器和其所需字段/来源闭包，不整体返回第四类。12/4/3/3业务列及config三列不变；没有自动付费补报或重解析UI。

解析能力、SDK适配与完整性细则见 [FIT基础层说明](skills/fit-store/README.md)。AI 模块只通过合成客户端或显式配置的兼容 HTTP 客户端运行；真实 AI 参数与验证保持暂停。认证维护开发自查不能代替独立验证、本人真实认证/刷新及完整同步验收。
