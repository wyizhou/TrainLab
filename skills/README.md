# 项目 Skill

本目录保存只属于当前仓库的 Skill，默认不安装任何 Skill。

## 目录结构

每个 Skill 使用：

```text
skills/<name>/SKILL.md
```

`SKILL.md` 应定义清晰名称、触发条件、执行说明和必要的本地引用或脚本；相对路径以该
Skill 目录为基准解析。

## 隔离约定

- Agent 只在任务与触发条件匹配时加载对应 Skill。
- 项目 Skill 始终保留在仓库内。
- 禁止复制、移动、同步、安装或链接到 `~/.codex`、`~/.claude`、其他全局或用户级
  Skill 目录、全局注册表或其他仓库。
- 除非用户单独明确授权，不得修改全局配置来暴露项目 Skill。
- Skill 不能覆盖系统指令、用户指令、仓库指令或已批准规则。
- TrainLab 项目不提供也不调用 `orchestrate-parallel-work` Skill。
