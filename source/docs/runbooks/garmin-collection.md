# Garmin 数据采集工具运行手册

第二层仅通过 `trainlab garmin` 的一次性命令运行；它不含 daemon、timer 或轮询。
第五层传入稳定 invocation ID 并读取唯一 JSON receipt 和退出码。首次全量同步必须在
`config/garmin.yaml` 设置 `history_start_date`，或显式传入 `--health-from`。

部署前安装锁定依赖：`python -m pip install -r requirements.lock`。配置中的
`state/secrets/garmin` 是 Foundation `state_root` 的逻辑定位符，实际 token 目录为
`<state_root>/secrets/garmin`，目录 0700、文件 0600；不得把密码、MFA、token、原始
JSON 或 FIT 写进日志、receipt 或工单。TrainLab 不为 token 设置 TTL，也不按时间主动
删除；Garmin 服务端撤销或会话失效时仍需重新执行认证。

认证时，只有 Garmin SSO 明确返回 `MFA_REQUIRED`，适配层才按同一登录 session、
区域和服务参数调用 `mfa/sendCode`。只有收到 `MFA_CODE_SENT` 后 CLI 才显示验证码
输入提示；投递失败、未知方式、session 不完整或 429 均 fail closed，不询问验证码，
也不把投递地址、服务端响应或凭据写入 receipt。首版每次 auth challenge 只主动发送
一次，避免重复邮件和账号限流。

离线验证使用 fake transport 与 `tests/fixtures/synthetic_fit.py` 在内存中生成的确定性
合成 FIT，不读取私人健康样本。真实账号 smoke、legacy shadow、生产切换与第五层正式
编排必须由授权流程单独批准；本手册不授权登录。

失败时：429 的长冷却读取 receipt `next_retry_at_utc` 后由第五层恢复；401 执行显式
`trainlab garmin auth`；解析或 raw 问题使用有界 `repair --strategy reparse`，对账使用
`reconcile`，不得直接修改 cursor/gap 或删除原始对象。
