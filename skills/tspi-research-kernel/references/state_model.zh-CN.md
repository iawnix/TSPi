# ResearchMap 状态模型

`ResearchMap` 是一个研究项目的规范类型化科学状态。Filesystem Research Kernel 将其持久化到
`research_map/context.json`，把生命周期投影到 `lifecycle/liveness.json`；
`workspace_manifest.json` 绑定 identity、mode、root、admission 和 revision。SQLite 与
`research_map.json` 不是运行时权威。

## 对象

| 对象 | 作用 | 重要字段 |
| --- | --- | --- |
| `ResearchPhase` | 相关 Node 的可选导航分组 | `title`、`objective`、`node_ids` |
| `ResearchClaim` | 正在研究的陈述 | `statement`、`status`、`predictions`、`falsifiers`、`node_ids`、`finding_ids`、`gate_ids` |
| `ResearchNode` | 一个有边界的问题与交付物 | `title`、`objective`、`phase_id`、`claim_ids`、`dependency_ids`、`state`、`outcome`、`finding_ids`、`gate_ids`、`artifact_refs`、`attempt_refs` |
| `Finding` | Node 输出 | `node_id`、`statement`、`kind`、`status`、`claim_ids`、`source_refs` |
| `FactFinding` | 已核验值；`kind=fact` | `value`、`datatype`、`unit`、`provenance` |
| `IssueFinding` | 局限、异常、冲突或未决问题；`kind=issue` | `severity`、`resolution` |
| `Gate` | 面向一个 Node 或 Claim 的 criteria 与 evaluations | `scope`、`target_id`、`criteria`、`evaluations` |
| `NodeGate` / `ClaimGate` | Gate 的类型化实现 | `scope=node` / `scope=claim` |

`Finding` 是科学结论的共同数据结构。运行证据由 Kernel 单独管理：`AttemptRecord`、
`ArtifactManifest` 与 `EvidenceLink` 构成 Evidence Registry；原始 payload 保留在 Node
目录或外部 Artifact store。`GateEvaluation` 保存 verdict（`pass`、`fail`、`inconclusive`、`blocked`）、时间戳、
message、证据引用与输入 revision。

## 状态与图规则

Claim status 为 `proposed`、`supported`、`contradicted`、`inconclusive` 或
`withdrawn`。Node state 为 `planned`、`active`、`paused`、`blocked` 或 `closed`。
已关闭 Node 的 outcome 为 `completed`、`inconclusive` 或 `stopped`，且不能重新打开。
具有依赖的 Node 只有在全部依赖关闭后才 ready。Node 依赖和 Claim 关系必须无环。Node
要以 `completed` 关闭时，所附每个 NodeGate 的最新评估都必须为 `pass`。

Finding 只属于一个产出它的 Node，并可引用 Claim 与来源。Gate 准确指向一个 Node 或
Claim。Map 维护反向索引（`node_ids`、`finding_ids`、`gate_ids`），并在每次保存时校验。

## 读取与写入

使用以下共享读取命令：

```text
research.map          完整规范 map
research.summary      进展与焦点
research.detail       一个 phase、claim、node、finding 或 gate
research.locate       在 map 对象中进行文本搜索
research.validate     校验 map
research.operations   当前 ChangeSet operation catalog
research.context      有界 turn context
research.liveness     生命周期诊断
research.decisions    有界 strategy/interpretation/checkpoint 历史
research.evidence     Attempt/Artifact/EvidenceLink 元数据
research.storage      canonical Filesystem Kernel 文档与 revision
```

`research_read` 还暴露上述有界模式与计算模式（`artifacts`、`capabilities`、`runs`）。交互式读取
使用 `/research`。Strategy、interpretation、checkpoint、Evidence Registry 与 map 变更都使用
各自的类型化 Kernel command；不要创建通用 memory write。

不要直接编辑 canonical 文档。ChangeSet 在隔离副本上校验，只递增一次 `revision`，并原子更新
context、liveness、memory 与 manifest。每次 mutation 都要带 Root Agent 的 `principal` 和
`kernel_write` `authority`；无效变更不会触碰之前的 revision。
