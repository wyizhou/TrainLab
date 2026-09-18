# Garmin认证维护主验收与分范围裁决

日期：2026-09-18。结论：**AU32认证维护模块、CLI及同步接线的本地/离线范围通过独立验证和主Agent验收，可以进入用户本人真实登录；整个ADHOC-0032仍未完成。** 不把真实401、实服务刷新或真实活动同步记为通过。

## 固定版本及证据

- 分支`work/adhoc-0031-local-web-system`，HEAD `a5893ac6eb8295cd8a60d8f2537bc213d1412885`加既有未提交工作。未暂存/提交/推送/更新PR/合并。
- 96个source与4个公开references逐字节匹配独立受审副本，前后无修改；清单见本目录`source-before.json`、`source-after.json`、`references-before.json`、`references-after.json`。
- source清单摘要`49fce46458eaeef9369590ee21ad27e6a05d5330af59d552632b4f3238dee24e`。新建仓库外Python3.12非editable环境，强制重建安装；42个产品/Schema文件与当前源码一致，见`installed-match.json`。
- 独立验证材料：上一轮纯客观固定副本的认证39项/实际CLI/PTY/Chrome证据见[固定副本报告](../auth-maintenance-isolated-validator-report.md)；补齐运行资料后的全部门禁及新增40项检查见[完整材料复验](../auth-maintenance-material-validator-report.md)。后者37通过/3失败，失败属于下述两个既有Web问题；原报告原样保留，不改成全绿。

## 独立性及材料问题处理

- AU32-V1-001始终表示材料隔离/完备性问题：首次看业务PLAN历史摘要，第一次隔离副本又漏复制references；累计材料失败2不清零。
- 第二种材料处理（完整副本、客观协调视图、4个公开资料、预先构建）经全新Validator `dbd38663-02f0-4385-9414-059625a37e51` 实际核对通过；明确未访问原仓库/旧报告/旧临时检查，96+4原件冻结，完整pytest282通过。**材料问题已闭合，没有第二种材料修法继续失败或三轮产品修复不收敛。** 不是把新产品缺陷当材料恢复成功的证据。
- 最后报告把新的Context运行错误也编号为AU32-V1-001，发生编号冲突。主Agent保留原报告编号，新增映射：报告的Context问题→**AU32-V1-003**；报告的路径暴露问题仍为**AU32-V1-002**。这两个实现问题此前没有修法，首次发现各1/修法0，不继承或重置无关材料计数。来源标签和对应关系完整保留。

## 范围裁决：真实发现，但不冒充认证回归

| 稳定编号 | 主Agent核对 | 裁决 |
| --- | --- | --- |
| AU32-V1-002 | references符号链接逃逸被拒绝，但ValueError含绝对路径，Web的通用ValueError处理将其回传；主复跑直接工具及Web两断言都失败。没有外部文件内容被读取的证据。 | 有效的既有受限资料/Web错误处理缺陷；未修复，不能宣告整个Web无缺陷。并非新Garmin认证CLI的阻断，不借此恢复暂停的AI/Context修复。 |
| AU32-V1-003（原报告AU32-V1-001） | 故意在合成部署中移除references索引，Web生成返回纯文本500而非公共JSON错误壳；未调用AI、未保存报告。主复跑确认。 | 有效的既有Context/Web错误协议缺陷；未修复。与验证副本真实漏带资料不是同一个原因，不把故障注入失败说成当前材料不齐。 |

代码来源证据：`../auth-maintenance-material-recovery/existing-web-boundary-origin.json`证明`context.py`、`reference_tools.py`、`report_service.py`、Web`server.py`在HEAD、认证改动前78文件快照及当前版本三者完全相同。认证CLI不调用Context/受限资料/Web生成路线。原完整回归与Web正常生成、健康合同均通过，所以这两项不是由认证接线引入的退化。

本轮用户目标为认证维护模块及未来Web复用，不是恢复暂停的AI实现；因此认证本地交付可继续，两个Web/Context修复保留为明确未完成事项，待用户确认处理范围，未擅自派Developer改这些文件。原G1浏览器受测范围通过的历史不改写为当时已发现这些问题，也不外推为当前所有异常必然正确。整体G2/G3、T2/T3/T9不标完成。

## 主Agent实际验收

所有命令cwd/参数/退出值见`commands.json`。Python为本轮仓库外环境解释器；真实状态未读取，所有活动、账号、密码、验证码、令牌均为合成数据，SDK/CLI传输阻断真实socket。

| 实际检查 | 结果/证据 |
| --- | --- |
| 锁定非editable强制重装、npm ci、前端构建 | 各退出0；`install.log`、`npm-ci.log`、`build.log` |
| 全量pytest | 退出0，282通过；`pytest.log`、`pytest.xml` |
| Ruff、mypy、compileall、架构/Schema | 各退出0；对应日志，不用静态检查代替集成 |
| 前端lint/typecheck/单测 | 各退出0，11项单测；`frontend-*.log` |
| 默认Playwright系统Chrome | 退出0，2项通过；`chrome.log`、`playwright-results.json`。实际启动浏览器及Web，无借用旧服务 |
| 独立验证40项完整复跑（未删/跳失败测试） | 退出1，37通过/3失败，恰好为上述两个Web缺陷的3个断言；`independent.log`、`independent.xml`、`independent-summary.json`。没有额外失败或skip |
| 实际SDK认证与CLI集成 | 上项中普通com/cn、分步MFA、失败/过期/取消/代次冲突、刷新保存/重启、进程锁、隐式刷新、ZIP/FIT/SQLite、真实CLI/PTY/EOF/SIGINT和无TTY安全边界通过 |
| CLI公开入口帮助 | 实际调用顶层及login/status/maintain/sync-once五个help，均退出0；`cli-*-help.txt` |
| Git/冻结/端口 | `git diff --check`、无暂存均退出0；96+4文件不变，42安装文件匹配；8080前后无监听，`port-*.txt` |

任务裁决：T4～T7的模块/CLI/统一接线已完成本地交付；T8的认证独立验证及关联正常回归证据已满足，两个超出认证影响面的有效既有问题单列不隐藏；T9的离线主验收完成，但本人真实登录/到期前刷新/重启/有界同步待做，T9仍执行中。

## 使用与未完成边界

- 代码入口`trainlab.garmin_auth.GarminAuthService`供未来Web持有实例后复用分步登录；当前未实现登录页面、HTTP会话绑定/CSRF或Web后台维护。
- 本人终端使用`python -m trainlab.garmin_auth_cli login --instance-root . --region com`（中国区为cn）。密码/验证码隐藏输入；成功才切换认证配置并备份旧原字节，未启动正式维护或修改系统调度。
- `maintain --once`只检查一次，`maintain`才显式前台循环；退出/休眠/断网期间不能保证提前刷新，Garmin撤销授权可能仍需登录。
- 下一步先让用户选择正确区域并本人运行登录；只回报成功或安全错误码，不收集密码/验证码/token。之后核对脱敏收据，实施原授权有界真实列表/下载/SQLite与真实期限刷新验证；不能造token期限来代替观察。
- 两个既有Web缺陷未修；AI实服务继续暂停；未提交/推送/合并。没有把该局部认证验收包装成整个功能交付。
