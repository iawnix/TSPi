# ResearchMap 状态模型

`ResearchMap` 是一个研究项目的规范类型化科学状态，包含研究对象、执行证据和用户要求。
工作区合同负责文件布局，运行时 command catalog 和 operation schema 负责精确字段及支持的
读写操作。本参考解释对象职责与不变量，不重复维护这些合同。存储边界见
[工作区所有权](workspace_contract.zh-CN.md)，用户交付义务见[要求与交付](requirements.zh-CN.md)。

## 对象

| 对象 | 作用 |
| --- | --- |
| `ResearchPhase` | 相关 Node 的可选导航分组。 |
| `ResearchClaim` | 正在研究的科学陈述。 |
| `ResearchNode` | 有边界的问题与交付物，带有依赖和证据引用。 |
| `Requirement` | 来源于用户的交付要求和最低验收条件，独立于研究计划。 |
| `Finding` | Node 输出；已核验值使用 `FactFinding`，局限、异常、冲突或未决问题使用 `IssueFinding`。 |
| `Gate` | 面向一个 Node 或 Claim 的条件与评估；`NodeGate` 和 `ClaimGate` 表示作用域，不是两套协议。 |

`Finding` 是科学结论的共同数据结构。运行证据由 Research State 单独管理：`AttemptRecord`、
`ArtifactManifest` 与 `EvidenceLink` 构成 Evidence Registry；原始 payload 保留在 Node
目录或外部 Artifact store。`GateEvaluation` 保存 verdict（`pass`、`fail`、`inconclusive`、`blocked`）、时间戳、
message、证据引用与输入 revision。

## 状态与图规则

Claim status 为 `proposed`、`supported`、`contradicted`、`inconclusive` 或
`withdrawn`。Node state 为 `planned`、`active`、`paused`、`blocked` 或 `closed`。
已关闭 Node 的 outcome 为 `completed`、`inconclusive` 或 `stopped`，且不能重新打开。
具有依赖的 Node 只有在全部依赖 closed 且 outcome=completed 后才 ready；inconclusive 或 stopped 不满足依赖。Node 依赖和 Claim 关系必须无环。Node
要以 `completed` 关闭时，所附每个 NodeGate 的最新评估都必须为 `pass`。新 Claim 从 `proposed` 开始，科学状态通过 `assess_claim` 记录理由与证据后更新。

Finding 只属于一个产出它的 Node，并可引用 Claim 与来源。Gate 准确指向一个 Node 或
Claim。Map 维护反向索引（`node_ids`、`finding_ids`、`gate_ids`），并在每次保存时校验。

## 读取与写入

Agent 使用公共 `research_read` 和 `research_change`。运行时 catalog 是当前读取模式的
权威来源，operation catalog 是写入字段的权威来源。陌生写入前查询
`research_read mode=operations`；requirement 工作流参见[要求与交付](requirements.zh-CN.md)。
Strategy、interpretation、checkpoint、Evidence Registry 与 map 变更使用类型化 Research State
command；不要创建通用 memory write。

`research_read mode=evidence` 可选筛选字段为 `record_type`（`attempt`、`artifact` 或 `link`）、
`node_id`、`artifact_id`、`subject_id` 和 `limit`（1--2048）。`record_type=link` 读取
`evidence_links`，不会产生第二套写入协议。

Lifecycle action 和 checkpoint 都由公共 Research State 工具管理。当前操作名和字段以运行时
operation catalog 为准；Research State 仍是唯一写入者。

不要直接编辑 canonical 文档。ChangeSet 在隔离副本上校验，只递增一次 `revision`，并原子更新
context、liveness、memory 与 manifest。Host 会在每次内部 mutation request 中附加 Root Agent 的
`principal` 和 `kernel_write` `authority`；无效变更不会触碰之前的 revision。
