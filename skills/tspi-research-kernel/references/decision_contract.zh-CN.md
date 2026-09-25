# ChangeSet 合同

`research.change` 是 `ResearchMap` 唯一的公共变更边界。它接受一个对象，其中包含
`rationale`、可选 `basisRefs`、可选 `expectedRevision` 和非空 `operations` 数组。
使用不熟悉的 operation 前，先查询 `research.read mode=operations` 获取当前目录。

## Operations

每个 operation 使用 `type`；创建对象时还要提供显式的项目本地 `id`。引用使用 map 中
已有的 ID。

| 类型 | 必需数据 |
| --- | --- |
| `create_phase` | `id`、`title`；`objective` 可选 |
| `create_claim` | `id`、`statement`；`status`、`predictions`、`falsifiers` 可选 |
| `create_node` | `id`、`title`、`objective`；`phase_id`、`claim_ids`、`dependency_ids` 可选 |
| `create_finding` | `id`、`node_id`、`statement`、`kind`（`fact` 或 `issue`）；fact 字段为 `value`、`datatype`、`unit`、`provenance`；issue 字段为 `status`、`severity`、`resolution` |
| `create_gate` | `id`、`scope`（`node` 或 `claim`）、`target_id`；`criteria` 可选 |
| `evaluate_gate` | `gate_id`、`verdict`；`message`、`evidence_refs` 可选 |
| `set_node_state` | `node_id`、`state`；关闭时还需要 `outcome` 和 `summary` |
| `set_claim_status` | `claim_id`、`status` |
| `relate_claims` | `source_id`、`target_id`、`relation` |
| `set_focus` | `claim_ids`、`node_ids` |

对象 ID 在 map 中必须唯一，引用必须能在拟议变更后的状态中解析。Operation 按顺序运行，
因此后面的 operation 可以引用同一请求中较早创建的对象。一个 ChangeSet 只包含一项连贯
的研究变更；无关变更应使用不同请求。

## 提交规则

Kernel 锁定 workspace，加载当前 map，在存在时检查 `expected_revision`，对独立副本应用
operations，运行完整 map validator，递增一次 `revision`，并原子替换
`research_map.json`。被拒绝的请求不会改变之前的 map。不要直接编辑 JSON、transaction
log 或 TS Web 数据。

`create_finding` 记录 Node 已核验的输出，不是通用日志项：支持科学陈述的值使用
`FactFinding`；局限、异常、冲突或未决问题使用 `IssueFinding`。`create_gate` 与
`evaluate_gate` 构成 Gate 生命周期。Claim status 与 Gate verdict 相互独立；Gate 评估
不会静默改变 Claim。
