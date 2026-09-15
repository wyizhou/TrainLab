# 可替换命令运行器

产品配置只选命令入口与适配协议（`codex` / `claude`），不填写模型、推理等级或 Provider。Python 从宿主环境读取当前选择，只把非秘密的选型设置放入身份快照；命令启动、请求封装和终态提取集中在 `command_*` 模块。环境没有选型时沿用 CLI 默认值，不强加型号。

| 边界 | 实现 |
| --- | --- |
| 命令身份 | `CommandSpec` 绑定适配协议、解析后的可执行路径与文件 SHA；v2 授权按周、stage、命令 SHA、墙钟和截止精确匹配。 |
| 一次执行 | 两阶段都使用原 `model_job`、`model_process`、`process_capture` 与 parent watcher；不新增重试循环。 |
| 终态 | Codex 使用默认最终 stdout 通道；Claude 解析单个 `type=result/subtype=success/is_error=false` 包络，再严格解析 result 字符串。必须完整输入、确认退出、退出0、无监督错误；完整业务 Schema 与证据校验仍执行。 |
| 恢复 | 原请求/profile、prepared、进程终态及结果 SHA 不变；新命令目录不存在才读旧 Codex 材料。旧 adapter/runtime 启动方法明确拒绝，不能成为备用执行器。缺失/不完整材料保持 unknown。 |
| Codex 环境 | 仅读取 config.toml 的模型、effort、选中profile/Provider相关白名单；忽略全局instructions/MCP/插件。选中Provider以等价专用别名保留endpoint、环境认证名称和原模型选择，令请求/流重试为0；不复制认证文件。 |
| Codex 原生工具 | 已有 code-mode host 在绑定其文件 SHA 后启用；完整原生 Lite 请求、ALL_TOOLS、全局对象与实际越权拒绝单独审计。只保留 FIT 和原无外部动作辅助工具，文件补丁与团队工具关闭；不把原生请求裁剪成旧协议。 |
| Claude 环境 | 仅读取 settings.json 的 model/effort 和受支持环境选型。空 setting-sources、空内置tools、strict MCP、禁slash/记忆/指引、专用system prompt；只允许预绑定FIT工具。请求重试及非流式备用请求关闭。 |
| 细读 | 两命令共用原DetailHost范围、20次共享账本、20分钟和缓存。Claude使用MCP文本通道保留数值原字节，避免CLI重新序列化结构化内容改变SHA；不放宽数值或SHA校验。 |
| 隔离 | 原macOS/Linux OS指引/技能遮罩继续使用。Claude还遮罩其指引、插件、命令、agents、历史目录及托管设置文件；任何必要隔离不可用则拒绝。新环境不加载工作树说明、任意MCP或历史。 |

每个新阶段在原账本确认尚无 intent 后、写入 intent 前，复核现时命令、源码身份、准备文件、冻结请求和环境选型，并调用与真正启动相同的隔离及命令准备入口，检查 job、logs、sqlite、tmp 及其父级私有目录和实际命令依赖；缺失、权限放宽或链接替换均拒绝。真正启动前再次执行同一检查。检查失败不创建新 intent，不消耗阶段次数。已有 intent 的成功或 unknown 路径只读恢复，不检查当前环境、不新启动，也不删除或退还原 intent。外部设置可能在两次检查之间变化：意图之后的变化仍保留已领取次数并在启动前拒绝，不能承诺全局原子性。

每个新阶段启动前要验证当前公共合成能力证明，绑定实际可执行文件、源码、Prompt、Schema、选型、超时与原授权截止；实际请求/终态、细读完整传输和拒绝、缓存、毫秒尾段与禁自动请求重发必须一致。计划阶段的非跑步拒绝和总结阶段的非跑步完整结果分别检查；共享20次额度保存实际逐次Host回执和已用完额度后的缓存回执，不能用通过标记代替。能力文件是可信Host保存的诊断证据，不是防同UID篡改的远程证明。新环境或代码变化必须重新检查，不能沿用旧PASS。

