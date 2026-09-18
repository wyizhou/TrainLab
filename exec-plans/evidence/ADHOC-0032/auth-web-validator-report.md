# 0032-T14 独立验证报告

**结论：通过，限 GUI32-01～06 约定的离线集成范围。** 未发现可复现的产品阻断问题；不代表真实 Garmin 账户、线上服务或 AI 已通过，也不代替主 Agent 最终验收。

## 受验材料与隔离

- 已先读取客观 PLAN、关联执行计划，再完整读取任务、合同、provenance、两个 manifest、适用 AGENTS 与 Validator 模板；核对当前实现、完整 source.diff、关键 SDK 控制流及已有测试。未读取来源仓库、开发报告、历史裁决或真实实例。
- 固定版本：来源分支 `work/adhoc-0031-local-web-system`，HEAD `a5893ac6eb8295cd8a60d8f2537bc213d1412885` 加导出时全部未提交 source。本副本无 Git；未初始化、提交或推送。
- **116 个 source、4 个 references 哈希全部匹配；连同规则、任务等共133个冻结文件，检查前后0变化。** 产品、参考资料、规则、协调记录均未修改。
- 独立仓库外 Python 3.12.13 非 editable 安装，强制重装当前产品0.1.12；46个唯一安装实现/Schema/资源与源码逐字节一致，结束时再核对通过。SDK：garminconnect0.2.40、garth0.6.3；React19.3.0、Vite8.3.0、Playwright1.63.0；实际系统 Chrome152.0.7977.83。
- 所有测试命令及其子进程由 OS 网络白名单限制到回环8080/8081及本地 Unix IPC；Python另设审计门，认证宿主保留离线传输/socket统计。非白名单回环端口阳性检查被 OS 拒绝。**产品/SDK及Python审计未发现意外外连尝试**；没有请求真实 Garmin 或 AI。Chrome自身后台流量由OS阻断，未据此声称具有全部浏览器内部尝试计数。
- trace/HAR/video/自动截图关闭。认证未使用 route.fulfill，也未伪造 begin_login、submit_mfa、maintain_once 或 commit 结果。

证据统一在 `review-output/v2/`。安装、冻结、安全及实际环境见 `install-verification*.json`、`freeze-{before,after}.json`、`safety-freeze-summary.json`、`network-gate-control.json`。

## 实际命令与结果

`gates.tsv`保存实际 cwd、命令和退出码；下表路径以副本根为基准。Python均直接使用本次独立环境解释器，未用uv run切换安装模式。

|cwd|实际检查|结果／证据|
|---|---|---|
|`.`|`uv sync --project source --python 3.12 --locked --offline --extra dev --no-editable --reinstall-package trainlab-source`|退出0；`install.log`|
|`source/frontend`|`npm ci`；`npm run build`|均退出0，先构建后完整门；`npm-ci.log`、`build.log`|
|同上|`npm run lint`；`npm run typecheck`；`npm test`|均退出0，14测试通过；对应日志|
|`source`|`python -m pytest tests -q -p no:cacheprovider --junitxml=<本次证据>`|退出0，**318通过**；`pytest.log`、`pytest.xml`|
|同上|`python -m ruff check --no-cache .`|退出0；`ruff.log`|
|同上|`python -m mypy -p trainlab -p tests --no-incremental`|退出0，84文件；`mypy.log`|
|同上|`python -m compileall -q skills schemas tests`|退出0；`compileall.log`|
|同上|`python -m trainlab.check_architecture`|退出0；`architecture.log`；完整pytest另含Schema/所有权门|
|`source/frontend`|`npm run e2e -- --reporter=list,json --output=../../review-output/v2/default-output`|退出0，**2项系统Chrome通过**；`playwright-default.json`|
|同上|`npx playwright test -c playwright.auth.config.ts --reporter=list,json --output=../../review-output/v2/auth-output`|退出0，**24项认证Chrome通过**；`playwright-auth.json`|
|`.`|`source/frontend/node_modules/.bin/playwright test -c review-output/v2/independent.config.ts`|退出0，**6项独立产品CLI＋Chrome通过**；`independent-chrome.log`及下述JSON|
|`.`|`python -m pytest review-output/v2/independent_integration.py -q -p no:cacheprovider --tb=short --junitxml=review-output/v2/independent-python-v3.xml`|最终退出0，**13项独立集成通过**；`independent-python-v3.{log,xml}`|
|`.`|`python -m trainlab.local_web.cli --instance-root <合成实例> --project-root <空目录>`|预期退出2，固定“前端未构建”提示，未创建实例；`missing-build.log`|

默认E2E再次按原脚本构建；生成bundle哈希记录在安全汇总。三个Chrome套件共32项通过，无跳过或flaky。独立Chrome JSON实际为 `review-output/v2/review-output/v2/independent-chrome.json`：其配置相对路径由reporter按配置目录解析，证据保留原位。

**未隐去的验证脚本调试：** 独立Python初稿退出1／13失败；加启动等待后退出1／2通过11失败。原因是脚本没有等待合同允许的后台观察完成，以及维护时钟推进3300秒已越过1800秒浏览器会话期限；还把允许的stale缓存当成即时损坏观察。最终脚本等待相邻操作完成，并让离线SDK响应产生1000秒真实期限，在会话有效期内测900秒维护点；1800秒会话过期测试仍保留。未修产品、未放宽原断言或重放失败的秘密提交。两次原失败日志/XML（脱敏）与实际退出均保留，详见 `execution-notes.md`。

初次自建OS规则因系统要求localhost而非数值IP退出65；仅修正隔离脚本语法后验证有效，产品尚未启动。开头通用git检查退出128，是无Git固定副本的预期形态；没有环境依赖故障或受审冻结变化。

