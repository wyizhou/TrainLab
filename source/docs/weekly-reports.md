# R4 本地周报、修订与发布封存

本模块提供内部 Python 接口，从重新验证的两阶段结果生成中文 Markdown 和 PDF，并允许发布前的显式本地修订。完整运行命令、真实 Gmail/Garmin 动作与调度仍由后续模块提供。

## 指定实例、周期和修订

接口位于 `skills._shared.fit_weekly.report_revisions` 与 `report_artifacts`。`root` 必须是显式的新实例根；`end` 是原周窗口的 UTC 结束时间，不接受任意路径作为报告输入。

1. `report_revisions.create(root, end)` 调用 `coaching.report` 重新核验原请求、捕获、成功状态、版本、SHA 和固定计划，再保存 `revision_id="ai"`。该保存动作不等于已有可发布产物。
2. `report_artifacts.render(root, end, revision_id, revision_sha)` 从指定修订生成同内容的 Markdown/PDF，字节先耐久化，最后提交产物清单。修订 SHA 使用 `model_job.sha(revision)`；所有后续读取必须显式提供该身份。
3. `report_revisions.edit(root, end, *, base_revision_id, base_revision_sha256, revision_id, target, content)` 只接受 `target="summary"` 或 `target="plan"` 及其完整原业务结构。合法内容创建独立修订并自动重新渲染；同身份同内容可精确重放，不同内容冲突。渲染失败留下可恢复修订，不留下可发布清单。
4. `report_revisions.read(root, end, revision_id, expected_sha)` 验证来源和整条修订链。`view(...)` 返回用于渲染和课程读取的当前有效视图。
5. `report_artifacts.read(root, end, revision_id, revision_sha)` 返回 `Bundle(revision, manifest, plan, markdown, pdf)`，读取前核对当前来源、内容和实际产物字节。

总结编辑不接收计划、日期、统计或原始 SHA 字段。计划编辑继续依据原先冻结的跑步输入重验；总结仍按原总结事实重验。原 `summary request.fixed_plan`、原 AI 输出、细读、目标、周快照和历史报告不改写，不增加模型或细读调用。修订不伪造新 capture，也不自动进入 AI 历史。

## 原来源与有效内容

`fit_report_revision_v1` 明确保存 `source`（组合报告、Host 报告、原计划/总结和原请求 SHA）、`plan_content`、`summary_content`、有效内容 SHA、父修订与编辑目标。有效视图的计划不带 `original_plan_sha256`；修订后的 SHA 只称为 `effective_plan_sha256`。原 `fit_coaching_report_v1` 及其 `raw_*` 含义保持不变。

`fit_report_artifacts_v1` 绑定周期、修订、有效计划、视图、渲染实现/字体和两种产物 SHA。文件位于实例的 `reports/<revision_sha>/report.md` 与 `report.pdf`；目录 0700，文件 0600。符号链接、硬链接、不安全权限、缺失或损坏字节不能成为发布输入。路径不含调用方提供的自由文件名，搬迁后仍能读取与精确重放。

中断可用同一个 `render` 恢复。已有文件必须逐字相同；已提交清单的缺失文件只能由产生同一清单的当前渲染器恢复。不同实现或环境产生不同字节时拒绝覆盖，需要保留原证据后由人处理。未知修订/Schema 或损坏来源直接拒绝，不以重跑模型恢复。

## 给后续发布模块的固定选择

`report_artifacts.seal(root, end, revision_id, revision_sha)` 在与编辑共享的实例锁下耐久保存 `fit_report_publication_v1`，绑定唯一修订、产物清单、Markdown/PDF 字节和课程 SHA。封存之后整个原周期不可继续编辑或选择另一修订；没有撤销、重置或因 unknown 重新领取授权的接口。

R5 必须在任何外部动作 intent 之前先调用该封存接口，再让邮件、PDF 附件与所有 Garmin 课程统一消费 `read_sealed(root, end)` 返回的同一 Bundle。不得分别读取 latest。重复封存相同选择只是本地读回，不授权重新发送、创建或排期；R5 仍须独立动作账本。封存本身不发送邮件、不生成远端 ID、不创建 Workout，也不声明发送成功或 unknown 对账完成。

计划日期保持原冻结周一至周日；R4 不平移日期或排过去课程。后续调度和动作模块必须保留原日期及其不排过去的业务边界。

## 输出与检查

两种格式消费同一个 `report_view.blocks` 内容树，含七部分、全运动清单统计、证据与适用条件、缺失与覆盖、最多三项跑技、其他运动说明、计划对比、七日完整步骤/重复组/RPE/技术备注/停止条件。休息日明确无 Workout。图表只用清单中已知设备时长，部分已知有标注；未知不补零，设备历史心率与分区不用于未来处方。

PDF 使用随代码再分发的 OFL 中文字体，长段落、跨页表格与超过一页的单课可以自然拆页。没有固定页数或图表数量要求。自动文字/页面与字体检查不替代逐页渲染视觉检查；交付时检查实际全部页的中文、图表、表格和课程末尾。

确定性校验沿用 R3 的明确结构、日期、剂量、来源和明显处方检查范围，不能证明任意自由文字、目标解释或训练合理性；没有第三次生产模型调用。

合成回归：[修订](../tests/code/contract/test_m12_report_revisions.py)、[产物与封存](../tests/code/contract/test_m12_report_artifacts.py)、[PDF 内容](../tests/code/contract/test_m12_report_pdf.py)、[无测试目录运行](../tests/code/integration/test_m12_report_pipeline.py)。这些测试不读取正式私人资料或调用真实业务服务。
