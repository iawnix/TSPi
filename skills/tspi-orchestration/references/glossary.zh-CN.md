# 公开术语表

[English](glossary.md) | [简体中文](glossary.zh-CN.md)

这些名称用于记录和职责划分。科学问题、方法、标签、关系标签和验证维度使用开放的
科学词汇。

| Term / 术语 | Meaning and owner / 含义与所有者 |
| --- | --- |
| Root Agent | 选择研究问题、方法、分支、解释和停止条件。 |
| Research Kernel | 通过 `ts_change` 校验并提交规范化科学状态。 |
| ResearchPhase | 通过标题和目标组织相关研究问题，便于导航。 |
| ResearchNode (Node) | 一个研究问题或决策事件，包含依赖、Claim 范围和结果。 |
| Claim | 带假设、反证条件、状态和引用记录的科学陈述。 |
| ClaimRelation | Claim 之间已记录的科学关系，如依赖、冲突或替代。 |
| Artifact | 带标识、摘要和来源的输入、输出或分析文件。 |
| Observation candidate | 等待 Root Agent 核对和显式提升的解析器候选值。 |
| Observation | 绑定已验证产物和来源的不可变语义值。 |
| Finding | 明确记录的异常、限制、冲突或未解决问题。 |
| Decision | 由 Root Agent 发起、经内核校验并提交的一次原子变更。 |
| ProofSpec | 在评估前冻结的版本化验证定义，包含内容和注册表摘要。 |
| ValidationResult | 针对明确且绑定摘要的 Observation 得出的确定性结果。只有 `pass` 满足 ProofSpec。 |
| Acceptance record | Claim 及其通过的验证覆盖范围的不可变快照；当前性另行计算。 |
| Attempt | 一个由 Node 所有的计算执行。重试和重新计算仍是 Attempt，新问题才启动 Node。 |
| Compute | 通过操作工具执行 Host 绑定计算计划的子模型。 |
| Review | 对一个 Claim 及其相关材料的独立评估；Root Agent 通过 `ts_reply` 记录处置。 |
| Reviewer role | Review 中版本化的专业角色和预算；当前角色是 `general`，权限仍是建议性。 |

工具名和字段名必须以实时合约为准。`frontier` 和 `delta` 是上下文读取模式；
`$alias` 只在一个 Decision 草稿中有效。修订和摘要绑定记录版本，Root 根据问题和
现有证据选择后续研究操作。

操作失败和科学矛盾是不同结果。调度器、传输、解析器、供应商和合约诊断应留在
操作记录中；只有通过 `ts_change` 核验后，才提升科学观察或限制。
