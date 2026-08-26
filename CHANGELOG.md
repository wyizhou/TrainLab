# 变更日志

本文件记录 TrainLab 的重要变更。普通工作归入 `Unreleased`；只有用户明确要求发布并批准
版本号后，才能整理为正式版本。

## Unreleased

- 收敛 M11 content-first v4 的模型输出合同：模型只输出七日决策槽位，Host确定性注入周期、
  日期和成功状态；跑步/攀岩课程使用四个必填步骤对象，休息仅使用检查清单。业务Schema确定性
  投影为Structured Outputs wire；新增由业务/Host Schema确定性派生的Prompt规范语义块，自动
  校验根字段、七个槽位、课程类型、步骤和Host字段三层同构。历史RHR及活动平均/最高心率仅由
  Reader从已验证证据展示；新增Candidate/intent/receipt v3和只接受Candidate内结果的Finalizer，
  不改变旧失败证据。
- 将根开发 Harness 从 agentForge `v0.4.2` 三方适配到 `v0.4.4`：新增每任务冻结验证合同、
  Validator 固定输出、`FAIL`/`INCONCLUSIVE` 边界、反复失败诊断门和只读 Failure Analyst；
  保留 TrainLab 的 `source/` 产品布局、隐私与外部动作边界，未修改产品实现或正式 state。
- 完成M11 v3八封真实Gmail投递：用户一次性批准发送2026-08-12至18的7份日报和1份周报；
  官方REST单写者严格串行完成32次API调用和8次send，8个Gmail ID、实际Message-ID、RAW、
  text、HTML与CID全部闭合，零调用重放和独立Delivery/Data-Privacy Validator均PASS；未重跑
  Garmin/AI、未修改正式state，也未授权部署或定时运行。
- 完成 M11 OpenDesign v3 离线闭环：冻结既有AI日报、周报与课表，新增有界展示证据、共享
  Gmail table/CID渲染引擎、品牌与状态图形、香港时间、中文图表降级、真实活动/睡眠/七日趋势图
  和详细计划时间轴。历史心率分区仅展示Garmin/FIT session已记录时长，不从采样重新划区，也不
  用于课程处方。最终594项测试及Code、Design-Fidelity、Data/Privacy三类Validator全部PASS；
  未发送邮件、未调用Provider、未修改正式state。
- 启动 M11 Coaching Utility v2 内容返工：日报区分周计划原课与今日调整，周报增加健康/运动负荷
  总结、观察→意义→行动洞察和七天可执行课表；课程以 RPE/体感为主并补齐 SOS、步骤、开始门、
  降级和停止条件。TrainLab 不计算心率区间或目标 BPM，本批次只做离线 Candidate 验收。
- 收敛 M11 content-first v4 的 VC-006 模型输入边界：私人目标只按权威公开模板的1个标题、
  5个章节和19个有序字段解析，强度说明不进入模型；有限隐私词法明确活动名称、坐标、邮箱、
  文件名与斜线边界；Prompt和目标模板均绑定仓库权威SHA，输入或pending持久化失败时模型调用为0。

- 启动 M11 人类可读邮件展示：引入版本化日报/周报 ViewModel、显式字段映射、确定性静态 PNG、
  私有 CID `multipart/related` MIME v2 与完整 RAW 核验；新增仅限日报确认后再周报的两封 Gmail
  REST 样式 canary 主机；按 A-010 收敛 Token 原子刷新与崩溃恢复，移除同 UID 对抗产生的
  CAS、逐调用 SHA 和长时间正式锁；F05 可从严格验证的 durable send capture 恢复 Gmail ID，
  即使 Gmail 改写 Message-ID 或主回执发布前崩溃也不会重发；A-014 新增 VO₂ Max 30天与
  体重14天有界最近健康快照、实际测量日期展示和修正版日报续跑，仍不接入普通运行或部署。
- M10 Gmail 投递停止继续修补 MCP，改为官方 REST：新增 Desktop OAuth、owner-only 专用 Token、
  Google官方端点门、profile失败回执、确定性 RFC822 Message-ID、每阶段最多5次只读恢复、
  单次发送、RAW 读回、canary 人工确认和崩溃后只读对账；r04/r05失败证据及旧 `unknown`
  原样保留。r07允许以 Gmail ID 和 RAW 实际 Message-ID 闭合 Provider 改写，保留已收到的
  旧标题canary，并只为剩余6份日报与1份周报建立新标题动作。r08按用户A-012授权保留
  已发送8封，再建立8个更正标题的独立请求，最终累计上限16封。
- 增加 M10 固定滚动七日 Candidate 采集、7 日报/1 周报 AI 编排、精确 Gmail 自投递请求、
  临时 `-E2E-20260818-GTS` Workout 预览及 append-only 外部动作账本；所有真实写入仍由
  对话中的精确确认门控制。早期真实释放曾因 Gmail `invalid_grant` 安全停止，失败证据永久
  保留；最终4项测试Workout完成完整生命周期并清理为残留0，官方Gmail REST闭合旧标题8封和
  更正标题8封，累计16封。最终Code、AI与Delivery/Data-Privacy Validator均PASS。
- 为 M9 日报恢复增加 Structured Outputs wire v2、递归兼容检查、公开合成 Schema canary，
  并将下游证据链版本化为 attempt 2/3 失败后唯一 attempt 4；旧 wire 与失败证据保持不变。
- 完成 M9 单日 Garmin MCP 有界只读采集与离线日报闭环：固定日期、工具、依赖和预算，使用
  cached-token-only 的离线启动器，把 MCP Capture、FIT、调用收据和离线 AI 日报仅写入
  仓库外 Candidate；Gmail、Workout、Sites、cron 与正式 state 保持关闭。
- 引入 agentForge `v0.4.2` 开发 Harness，并将 TrainLab 收敛为根 `src/`、根 `tests/`
  的唯一项目布局；移除临时 `product/`、旧开发编排控制面和无消费者的 legacy 文档。
- 将产品 Harness、Schema、策略和公开默认值迁入 wheel 的不可变
  `trainlab.resources`，以外置 `TRAINLAB_INSTANCE_ROOT` 保存私有配置、state 与 logs。
- 新增完整哈希依赖锁、可复现 wheel/runtime bundle、安全解包验证器、离线安装器和
  Linux/macOS CI 真安装链；bundle 不再包含源码 checkout、开发 Harness 或私有数据。
- 用可重复、无个人信息的代码生成 FIT 夹具替代私人测试样本，并移除项目内的
  `test_data/` 依赖与历史样本展示。
- 完成 M4 `source/` 工程、Foundation v4 离线重建与教练 Harness v2；源码 `mypy src`
  清零，补齐分析输入、SQLite、Garmin mixin 和交付工厂的显式类型边界，并保留
  tests/tools 类型债为后续候选。