## 独立场景与合同覆盖

运行前设计：`scenarios.md`；可复现代码：`independent.spec.ts`、`independent.config.ts`、`independent_integration.py`、`network/v2_cli_bootstrap.py`、`network/sitecustomize.py`、`offline.sb`。

|合同|实际操作及证据|判定|
|---|---|---|
|C01／GUI32-02|正式产品CLI启动无DB/AI合成实例；实际React面板可操作，仪表盘错误不挡登录，健康声明维护启用、AI关闭|通过；独立P01＋原Chrome|
|C02／01、03、06|com/cn各普通GUI登录；密码前后空格经过真实HTTP、Garmin/garth传输仍保留；SDK只访问所选区域域名，真实交换一次、保存成功，无MFA步骤|通过；独立P01四组合中的普通分支、安全receipt|
|C03／02、03、06|两区MFA，刷新页面后期限不变；独立使用非六位验证码；真正resume_login/profile/settings并提交仓储；同浏览器第二标签页CSRF不轮换|通过；独立P01＋原Chrome|
|C04／02、03、05|真实离线传输返回401/403/429/超时/异常HTML/MFA未完成/settings失败；GUI固定错误、不假报保存，原指针保留|通过；原7项Chrome、全量HTTP/SDK测试|
|C05／02、05|GUI取消重来、旧句柄拒绝、迟到状态不覆盖新流程、会话过期；独立精确299.999/300/300.001秒、空白/超长码不消耗上下文|通过；原Chrome＋独立I01/I04|
|C06／05|双上下文越权、同码并发、重复Enter；业务最多执行一次，忙时页面/health仍可访问；独立测32会话容量、第33个429|通过；原Chrome＋独立I04|
|C07／02、03|独立正式CLI各登录组合保存后SIGINT关服，再启动原实例；区域/期限一致、交换数0、明确旧会话失效；原Chrome覆盖待MFA重启|通过；独立P04＋原Chrome|
|C08／03、04|独立正式CLI使用自然墙钟：10秒令牌在过期前自动SDK交换并提交新代次；无需CLI maintain。Python精确维护点前/到点/已过期，GET零额外交换|通过；独立P04/I02＋原Chrome|
|C09／04|503/429/超时精确5/10秒退避、三次暂停，推进1000秒不再交换；GUI点击重试只开启有界组；401/403人工状态不被GET或retry清除，新代次后重估|通过；独立I02＋原Chrome|
|C10／03、04|原Chrome实际CLI登录/维护/同步、外进程持锁、保存失败保留旧指针；独立待MFA期间自动维护提交后旧码409且无verifyMFA请求|通过；原Chrome＋独立I03|
|C11／05|独立正式CLI直接HTTP：缺失/null/外站/另一端口Origin、错误CSRF、非法Host、重复JSON键、数字密码、非JSON及分块超限，安全拒绝前SDK0请求；同一浏览器携已有会话从另一端口和localhost跨站攻击，连已知有效CSRF也不能取消MFA或触发维护|通过；独立P02/P03＋原安全回归|
|C12／03、04、05|公开响应/日志及浏览器持久存储canary检查、阳性对照；OAuth只在私有代次，目录0700/文件0600；独立CLI睡眠时退出/重启，原Chrome在途停服等提交后退出，Python检查jobs清空；完整仪表盘搜索/选择/全文/周报/API-SPA回归|通过；独立P04、原Chrome及全量门|

## 人工审查与问题

- 人工核对完整调用链：React→真实HTTP安全门→运行态→唯一所有者→SDK→仅远端HTTP替身→实际dump/load/代次提交。独立Chrome启动的是 `python -m trainlab.local_web.cli`，不是serve_web替代产品入口；sitecustomize只安装离线HTTP传输和统计，不替换认证业务结果。
- Web/CLI/同步没有直接读写认证仓储或导入SDK；状态只来自所有者，HTTP不泄露内部flow/revision/OAuth；16条方法/路径集合的合同门通过。
- 导入/构造无私人认证读取或维护启动；真实lifespan才启用一条维护链。停止先拒绝新操作、等受理jobs后close；不把15秒单次HTTP超时当完整关服总期限。
- **产品问题表为空；未分配GUI32-V2新缺陷编号。** 两轮独立脚本失败归因为上述可解释的测试同步/时钟设计问题，不是产品修复轮次。

## 隐私、清理与残余风险

- 独立pytest前两轮失败诊断自动带出了测试源码中的固定合成输入和随机attempt；已对归档日志/XML做明确脱敏，保留失败实情和统计（`diagnostic_redactions_only`）。这是本次验证脚本产物问题，不是产品日志泄漏；没有真实秘密。后续采用short traceback。最终公开日志/XML/JSON扫描0命中，扫描阳性对照有效；可复现测试代码中的合成输入不冒充产品泄漏。
- 自建CLI和原宿主均正常结束；8080/8081无监听，serve_auth/serve_web/auth_actor/产品CLI无残留。证据：`process-cleanup.json`、`ports-after.log`；独立集成退出检查jobs、会话与MFA资源清空。
- 没有真实账户、真实外部服务、真实AI、长期休眠/断网恢复或用户正式实例验收。离线传输不能证明线上SSO页面与地区服务当前兼容；这些仍需用户以后安全操作。
- 独立损坏指针场景证实blocked、固定错误和期限清空；未额外证明修复同一代次损坏文件后能自动恢复维护，合同也未承诺所有本地损坏可靠重新登录修复。
- 单机恶意进程、浏览器自身密码管理器及字符串物理擦除不在该合同保证范围。全量Python仅有Starlette/httpx与BlockingPortal两项弃用警告，未改依赖消警。
