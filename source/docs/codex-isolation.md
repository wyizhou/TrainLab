# Codex 子进程说明和 Skill 隔离

这是 M12 内部 Host 组件，不是新的 `weekly` 命令，也不是私人模型调用授权。
它补充[能力前检](codex-input-boundary.md)：只读沙箱主要限制写入，
`--ignore-user-config` 只排除用户配置，不能据此认定全局说明和 Skill 已被隔离。
相关区别见 [OpenAI 非交互模式](https://learn.chatgpt.com/docs/non-interactive-mode)
和 [Skill 加载位置](https://learn.chatgpt.com/docs/build-skills)。

## 做什么

`codex_isolation.prepare` 接受 Host 解析后的工作目录、用户根和原 Codex 认证根。
只检查路径及文件类型，不读取全局说明、Skill、认证文件或配置内容。它生成仅对子进程
生效的参数，不启动 Codex，不修改这些全局文件，也不复制凭据。

- 排除当前与默认 Codex 根下的 AGENTS、Skill、插件及记忆目录，用户 `.agents/skills`、
  工作目录向上的说明和 Skill 位置，以及管理级 Skill 根。
- 同时处理逻辑路径及符号链接指向的真实目标。若遮蔽范围覆盖任务目录、原认证位置或
  隔离程序本身，拒绝执行；不为了继续运行而放开该路径。
- Host 必须用 `validate_environment` 核对实际传给子进程的 HOME/CODEX_HOME。
  不替换登录位置，不在临时目录复制 auth.json，也不指定或变更用户的认证方式。
- `command` 只组合 Host 的明确参数，不通过 shell，不接受模型提供的命令。

## 两个平台

| 平台 | 方式及限制 |
| --- | --- |
| macOS | 使用已安装的 `sandbox-exec`，对这些位置设置 Seatbelt 读取限制。未读到的全局说明可能使 CLI 输出固定启动诊断；只有公开能力探针确认的诊断才能进入后续解析白名单。 |
| Linux | 使用已安装的 Bubblewrap，把已存在的说明和 Skill 目标挂载为空白只读视图。只创建工作目录里的空白配置，不在用户目录创建挂载目标。Codex 的 Skill 根必须已经存在，否则停止，避免 CLI 自动建立新的未屏蔽根。 |

Linux 的两个空白文件/目录是明确的配置脚手架，不是模型结果。它们可复用，但内容、权限、
owner、链接类型和目录成员必须正确。有限 fsync 失败先停止，之后可重新完成准备；这不
启动模型，也不重置[周任务账本](model-job-ledger.md)。用户全局文件不受这些挂载影响。
Linux 显式保留原 `/dev` 的普通设备访问，避免递归普通挂载的 nodev 标志使 `/dev/null`
和随机数设备失效；仍不改变原用户权限或增加模型工具。挂载语义见
[Bubblewrap 官方手册](https://github.com/containers/bubblewrap/blob/main/bwrap.xml)。

其他平台、工具未安装、路径或脚手架异常均拒绝；不安装依赖，也不降级为无隔离运行。
工具文件存在不代表内核一定允许使用。完整 Launcher 还必须通过本机公开合成能力探针，
实际验证屏蔽、工具往返和进程停止。Linux 参数测试不是 Linux 运行成功证明。

两种包装都不建立新 session 或 PID namespace，以便[进程监督器](model-process.md)
追踪同一 session 内的 Codex 和 FIT MCP。正常崩溃由已有监督/证据模块处理，
不会再复制一套进程管理器。

## 不能单独保证什么

本组件不是完整文件系统/网络沙箱：未屏蔽位置保持 Host 原有访问能力，认证也仍由原 CLI
管理。模型只允许访问 FIT 工具的约束来自固定能力配置、实际工具清单检查和工具本身的
范围验证。完整 Adapter 必须同时使用这些部件，绑定已测的 CLI/配置与当前平台，不得仅
拿本组件参数直接发起私人调用。全局配置被恶意同 UID/root 任意替换不属于本应用的绝对
保证；正常输入或环境不合规时仍停止，不产生备用启动路径。

代码回归见 [test_m12_codex_isolation.py](../tests/code/contract/test_m12_codex_isolation.py)。
测试只用合成用户目录和公开占位文件；本机实际子程序验证不读取用户真实认证或运行 Codex。
另行批准的公开 CLI 探针使用 localhost 假服务并额外阻断外网及私人读取，不是实际模型推理。
