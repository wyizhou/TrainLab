# ADHOC-0032-INFRA-003：独立副本mission绑定启动失败

- 失败次数1；在任何子Agent启动前被拒绝，工具未返回workflow/child run ID，状态`prelaunch_rejected`。没有Validator读取材料，也没有产品修改或测试失败。
- 原始错误：

```text
Mission '94dc6917-4cee-4836-b099-8358276006fa' was not found in mission directory '/Users/lucas/.pi/agent/missions/projects/ab1ac21a9a3162abba3e472fde62fbce03d3f124b10e706fb82fe6de2ccdd03a' for project root '/private/var/folders/dh/4th4rwbd7xlg8qslxz62hbjc0000gn/T/trainlab-gui32-review-f7ovkrsi'. If it was created in another worktree, run the request from that worktree.
```

- 原仓库/请求cwd/分支/HEAD/非managed副本身份保存在`state.json`。原工作区有既有未提交内容，不宣称干净；已捕获`source-preserved.diff`和`git-status.txt`，暂存为空、diff检查0。再次核对原source与固定副本全部116文件、4个资料哈希未变，验证输入未受污染。
- 原因：业务mission索引按项目根隔离，不能直接从新的中性固定副本根查原项目mission。不是SDK/Chrome/产品故障，不重算产品修法失败。
- 同协议恢复：已读取tool-reference/workflows，工具明确支持只读隔离工作流`mission:false`。固定副本验证显式不跨项目绑定业务mission、不获得共享mission state；原业务mission不修改。保持同一native async workflow、相同fresh Validator角色/模型/工具与完整客观材料，持久输出绑定照旧，主Agent在业务协调记录关联返回receipt。
- 这不是换前台/外部CLI/执行模式或绕过独立验证；不使用resume或追加旧实例。脚本静态校验实际返回`ok:true/errors:[]`；同协议重派已获异步工作流启动回执`eee22d31-30c6-4cfc-874b-76483f6f842d`，mission绑定障碍解除，验证执行/结论仍待原生通知。若后续运行出现新故障，停止受影响调度报告，不盲目循环。
