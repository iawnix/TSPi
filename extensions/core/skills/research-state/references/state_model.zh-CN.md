# ResearchMap 状态模型

`ResearchMap` 是一个研究项目的规范类型化科学状态。Research State filesystem boundary 将其持久化到
`research_map/context.json`（`schema_version=research_map_context_1`）。有效 Context 始终包含
数组 collection：`phases`、`claims`、`nodes`、`findings`、`gates`、`claim_relations`、
`attempts`、`artifacts`、`evidence_links`、`lifecycle_actions`、`strategy_plans`、
`strategy_reviews`、`attempt_interpretations`；`focus.claim_ids` 与 `focus.node_ids` 也必须是
数组。生命周期投影到 `lifecycle/liveness.json`（`research_liveness_1`）；
`workspace_manifest.json` 绑定 identity、mode、root 和 admission。已废弃的 SQLite 与
`research_map.json` 文件会被拒绝，不是运行时权威。

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

`Finding` 是科学结论的共同数据结构。运行证据由 Research State 单独管理：`AttemptRecord`、
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

Research State command catalog 使用以下内部读取 ID：

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
research.storage      canonical Research State filesystem boundary 文档与 revision
```

Agent 只能调用公共 `research_read`，并通过对应的有界 `mode`（`map`、`summary`、`detail`、
`locate`、`validate`、`operations`、`context`、`liveness`、`decisions`、`evidence` 或
`storage`）访问上述读取。该工具还暴露计算模式（`artifacts`、`capabilities`、`runs`）。交互式读取
使用 `/research`。Strategy、interpretation、checkpoint、Evidence Registry 与 map 变更都使用
各自的类型化 Research State command；不要创建通用 memory write。

`research_read mode=evidence` 可选筛选字段为 `recordType`（`attempt`、`artifact` 或 `link`）、
`nodeId`、`artifactId`、`subjectId` 和 `limit`（1--2048）。`recordType=link` 读取
`evidence_links`，不会产生第二套写入协议。

生命周期动作是通过 `research.change` 管理的 State 记录，`research_checkpoint` 是 turn checkpoint。
使用规范的 `set_lifecycle_action` 和 `resolve_lifecycle_action` 操作，并显式提供 scope、target、
action、status、reason 和 request identity。唯一写入者仍然是 Research State。

不要直接编辑 canonical 文档。ChangeSet 在隔离副本上校验，只递增一次 `revision`，并原子更新
context、liveness、memory 与 manifest。Host 会在每次内部 mutation request 中附加 Root Agent 的
`principal` 和 `kernel_write` `authority`；无效变更不会触碰之前的 revision。
