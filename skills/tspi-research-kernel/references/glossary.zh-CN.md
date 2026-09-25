# 公开术语

[English](glossary.md)

在提示词、工具请求、Finding 和报告中使用以下名称。

| 术语 | 含义 |
| --- | --- |
| Root Agent | 选择研究问题、方法、分支、解释和停止条件。 |
| Research Kernel | 校验并原子持久化一个项目的 `ResearchMap`，不运行科学软件。 |
| ResearchMap | 项目的规范类型化聚合对象，序列化为 `research_map.json`。 |
| ResearchPhase | 相关研究 Node 的导航分组，不拥有独立生命周期。 |
| ResearchClaim | 带有预测、反证条件和状态的待研究陈述。 |
| ResearchNode | 一个有边界的问题和交付物，包含依赖、状态、结果，以及 Claim、Finding、Gate、Attempt、Artifact 引用。 |
| Finding | Node 的产出并存储在 map 中。核验过的值用 `FactFinding`，限制、异常、冲突或未决问题用 `IssueFinding`。 |
| Gate | 绑定一个 Node 或 Claim 的 criteria 与 evaluations。`NodeGate` 与 `ClaimGate` 只是类型化作用域，不是两套协议。 |
| Artifact | Node 所属输入、输出或分析文件的逻辑引用。 |
| Attempt | Node 所属的一次有边界的计算或执行记录。重试仍是 Attempt；问题改变时才创建新 Node。 |
| Compute environment | 绑定 Backend 的命名本地或远端执行环境，用 `compute.environment` 或 `/compute` 查询。 |
| Claim relation | Claim 之间的有向关系，例如支持、冲突或依赖。 |
| ChangeSet | 通过 `research.change` 提交的一组显式 map 操作，由 Kernel 一次校验并提交一个 revision。 |
| Review | 隔离的建议性评估，由 Root 把决定记录回 map。 |
| Skill | Agent 的方法指导，可以选择工具和解释结果，但不拥有规范研究状态。 |
| Backend | 计算使用的科学软件或执行器。 |
| Platform | 远端 Compute environment 使用的传输和调度器细节。 |

使用实时 map 和 operation catalog 中的准确值。原始执行输出、解析诊断、调度器状态
和 Review 建议在 Root 核验并通过 `research.change` 记录为事实或问题前，都保持为独立的
运行数据。
