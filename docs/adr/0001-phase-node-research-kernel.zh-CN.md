# ADR 0001：Phase 与 ResearchNode 内核

[English](0001-phase-node-research-kernel.md) | 简体中文

- 状态：已接受，由 [ADR 0003](0003-minimal-research-kernel-and-gates.zh-CN.md) 修订
- 日期：2026-08-23

## 背景

研究叙事、可执行工作和科学命题需要分开。一个对象不应同时承担导航、计算产物、
依赖血缘和 Claim 语义，否则会复制状态并把标签误作流程策略。

## 决定

Research Kernel 使用三个正交层次：

```text
ResearchPhase -> 可选的人类导航和路线分组
ResearchNode  -> 有界工作、依赖血缘、尝试和文件
ResearchClaim -> 科学陈述、预测、反证条件和状态
```

Phase 包含通用 map 对象身份和 metadata、标题、目标及 Node 反向索引，不是生命周期、
权限或 Gate。Node 可以通过可选 `phase_id` 属于至多一个已有 Phase；跨 Phase 依赖有效。
Node 拥有一个 bounded objective 和主交付物，记录 `claim_ids`、`dependency_ids`、
`finding_ids`、`gate_ids`、`attempt_refs`、`artifact_refs`、明确 state 和可选终态结果。
保持同一目标的重试留在该 Node 的 `attempts/` 下；问题或交付物改变时创建新的依赖 Node。

Claim 独立于执行。Node 产出统一的 `Finding`，按 `kind` 特化为 `FactFinding` 或
`IssueFinding`；Gate 及其评估记录在 map 中，但不会自动改变 Claim 或 Node 状态。

## 权威边界

Root Agent 选择问题、方法、替代方案、反例、回溯和停止条件。ChangeSet 调用方提供
工作区内的科学对象 ID；Research Kernel 校验 ID、引用、schema 和图不变量，应用
ChangeSet 并持久化规范状态。Compute、Render、Report、远程控制、导入和通知是确定性
工具；Review 只提供 advisory 评估。

TS Web、报告和 context 都直接消费完整的 canonical ResearchMap，不是第二套状态存储。
客户端可以聚焦展示或上下文，但不定义另一种科学模型。只有 ChangeSet apply 能改变
规范科学状态；Phase 不授权操作；Node 和 Claim 图分别保持无环且语义不同。

## 结果

需要时，用户可以沿 Phase 定位研究叙事和文件；多个 Node 可以测试同一 Claim 而不复制
假设。代价是增加一个可选 Phase 类和 Node 的可空 `phase_id` 字段，但 Phase 的 schema
保持狭窄，不增加流程语义。
