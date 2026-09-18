# AU32-V1-001 验证材料隔离处理

- 对应要求：AU32-06/T8，Validator只接收当前客观要求、已审核拆解和受审材料，不接收历史裁决；同时AGENTS要求会话开始读取PLAN及关联执行计划。
- 客观事实：workflow `31d7a779-1837-454a-973f-2f2e6b03ead7`、Validator `5bbe1d62-ae8b-4708-91fa-ec6cd9afdb96` 已完成。其开场读取原业务PLAN时看到了历史结果摘要，报告明确不能无保留签署T8。没有读取Developer输出/其他Validator报告的声明保留；不把材料暴露改称完全隔离。
- 已有行为证据：本轮原报告记录282项全量测试、62项独立SDK/存储/CLI、11项前端与默认Chrome2项通过，受审96文件未变。这些是有效检查证据，但不替代未满足的独立输入条件。完整[报告](../auth-maintenance-validator-report.md)及原始证据保留，不删除或改写原结论。
- 主Agent核对：96个当前source逐字节匹配该Validator冻结清单，清单摘要`49fce46458eaeef9369590ee21ad27e6a05d5330af59d552632b4f3238dee24e`；原分支/HEAD不变，工作区仍有既有未提交内容，无产品修改。
- 处理：不降低独立验证标准、不改产品。依据允许固定副本验证的现有规则，导出全部96个公开source、逐字节AGENTS/角色模板、来源分支/HEAD和diff，制作只含客观目标/合同的PLAN及执行计划视图，既能遵守恢复规则，又不读取历史裁决。没有复制MEMORY、正式states、历史报告、旧临时检查或Git历史；新建全新Validator在副本检查，不访问原仓库。
- 副本不是新的业务计划或Git工作树：不提交/暂存，不改原PLAN规则含义；只读视图和任务包由主Agent协调维护。原源码、测试、README及规则不做脱敏删改，全部byte/hash一致。独立测试由新实例重新设计，不把上一轮62项临时测试作为输入。
- 当前恢复证据：`source-manifest.json`、`provenance.json`、`packet-manifest.json`；`source-snapshot.zip`保全受审源码，`review-input-packet.zip`保全无裁决任务材料。临时副本位置在`review-cwd.txt`。先核对输入完整性再派发；输出核对后由主Agent回收至持久证据目录。
- 首次处理计数：材料隔离失败1，处理方式1为固定副本＋客观协调视图＋全新Validator；后继结果见下文，旧记录不清零。产品修复失败新增0，原D31-LIVE/RV/INFRA全部保留。

## 固定副本结果及第二次材料处理

- workflow `13aa86c3-241f-4597-a2fc-c75f6b875ef4` / Validator `96729314-3c93-4918-974b-5f1ec22b6333` 已结束，未接触原仓库/旧结论。认证维护39项独立检查、实际CLI/PTY、默认Chrome2项通过，96个source和42个安装文件一致；报告见[固定副本验证](../auth-maintenance-isolated-validator-report.md)。
- 原材料污染已消除，但主Agent的导出包遗漏source外运行依赖references，全量pytest为269通过/13失败（8缺资料、5初始缺Web构建）；构建后不依赖资料的3个Web检查通过，其余不预写通过。按同类材料问题保留AU32-V1-001，累计材料失败2，不改称产品缺陷或清零。
- 原因核对：`context.py`读取`references/README.md`；`contracts/interfaces.py`注册`references/longdou.md`与`garmin-fit-parsing.md`。它们是公开运行期技术输入，不是历史认证裁决。旧副本确实没有references。主Agent完整阅读三份文档和检索实际引用，没有复制私人文件或DS_Store。
- 第二种处理与上次区别：创建新固定副本，保留完全相同96个source、客观协调视图，追加全部4个tracked references文件及哈希；先由主Agent在新外部非editable环境执行安装→npm ci→build→全量pytest的材料完整性预检，全部退出0，282通过。预检日志保存在副本外，后继Validator不会看到裁决或旧临时测试。
- 已有恢复证据：`../auth-maintenance-material-recovery/preflight-results.json`、`preflight-pytest.log`（282通过）、`reference-manifest.json`及任务包zip；原/副本source及资料前后逐字节一致。该预检证明材料/构建障碍已消除，不代替独立复验或最终主验收。
- 主Agent导出脚本首次因stdin非UTF-8报SyntaxError、退出1，Python尚未执行，无部分复制；改为纯ASCII的复制脚本后成功，中文任务内容使用文件编辑工具补入。此为父级准备错误，不是子Agent平台/产品修复失败。
- 最终计数：材料失败累计2保留；方式1未完整闭合，方式2经全新Validator核对96+4输入、无历史接触及完整282项回归通过，材料问题已恢复。产品修复失败新增0，没有因本次流程问题自动再做第三种材料修法。
- 后继结果：workflow `4af5788a-cbbc-4b91-91b2-67e7030064d5` / Validator `dbd38663-02f0-4385-9414-059625a37e51` 已结束；发现的两个既有Context/资料错误边界与材料隔离不是同一问题。来源编号冲突、代码前后不变证据及范围裁决见[主验收](../auth-maintenance-parent/report.md)，不篡改原报告或历史计数。
- 下一动作：材料问题关闭，认证本地范围已由主Agent亲自复跑验收；真实登录/同步与两个既有Web问题继续分别保留，不宣告整体完成。
