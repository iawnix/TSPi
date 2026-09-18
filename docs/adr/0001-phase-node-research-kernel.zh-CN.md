# ADR 0001：Phase 与 ResearchNode 内核

[English](0001-phase-node-research-kernel.md) | 简体中文

- 状态：已接受
- 日期：2026-08-23

## 背景

研究叙事、可执行工作和科学命题需要分开。一个对象不应同时承担导航、计算产物、
依赖血缘和 Claim 语义，否则会复制状态并把标签误作流程策略。

## 决定

Research Kernel 使用三个正交层次：

```text
ResearchPhase -> 人类导航和路线分组
ResearchNode  -> 有界工作、依赖血缘、尝试和文件
Claim         -> 科学陈述、假设、反证条件和状态
```

Phase 只有 ID、标题、目标、来源和时间，不是生命周期、权限或 Gate。每个 Node 恰好
属于一个 Phase；跨 Phase 依赖有效。Node 拥有一个 bounded objective 和主交付物，记录
依赖、Claim 范围、artifact root 和终态结果。保持同一目标的重试留在该 Node 的
`attempts/` 下；问题或交付物改变时创建新的依赖 Node。

Claim 独立于执行。Hypothesis 通常是 `status=proposed` 的 Claim；Observation 是有
产物来源的不可变语义值；ProofSpec 在评估前冻结。验证不会选择下一个 Node，Acceptance
也是与 Claim 状态分开的 revision-bound 评估。

## 权威边界

Root Agent 选择问题、方法、替代方案、反例、回溯和停止条件。Research Kernel 独占
分配 ID、校验引用和 schema、应用 Decision 并持久化规范状态。Compute、Render、Report、
远程控制、导入和通知是确定性工具；Review 只提供 advisory 评估。

TS Web、报告和 context 都是只读 projection，不是第二套状态存储。只有 Decision apply
能改变规范科学状态；Phase 不授权操作；Node 和 Claim 图分别保持无环且语义不同。

## 结果

用户可以沿 Phase 定位研究叙事和文件，多个 Node 可以测试同一 Claim 而不复制假设。
代价是创建 Node 时需要 `phaseRef`，但 Phase 的 schema 保持狭窄，不增加流程语义。
