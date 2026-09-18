# Garmin Web GUI主验收

## 结论与范围

GUI32-01～06约定的本地/离线GUI范围通过。主Agent已核独立报告和实际产物，并亲自以新环境运行完整门、真实系统Chrome及产品CLI，查看了空输入、待验证码、保存后的桌面/窄屏截图。不是只读取子Agent结论。

这不证明真实账户登录/MFA、真实到期前刷新、Garmin活动列表/下载/FIT入库成功；T2/T9及历史401仍待真实证据。AI实服务未请求，AU32-V1-002/003既有Context/资料错误不纳入本轮修复或通过结论。未提交/推送/合并。

## 版本与实际证据

- 分支`work/adhoc-0031-local-web-system`，HEAD `a5893ac6eb8295cd8a60d8f2537bc213d1412885`加全部当前未提交内容。116个source＋4个references与独立受验副本及原工作区逐字节相符；3个构建文件与原工作区匹配，暂存为空、diff检查0。
- 独立workflow `eee22d31-30c6-4cfc-874b-76483f6f842d`、Validator `bd3aac01-1cea-4f12-997c-49e3e9a9fc26`已结束；报告`../auth-web-validator-report.md`、完整证据`../auth-web-validator/`已持久归档。主核133个受审文件前后完全相同，现有及独立JUnit/Chrome统计与报告相符。
- 主Agent另建仓库外Python3.12非editable环境，锁定安装并核46个安装实现/Schema/资源与原工作区一致；SDK版本不变。环境/副本指针在`environment.txt`、`workspace.txt`，非业务模板路径。
- 实际完整结果：318项Python＋13项独立集成，14项前端，原Chrome2＋认证Chrome24＋独立产品CLI Chrome6，共32项Chrome，无跳过/flaky；Ruff/mypy/compileall/架构Schema/所有权、lint/typecheck/build退出0。产品CLI帮助0；缺构建负向门按预期退出2、不创建实例。
- 所有实际命令/cwd/退出见`commands.json`，JUnit/Chrome JSON、日志和冻结汇总见`acceptance-summary.json`。调用顺序先构建再完整Web/Python。独立Chrome采用真实正式CLI、自然墙钟的提前刷新、重启复用，合成临时实例。
- 另亲自运行`visual.mjs`，操作中国区MFA经产品HTTP/SDK实际保存，检查输入清空并截图，`visual.json`记录版本/两区选项/实际SDK交换1次/外连0/窄屏无水平溢出。人工阅读`gui-ready-desktop.png`、`gui-mfa-empty-desktop.png`、`gui-saved-mobile.png`确认可操作状态；未截图敏感输入。
- OS层阻断除8080/8081/Unix IPC之外的外连，阳性对照有效；Python审计和测试宿主补充防护。40份日志/XML/JSON canary扫描0命中、扫描阳性对照有效；不得把浏览器被OS拦截的自身背景流量写成『无任何浏览器尝试』。正式服务不携带这些测试传输替身。
- 测试结束时8080/8081无监听；随后只有在此验收通过基础上启动正式本机GUI，实际启动结果另记`delivery.json`，不把测试进程当交付服务。

## 中断与原失败保留

1. 首次主批次在独立Chrome阶段工具调用被中断，没有该命令最终退出值；原日志只证明第一项完成，不能算6项通过。保留`chrome-independent-interrupted.log`、`interruption.json`。用户要求继续后，核无残留进程/端口、文件不变，完整6项重新运行退出0。没有产品修法。
2. GUI32-PARENT-001：恢复批次安装核对第一次退出1，原因是为独立Python测试添加的PYTHONPATH同时暴露源码生成的egg-info，metadata查找误选不含direct_url.json的源码元数据。`metadata-probe-with-source.json`证明源码egg-info与安装dist-info同时存在。只为安装核对移除source路径、保留网络审计shim，重跑`installed-match-after-corrected.log`退出0，原源码与安装46文件相符；未重装/修改产品以迁就检查。该检查脚本失败1、修正1、产品修复失败0。
3. 独立Validator测试脚本的同步/时钟问题、诊断脱敏及开发自查GUI32-V1-001～007均保留原报告/日志及稳定记录。独立首次OS隔离规则语法退出65后已用合法localhost规则和阳性对照恢复，不是产品故障。主Agent没有重写原报告或抹掉原失败。

## 交付边界

- 安全GUI已达到可交给用户操作条件；正式入口`python -m trainlab.local_web.cli --instance-root . --project-root .`，仅`http://127.0.0.1:8080`，单worker、无reload/默认access日志。
- 用户在页面自行选择com/cn并输入真实账号、密码、需要时验证码，不放聊天、不使用CLI登录前置，不录制真实敏感阶段。后端运行期间维护令牌；停止服务/休眠/断网不保证刷新，不启动AI或活动同步后台。
- T15及G4本地GUI交付完成。2026-09-18T13:00:01Z正式产品进程已启动，仅绑定127.0.0.1:8080；页面、会话bootstrap和状态HTTP均200，维护启用、AI未配置，正式认证本地状态为legacy/manual_required，明确等待用户在页面重新登录。没有提交账号密码/验证码，没有真实认证成功声明。见`delivery.json`；进程身份保存在`runtime-process.json`，运行日志在仓库外0700目录/0600文件，不携带测试传输/审计注入。
- 测试端口清理和正式服务运行是两个检查点：测试结束端口均空闲；交付后8080由正式产品进程持续监听是预期，不是测试残留或系统守护。真实账户成功及后续有界同步仍归原T9/T2，不能凭本报告提前完成整体功能。
