# Pi 运行时适配器

Pi 是 TSPi 的传输与交互 Host。Python 拥有确定性的 Research Kernel 和计算服务；Pi
读取规范 ResearchMap。

## 公共接口

Root 会话使用：

```text
research.read         有边界地读取 ResearchMap 与计算状态
research.change        提交一个原子 ResearchMap ChangeSet
research.strategy      记录或评审 Claim strategy
research.interpretation 解释已完成 Attempt
research.checkpoint    用 disposition 结束当前 Research Turn
research.continuation  兼容 required-action ledger
system.prompt          查看有效 prompt 来源
compute.environment   本地与远端计算环境目录
compute.run          一个有边界的计算生命周期
execution.dispatch      暂停或恢复一个 Node 的新任务派发
analysis.run       已注册的本地分析
artifact.seed           Node 所属的结构 Artifact
artifact.import         Node 所属的输入 Artifact
artifact.compare       确定性结构比较
artifact.render        已注册的可视化 Artifact
report.build        绑定 revision 的报告包
review.run             建议性 Review
review.respond         Root 对已完成 Review 的处置

`notify.send` 是 Host/Monitor 拥有的投递 capability，不在 Root Agent 的默认工具清单中。
```

Slash command 调用同一个命令服务：`/research`、`/compute`、`/runs` 和
`/debug prompt`。它们是交互语法，不是另一套 API。

## Root 会话

对话不是科学状态。解释之前的回合前先读取当前 `ResearchMap`；写入后使用返回的 revision
或 `research.read mode=summary`。research extension 可以在 prompt 中加入有边界的摘要，但不能
写入 map。方法选择、结果解释与停止决策仍由 Root Agent 负责。

`research.read` 模式包括 `map`、`summary`、`context`、`liveness`、`detail`、`locate`、
`validate`、`operations`、`decisions`、`evidence`、`storage`、`artifacts`、`capabilities`
和 `runs`。`capabilityKind=compute`
列出计算 capability；`capabilityKind=analysis` 解析分析方法。使用 `kind` 和 `id` 聚焦
一个 map 对象，不要为 ResearchMap 发明额外的上下文词汇。

## 隔离

Compute 与 Review 子会话只接收有边界的类型化任务包，无权编辑 ResearchMap。Compute
动作回执、调度器状态和解析器输出属于运行记录；Review 建议也只具有建议性。Root 检查
Artifact 后，通过 `research.change` 应用科学解释。

前台 UI 与 `/runs` 浏览器都是只读展示。TS Web 直接读取规范序列化 ResearchMap，不会
重新构建一份图或保存平行快照。
