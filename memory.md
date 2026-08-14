# TrainLab 项目记忆

本文件用于跨会话外置持久上下文，由主协调 Agent 根据已验证证据维护。

## 维护约定

- 只保存稳定偏好、已验证项目事实、已建立的 lint/test 命令和活动计划链接。
- 不重复任务步骤或检查点；exec plan 是任务状态的唯一事实源。
- 不保存密钥、凭据、个人健康数据、raw/FIT 内容、邮件内容、完整对话或未经验证的假设。
- 更新或删除过期事实；Validator 和 Worker 只返回发现，不直接修改本文件。

## 用户偏好

- 项目说明文档默认使用中文；路径、命令、状态枚举和协议标识符保留技术拼写。
- 开发使用根 agentForge Harness；产品运行 Harness/schema/policy 作为不可变资源位于
  `source/src/resources/harness/`，日常从 `source/index.py` 手动运行。
- `orchestrate-parallel-work` 只在本仓库禁用；不修改其全局安装。

## 已验证的项目事实

- 根开发 Harness 固定适配 agentForge `v0.4.2`，上游标签提交为
  `ccc934ece6b7b64368c08bc3ce431678511ecfa3`。
- TrainLab 的唯一产品工程位于 `source/`；产品包为 `source/src/`，直接入口为
  `source/index.py`，默认实例根为 `source/`，显式 `TRAINLAB_INSTANCE_ROOT` 可覆盖。
- Foundation v4 新库不含 Orchestration/Supervisor 表和视图；旧 state/config/logs/数据库
  归档在被 Git 忽略的 `data-backup/`，不删除、不进入产品新库。
- 产品时区合同使用 `Asia/Hong_Kong`；运行时教练 Harness v2 已加入课程、教练画像、
  睡眠半开区间和跑攀硬负荷合同。
- 私有 state、logs、FIT、raw、数据库、凭据和私有配置不得进入 Git 或 `dist/`。
- 项目不再使用或忽略根 `test_data/`；六类 Garmin FIT 测试输入由
  `tests/fixtures/synthetic_fit.py` 确定性生成，私人测试资料只能留在仓库外。
- 根 `references/` 只由用户主动要求维护；产品说明和运行资料位于 `source/docs/`。

## 已建立的验证命令

- `cd source && python3.12 tools/verify_repository_quality.py all`
- `cd source && python3.12 -m pytest`
- Ruff、format-check、mypy、schema 和 source-layout 门禁均从 `source/` 执行；正式运行
  不依赖 wheel、bundle、Supervisor 或仓库 `.venv`。

## 最近完成计划

M5 自适应教练画像与本地报告校准已通过独立 Validator；exec plan 已归档至
`docs/exec-plans/completed/M5-adaptive-coaching-0001-profile-and-preview.md`。
真实隔离库因活动覆盖不完整按合同延期，未伪造报告；预览 renderer 的 HTML/JSON、权限和无副作用回归通过。
最近完成的 M4 计划已归档至
`docs/exec-plans/completed/M4-source-root-0001-product-consolidation.md`；M4 基线提交为
`bab3649`（`feat: complete source runtime migration`）。
