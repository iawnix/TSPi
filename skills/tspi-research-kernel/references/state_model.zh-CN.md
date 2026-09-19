# ResearchMap 状态模型

`ResearchMap` 是一个研究项目的规范类型化状态。序列化文件为 `research_map.json`；
`ResearchMap.to_dict()` 的格式由 Root 与 TS Web 直接消费。Kernel 加载、校验并原子保存
同一个对象。

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

`Finding` 是共同数据结构，应使用其专用类型而不是发明平行证据记录。
`GateEvaluation` 保存 verdict（`pass`、`fail`、`inconclusive`、`blocked`）、时间戳、
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
```

`ts_state` 暴露相应的有边界模式（`map`、`summary`、`detail`、`locate`、`validate`、
`operations`），以及计算模式（`artifacts`、`capabilities`、`runs`）。交互式读取使用
`/research`。所有变更都使用由 Kernel 实现、通过 `ts_change` 暴露的
`research.change`。

不要直接编辑 `research_map.json`。ChangeSet 在隔离副本上校验，只递增一次
`revision`，原子写入，并追加一条小型 transaction receipt。无效变更不会触碰之前的
revision。
