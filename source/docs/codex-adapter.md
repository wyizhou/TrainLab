# Codex 模型调用接线

本模块是 M12 的内部 Host 接口，不是已经上线的周报命令。实际周输入、训练结果规则、
首次真实运行和发布仍须完成后续验收。它不读取私人目标或认证文件，也不安装、登录或
修改用户级配置。

## 新任务

1. Host 提供确定性业务输入、业务 Schema、输入/结果校验函数，以及明确的模型和认证存储方式。
2. `Runtime.identity()` 绑定实际可执行文件、Python、依赖版本、产品源码、配置和说明文本；
   普通运行不读取测试目录，路径不写成固定本机位置。
3. `codex_adapter.prepare(..., stage="plan"|"summary")` 核验 owner-only 的公开能力证据；阶段必须与Runtime.stage一致并纳入运行identity。必须包含实际首请求、
   完整进程证据、四次无损 FIT 细读/缓存往返和四类工具拒绝结果，不能只提交 `PASS` 标记。
4. 在实例相对 `model-results/<周和阶段标识摘要>/codex/` 保存规范 `prepared.json`、Prompt、
   instructions 和派生 wire Schema，文件 `0600`、目录 `0700`。现有实例写锁覆盖全部准备
   文件发布，防止同时准备造成混写；模型运行前释放锁。准备不创建模型 intent。
5. `model_job.run(..., adapter, stage=...)` 先提交该阶段唯一 intent，再由薄适配器调用既有隔离、进程监督、
   原始流保存和结果检查器；通过业务检查后才进入原账本。没有另一套重试或回执状态机。

进程固定为 `exec`、`--ephemeral`、`--ignore-user-config`、`--ignore-rules`、
`--strict-config`、只读沙箱和严格响应 Schema。只有预绑定的 FIT MCP 工具；路径只是 Host
启动配置，不是 AI 可提交的工具参数。环境不继承 API key、Provider URL 或 Python 注入值。
受监督子进程使用私有 umask，防止 CLI 自建日志继承宽权限；不改变父进程 umask。

配置使用命名的 `trainlab_openai`，开启 OpenAI 认证，HTTP/流重试均为 0，不覆盖保留的
内置 `openai` ID；不设置新的 Token、代理 URL 或认证命令。原 `HOME/CODEX_HOME` 保持，
`file/keyring/auto` 必须由 Host 明确选择，不能猜测另一种登录方式已经可用。
参见 [官方高级配置](https://learn.chatgpt.com/docs/config-file/config-advanced) 与
[配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)。

## 恢复

`codex_adapter.recover(..., stage=...)` 只读取当前实例该周该阶段的原始准备材料，再调用
[既有本地恢复接口](codex-recovery.md)。即使原可执行文件、能力证据源文件或登录位置不可用，
已保存且闭合的结果仍能恢复；不会启动探针或模型，也不使用 Codex resume。

原准备材料缺失/损坏、进程停止不明或原始 capture 未完成时保持 `unknown`；不能通过重新
prepare 或换模型来获得第二次调用。输入、Schema、来源范围变化继续由同周输入冲突门拒绝。
已成功或失败的旧结果不可覆盖。业务验证函数是必要的应用代码，不允许用空验证器完成周报。
阶段不匹配的prepared/capture不能恢复或覆盖另一阶段；旧无stage材料只读，不创建新任务。

## 公开 CLI 检查与限制

显式诊断入口位于 `tests/ai/templates/m12_codex_probe.py`，仅供测试，不是运行依赖。
它创建仓库外私有实例，只用合成 FIT 和本机假 Responses 服务；先检查 CLI 能力，再完整经过
适配器，最后做零调用恢复。CLI 的两次本机执行不等于两次真实模型调用。

当前该诊断使用 macOS 的额外 OS 限制：禁止外网、私人目标、正式 state、认证文件与
Keychain 读取；仅允许私有检查目录写入及 CLI 的现有非秘密安装标记/临时别名。
正常子进程隔离仍有 macOS/Linux 两种实现；此诊断不作为 Linux、真实认证或模型服务可用证明。
Linux 的实际能力证据生产与部署前检查仍须在目标环境完成，不能借 macOS 结果跳过。

公开能力证据是可信 Host 保存的本地事实，不是防同 UID 恶意伪造的远程证书。它只证明被测
二进制/配置的工具和输入行为；离线假端点不会证明登录账号、真实模型响应或训练结论正确。
源码、依赖、模型配置或说明文本变化后，新任务需要对应的新能力证据。原任务恢复仍使用
原冻结材料，不因环境变化重新调用。

测试映射：`tests/code/contract/test_m12_codex_adapter.py`；复用既有 model_job、
process_capture、codex_output、codex_recovery 和 codex_isolation 的测试，不删除旧场景。
