# TrainLab 项目记忆

主协调维护稳定事实与活动指针；任务状态以 exec plan 为准。不得保存私人资料、步骤或完整对话。

## 当前方向

- 用户已批准 M12：FIT-only 运动数据、新 SQLite、每周一次跑步技术总结与固定七日计划、
  简单邮件/PDF、Garmin 课程发布。每日健康/日报 AI 和高保真邮件不再是活动目标。
- source/ 是唯一产品工程；A-021 允许新的 Python 模块入口、相对实例路径和手动 daemon。
  旧 auto.txt 已改为退役通知，新运行层尚未交付，不表示后台已运行。
- 每日香港时间22:00同步当日、昨日及已知缺口；周日15:00同步并冻结周报告。
  离线验收后才进入精确在线范围，首个真实周任务等待下个正常周日15:00。
- 每个独立模块测试及全新只读验证通过后正常提交并推送 origin/main；不包含私人数据或强推。
- 原正式 source/state 和私人配置保留，M12 尚未切换新库；旧归档不能成为新运行依赖。
- 用户已确认 A-022，现完整合同VC-005：运动位置/路线/名称可供 AI 分析，凭据/任意文件边界保留；必要旧M12快照只读恢复不重置预算。不是允许私人资料进入 Git 或自动新增地图/天气服务。
- A-023要求批准的新方案同批替换受影响的规则、实现、Schema、Prompt、入口、配置、测试、CI与文档；必要安全场景迁移验证，已取消业务归档，不维持第二套执行器或永久旧测试总数。
- 归档工具已独立验证，9612 文件备份及恢复闭合。提交 afdb8c0 已推送核对；
  备份位置、清单与恢复命令见当前计划及 source/docs/legacy-archive.md。
- M11 未完成 v4 方向已取消，由 M12 替代；原 canary 失败和私人调用0的记录永久保留。

## 开发与安全

- 默认中文，通俗解释；保留必要的状态码、命令与协议名称。
- 根 Harness 适配 agentForge main 9964970d38df95bbd8fab53166c27c2e5648b82e，
  是 v0.4.4 后治理更新，不是新的正式版。
- AGENTS.md 授权 docs/exec-plans/README.md 作为详细协议。正式任务冻结合同；
  Validator 只读适用合同/规则/当前结果，不继承实施对话、memory 或历史 verdict。
- 验证绑定当前文件快照。只同步真实状态免重验；实现、规则、配置或合同语义变化必须新验证。
  同类两种修法仍失败、三轮不收敛或合同冲突时走独立 Failure Analyst，不自动补丁循环。
- 本仓库禁用 orchestrate-parallel-work，不修改全局技能/配置；实际并行需明确批准。
- FIT、GPS、raw、数据库、私人 goal/email、凭据/Token、Candidate 和结果不进入 Git。
  测试只使用合成或获批隔离输入；正常运行不读取测试。
- Gmail 只用官方 REST，正常原子刷新专用 Token；单次发送，unknown 只读对账。
  Garmin 只能管理已知自有 ID；历史成功验收不授权新的在线动作。
- 根 references 仅按用户主动请求维护，不自动沉淀开发结论。

## 验证入口

从 source/ 执行，使用已有 Python3.12 环境；不要求项目 .venv：

- PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/code -q
- ruff --config skills/_shared/ruff.toml check skills tests/code
- ruff format --check skills tests/code
- mypy --config-file skills/_shared/mypy.ini skills tests/code
- 只读 AST/compile、全部当前声明 Schema 及递归引用、Skill metadata、AI 布局、Markdown、隐私和 Git ignore。
- 根目录执行 git diff --check；完整检查包含 tracked 与 untracked 文件。
- 旧 macOS 专用 Candidate 的 Linux CI 失败记录仍保留；不得把 macOS 通过称为 Linux 已验证。

## 唯一活动计划

[ M12 FIT-only 周系统重建 ](docs/exec-plans/active/M12-fit-weekly-0001-rebuild.md)。

当前0003n按VC-005进行依赖与验收收敛；首批公共资源、周输入与安全接替已获全新独立PASS，macOS/Linux完整回归均3049项通过。提交推送/CI和其余旧CLI退出仍待完成，不等于M12交付。修改前保护/恢复副本及正式state不变。旧M9停止确认失败原因仍未确定，不声称已修复。0004–0006未进入真实调用。

## 历史交付定位

- 开发治理：ADHOC-0015/0016，见 docs/exec-plans/completed/。
- M10 曾完成有界 Garmin 测试课程生命周期与 Gmail 投递；不授权长期自动化。
- M11 v3 曾完成8封真实邮件；v4 返工取消，不改写为成功。
- M7/M8/M9 的测试、真实数据离线验收与失败记录均留在原 completed plans。
  M8 r31 曾触碰正式 SHM 元数据，不得宣称全部历史从未触碰 sidecar。