原生 Codex 读取环境已配置的绝对路径 `model_catalog_json`，完整保留目录中的模型及顺序、默认模型、推理、原生工具模式和 Lite 协议；仅在私有工作副本中把 `apply_patch_tool_type` 设为 null。源/派生 SHA 和逐字段差异进入运行身份，原目录不改写。这是宿主 CLI 的公开目录配置，不是训练产品新增的型号配置；运动教练仍不选择模型或推理等级。

没有显式目录时，目前仅对已验证的无认证、无缓存且没有额外功能配置的 Provider 环境使用安装二进制的 bundled 目录，并在 macOS 禁网、禁止写入的进程中离线导出。已有缓存不能仅因内容相同就冒称有效命中；当前无法证明其时效和身份时明确拒绝，不静默换成 bundled。其他有认证默认目录、相对目录路径及不可用的离线平台组合尚未证明，须由宿主环境提供其已确认有效的完整公开目录并重新完成能力检查。合成认证加显式目录路径的验证不代表真实账户及所有缓存组合已验收。

Codex 内置 OpenAI Provider 的 `openai_base_url` 同步到专用别名的 `base_url`，保留 `requires_openai_auth` 和原认证存储选择，不改为另一环境密钥来源。当前受测 0.147.0 在配置地址与 `OPENAI_BASE_URL` 同时存在时使用配置地址；仅设置该环境变量未改变内置路由，适配器保持这个实际行为，不能把变量名称当作有效覆盖的证据。`chatgpt_base_url` 与 `CHATGPT_CODEX_BASE_URL` 原样保留；本轮 API key 合成对照不证明 ChatGPT 登录路由。自定义 Provider 继续使用自身显式地址及环境认证键/头，内置地址设置不会覆盖它；环境头使用有效 TOML 映射传给 CLI，秘密值不进身份或命令。无显式地址的自定义 Provider、非 Responses 协议及其他不支持的组合明确拒绝，避免隐式落到默认服务。

Codex 0.147.0 内置 OpenAI Provider 的原生消息可附带 `internal_chat_message_metadata_passthrough.turn_id`。审计仅在权限说明、环境上下文和用户输入消息中接受这一可选对象：只有 `turn_id` 一个字段，值须为小写十六进制 UUID 格式，同一请求中出现的值须一致。Host 指令消息和工具表不增加元数据入口；完整请求原样保留，未知字段、坏元数据及正文、权限、环境或工具变更仍由原检查拒绝。此兼容处理不代替绑定当前源码与实际 CLI 的能力检查，也不证明真实账号或线上服务。 2026-09-11 两条 Codex 总结的历史失败原件保留：首个请求的工具表没有 FIT，首个调用返回工具不是函数。受控延迟检查复现了可选 MCP 尚未完成注册就开始请求的路径。FIT 现配置为必需 MCP，CLI 必须在原 10 秒启动期限内完成初始化；初始化失败则停止、零模型请求，不以缺工具的上下文继续。此设置不增加阶段次数或模型/HTTP重试，已领取的 intent 仍不退款。当前实际 CLI 的完整能力仍须绑定修改后的源码重新核验；单次成功不抹去历史失败，也不能把并行本身认定为根因。

当前适配识别明确的两种CLI协议，并非接受任意Shell字符串。自定义命令应提供支持的协议；未知协议在模型intent前拒绝。Codex自定义Provider支持Responses、endpoint与环境认证键/环境头；内嵌凭据头、命令型认证helper及无法识别的选型配置会明确拒绝，不能静默切回OpenAI。Claude的命令型认证helper目前同样拒绝。真实账号、Provider和模型质量需各自精确授权与验收；合成本机协议服务不证明真实认证或线上服务。

实际CLI参数依据本机帮助及[Codex官方配置](https://learn.chatgpt.com/docs/config-file/config-reference)、[Claude CLI参考](https://code.claude.com/docs/en/cli-reference)。CLI版本/未公开开关以绑定二进制的实际失败探针补充证明，不能仅依据参数名称宣称有效。
