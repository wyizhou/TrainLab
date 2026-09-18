# 本次运行说明

## 环境与顺序

- 固定副本，无 `.git`；开头通用 `git status` 检查退出128，随后按任务材料确认此为预期副本形态，没有回来源仓库。
- `uv sync --project source --python 3.12 --locked --offline --extra dev --no-editable --reinstall-package trainlab-source`：退出0。独立环境实际位置记在 `env-path.txt`；46个唯一安装实现/Schema/资源与受审文件逐字节一致，前后均检查。
- `source/frontend` 下 `npm ci`、`npm run build` 均退出0；先构建，再完整前端/Python门。默认E2E按原脚本又构建一次，bundle名保持一致。
- 回归和子进程使用 `sandbox-exec -f review-output/v2/offline.sb`；OS网络白名单仅回环8080/8081与Unix IPC。Python还通过 `sitecustomize.py` 审计网络；既有离线宿主也保留自己的socket拒绝/计数。浏览器认证无route.fulfill，页面路由只放行批准的本机源。
- 初次自建sandbox规则用数值IP，系统配置编译器要求host为localhost或*，退出65，产品未启动；仅将自建规则改成系统支持的localhost，编译执行成功。没有依赖故障或产品修复。
- 独立Chrome JSON reporter相对于配置目录解析，因此实际JSON位于 `review-output/v2/review-output/v2/independent-chrome.json`，非预想的上一层。实际证据保留原位，没有重跑或修改受审配置。

## 独立Python测试调试记录（非产品修复）

`gates.tsv`保留每次退出，不能将前两次写成通过：

1. 初稿13失败/退出1：lifespan启动的首次后台本地观察与立即登录竞争，合同允许非阻塞门返回409 busy。脚本未等观察结束。
2. 补启动等待后2通过/11失败/退出1：仍未在相邻变更请求间等唤醒观察结束；部分测试推进3300秒已超过1800秒会话闲置期限，所以GET409是合理过期；损坏观察断言亦遇到允许的stale缓存。
3. 最终脚本在相邻变更操作后明确等工作完成；维护场景由离线传输产生1000秒有效令牌，真实SDK计算900秒维护点，不跨会话TTL；独立会话过期场景仍保留1800秒。未改产品、未重放失败请求、未放宽原断言。13项全部通过/退出0。

前两次pytest失败输出包含断言源码中的固定合成输入和随机attempt。已仅对这些合成输入/attempt做脱敏，保留错误、状态码、行号和失败计数；统计在 `safety-freeze-summary.json`。这些是验证脚本诊断产物，不是产品日志/响应泄漏；没有真实秘密。后续使用short traceback。公开归档日志/XML/JSON扫描结果为0，测试代码本身保留可复现的合成输入。

## 人工调用链核对

- 构造：`create_app`只组装；lifespan才创建所有者、Sessions和Runtime，启动一条维护循环。
- 认证：React面板→authRequest→six auth routes→Origin/Host/session/CSRF/body门→runtime.action→GarminAuthService→GarminSDK→锁定Garmin/garth→离线requests传输→真实commit/dump/load/原子指针。
- SDK 0.2.40在return_on_mfa下普通登录直接完成交换；MFA恢复走resume_login、profile/settings。提前维护由真实garth.refresh_oauth2→sso.exchange→新代次提交，不fake认证成功。
- Web/CLI/同步不直接导入SDK或认证仓储；同步通过所有者租约；所有权AST门已实际通过。HTTP白名单不返回flow_id/revision/OAuth。
- stop先拒绝新操作、等循环和受理jobs、再close；shield避免客户端await取消后提前close。在途关服由原Chrome和Python回归实测，独立CLI反复SIGINT/重启通过。
- 既有test_auth_http部分禁用维护只用于路由测试，不作为运行期维护证据。独立Chrome正式CLI无runtime_factory替身，真实wall clock提前刷新通过。
