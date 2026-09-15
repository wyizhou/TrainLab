# ADHOC-0030 交付证据

范围：按用户要求删除旧CI，保护当前公开成果及既有删除，经本地独立验证和主验收后提交、推送当前功能分支并创建PR；不合并main，不启动产品开发。

- [已归档执行计划](../../completed/ADHOC-0030-retire-ci-and-publish.md)：RC-0030-01、任务状态、问题与实际交付记录。
- [合同与审核拆解](contract-and-plan.md)：冻结要求及独立验证输入，不附开发者辩护或历史裁决。
- [公开原基线](baseline.json)：本轮前110公开文件及326个已有删除的摘要/路径，无私人文件内容或API下载链接。
- [预冻结本地检查](checks-before-review.json)：113文件候选的180项检查，不替代后续完整冻结及独立验证。
- [开发过程原证据](development-evidence.zip)：Planner、两轮Developer、原失败、修复检查及主观测/格式诊断，10项。仅作历史数据，不执行其中删除脚本，不将自检当独立结论。
- [首次独立原报告](validation-v1.md)与[当轮快照](review-snapshot-v1.json)：首次在入口停止，完整验收未完成；原文不改写。
- [摘要载荷观测](index-digest-observation.json)：分别记录Git条目与索引容器摘要及115文件/327删除一致性；不能以两种载荷摘要不同推断文件被修改。
- [第二轮独立报告](validation-v2.md)、[受审快照](review-snapshot-v2.json)：118文件候选及本地交付前提通过；不预先证明Git/PR已交付。
- [主验收](parent-acceptance.json)与[189项重跑结果](checks-parent-final.json)：主Agent亲自检查冻结候选及独立证据。
- [验证原始证据](verification-evidence.zip)：validator/为独立检查，parent/为主检查脚本，11项；区分角色，不执行归档脚本。
- [精确暂存原收据](staged-verification.json)：完整124文件及树464dab9a…，对应首次提交，不包含收据自身或后置归档。
- [首次交付收据](first-publication.json)：c302e67三端一致、[PR #20](https://github.com/wyizhou/TrainLab/pull/20)为OPEN、main未变；观察时无检查或Actions运行。后置归档提交以PR最新头和最终报告为准。

旧ADHOC-0029及更早证据保持原字节，本任务不会把其历史失败或INCONCLUSIVE改判。首轮临时检查器的异构元数据比较失败、主Agent过早假定CI已删除的观测错误、历史diff格式诊断和规则集403均保留于本任务问题记录，不计为新的产品失败。

## 检查适用性

- 当前没有产品工程及可运行产品测试；不恢复旧source、不安装依赖、不读取私人state、不调用业务Provider或主动运行GitHub CI。
- 对完整公开候选及原5个证据ZIP检查路径、类型、原字节、CRC和常见秘密签名；扫描不能证明绝对不存在所有秘密。
- 历史`ADHOC-0029/closeout-status.diff`是unified-diff载荷。原始no-index空白检查退出3，19行仅含空上下文标记；原文件不得为绿灯裁剪。该文件以原摘要、补丁语法解析及标记合法性独立检查，普通文件仍执行空白检查，不改变全局Git规则。
- 规则集接口返回HTTP403并提示私有仓库套餐功能限制；分支API可查询protected字段。保留限制，不据此宣称已查明全部规则集，不修改仓库可见性、套餐或保护。

原始API响应含带查询参数的私有下载链接，只留仓库外隔离证据，不复制进Git或PR。后续公开记录仅保存必要脱敏摘要、检查结果及已核实的提交/PR事实；尚未发生的交付不记成功。
