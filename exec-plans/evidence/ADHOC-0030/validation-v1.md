# ADHOC-0030 T4 首次独立验证

结论：**冻结前提失败；AC-01～06的完整验收无法判断，已停止受影响验证。** 不据此认定产品或公开文件损坏，不代替主Agent验收或远端交付。

## 已执行检查

完整读取 `AGENTS.md`、`subagent-templates/validator.md`、`exec-plans/evidence/ADHOC-0030/contract-and-plan.md`。随后用一次只读 Python 检查读取冻结 JSON、核对当前 Git 身份、直接计算 `.git/index` 摘要，并按快照逐项核对115个公开文件的 SHA256、字节数及实际 `lstat` 模式；仅读取指定四个公开 states 文件，没有遍历私人 states。

命令/方法与结果（该组合命令退出0，表示脚本执行完成，不代表验收通过）：

| 场景 | 预期 | 实际及退出结果 |
| --- | --- | --- |
| 冻结文件真实性 | SHA256等于任务给定值 | `4fea57268fed2c4d8d8c2fdf1b368f571efdfc32d3d34ace0a80408d843dfa4b`，一致 |
| `git rev-parse --show-toplevel` | 指定仓库 | `/Volumes/DiskOther/Code/TrainLab`，退出0 |
| `git branch --show-current` | 指定分支 | `work/adhoc-0029-agentsmd-upgrade`，退出0 |
| `git rev-parse HEAD` | 指定HEAD | `ec36ce7bbdf9d70a509238dd771b155eb6f84261`，退出0 |
| Python读取 `.git/index` 并计算SHA256 | 与冻结摘要相同 | **不同，详见F-0030-V01** |
| `git diff --cached --quiet` | 无暂存变更 | 退出0；不能证明索引字节未变 |
| Python逐项比较115个文件的sha256/bytes/mode | 每项完全相同 | `file_errors []`，已列入快照文件全部一致 |

## 问题

**F-0030-V01：冻结索引摘要不一致（AC-05及T4冻结停止条件）。**

复现：读取 `review-snapshot.json` 的 `index_sha256`，与 `hashlib.sha256(pathlib.Path('.git/index').read_bytes()).hexdigest()` 比较。

- 冻结值：`ca081c39357d158a043573e2a2d8bcf0e4a8ed6249cd4b56d9cadfb06343068c`
- 实际值：`f14c937ccdcc50daae2bc6ad038ed4d4e3f21e50eae70b6732e39cd1b225c2a7`
- 该实际摘要在本次调用 `git diff --cached --quiet` **之前**取得。
- 冻结JSON的顶层字段为 `head`、`index_sha256`、`branch`、`observed_at_utc`、`files`、`tracked_absent`，未见独立的索引逻辑摘要字段。
- 索引字节变化可能只是元数据变化；现有证据不能确定原因，不能将其解释为候选内容损坏，也不能以无暂存变更替代要求的冻结一致性。

按照“变化则停止”要求，本轮不继续追加检查、恢复、重试或变更标准；没有修改任何仓库文件或Git内容。

## 未验证与限制

- 尚未完成公开路径集合及327项删除的独立核对、101旧文件原字节保护、8份协调文件完整差异、无替代CI、大小写边界、JSON/Markdown/链接/规范状态、全部候选及ZIP成员与内容隐私审查。
- `closeout-status.diff` 的19处空白异常尚未复现或解析，不能判断是否有效补丁上下文，不建议据此更改受保护历史字节或关闭检查。
- 未完成验证结束时的冻结核对；本轮入口已不满足冻结要求。
- 未联网、安装依赖、调用业务Provider、执行历史证据代码或运行旧产品测试；这些项目不能记作通过。
- MEMORY大小写索引落实、精确暂存、提交、推送及PR核对尚属主Agent后续工作，本轮未宣称交付完成。
- 已列入快照的文件一致，不等于完整候选集合一致，更不等于不存在秘密。

```acceptance-report
{
  "criteriaSatisfied": [{"id": "criterion-1", "status": "satisfied", "evidence": "返回冻结入口的实际摘要不一致证据、停止原因和未验证范围。"}],
  "changedFiles": [],
  "testsAddedOrUpdated": [],
  "commandsRun": [
    {"command": "python3 inline: snapshot SHA256, Git root/branch/HEAD, index SHA256, cached quiet, 115 file sha256/bytes/lstat mode comparisons", "result": "passed", "summary": "脚本退出0；文件比较无差异，但索引摘要检查发现冻结不一致，验收不通过。"},
    {"command": "git diff --cached --quiet", "result": "passed", "summary": "退出0，无暂存差异；不证明索引字节一致。"}
  ],
  "validationOutput": ["冻结索引期望ca081c39…，实际f14c937c…；115文件字节、大小、模式一致。", "完整T4验收无法判断，按冻结停止条件停止。"],
  "residualRisks": ["索引变化原因未确定。", "完整路径、原基线保护、协调差异、隐私/ZIP、格式和链接检查未完成。", "远端交付尚未执行或核对。"],
  "noStagedFiles": true,
  "diffSummary": "未修改受审内容，仅写验证报告。",
  "reviewFindings": ["blocker F-0030-V01: .git/index SHA256与冻结快照不一致。"],
  "manualNotes": "独立读取当前合同和规则；未参考历史裁决或执行证据代码。已停止受影响验证，报告不构成产品失败判定或主Agent最终验收。"
}
```
