# ChangeSet 合同

`research_change` 是 `ResearchMap` 唯一的公共变更边界。其公共 payload 包含
`rationale`、可选 `basis_refs`、可选 `expected_revision` 和非空 `operations` 数组。Host 会在发往
Research State 的内部请求中附加 `principal=root_agent` 与 `authority=kernel_write`；这两个 authority 字段
不是公共 tool 参数。
使用不熟悉的 operation 前，先查询 `research_read mode=operations` 获取当前目录。

## Operations

每个 operation 使用 `type`；创建对象时还要提供显式的项目本地 `id`。引用使用 map 中
已有的 ID。

| 类型 | 必需数据 |
| --- | --- |
| `create_phase` | `id`、`title`；`objective` 可选 |
| `create_claim` | `id`、`statement`；`status=proposed`、`predictions`、`falsifiers` 可选 |
| `create_node` | `id`、`title`、`objective`；`phase_id`、`claim_ids`、`dependency_ids` 可选 |
| `create_finding` | `id`、`node_id`、`statement`、`kind`（`fact` 或 `issue`）；fact 字段为 `value`、`datatype`、`unit`、`provenance`；issue 字段为 `status`、`severity`、`resolution` |
| `create_gate` | `id`、`scope`（`node` 或 `claim`）、`target_id`、`criteria` |
| `evaluate_gate` | `gate_id`、`verdict`、`assessments`；`message`、`evidence_refs` 可选 |
| `set_node_state` | `node_id`、`state`；关闭时还需要 `outcome` 和 `summary` |
| `assess_claim` | `id`、`claim_id`、`verdict`、`reason`；`supported`、`contradicted`、`inconclusive` 还需已登记的 `evidence_refs` |
| `revise_claim` | `source_claim_id`、`target_claim_id`、`revision_id`、`statement`、`reason`；`relation`、`predictions`、`falsifiers` 可选 |
| `relate_claims` | `source_id`、`target_id`、`relation` |
| `set_focus` | `claim_ids`、`node_ids` |

对象 ID 在 map 中必须唯一，引用必须能在拟议变更后的状态中解析。Operation 按顺序运行，
因此后面的 operation 可以引用同一请求中较早创建的对象。一个 ChangeSet 只包含一项连贯
的研究变更；无关变更应使用不同请求。

## 提交规则

Research State 锁定 workspace，加载 canonical context，在存在时检查 `expected_revision`，对独立副本
应用 operations，运行完整 map validator，递增一次 `revision`，并原子更新 context、liveness、
memory 与 manifest。被拒绝的请求不会改变之前的 map。不要直接编辑 canonical 文档。

`create_finding` 记录 Node 已核验的输出，不是通用日志项：支持科学陈述的值使用
`FactFinding`；局限、异常、冲突或未决问题使用 `IssueFinding`。`create_gate` 与
`evaluate_gate` 构成 Gate 生命周期。Claim status 与 Gate verdict 相互独立；Gate 评估
不会静默改变 Claim status。新 Claim 从 `proposed` 开始；科学状态通过 `assess_claim` 记录理由与证据，
不直接设置 status。证据可以是已登记文献、导入数据或计算产物，不要求每次评估都新增计算；
未经检验的计划不能确立科学结论或 confirmed Finding。
`current_assessment_id` 指向当前采用的评估；其证据版本和所需 ClaimGate 必须保持有效。
`assessment_state` 为 `not_assessed`、`current` 或 `needs_review`。证据变化后重新评估，
不要修改旧记录；没有评估的历史 status 仍显示为 `not_assessed`。
通过 `research_read mode=decisions claim_id=<claim_id>` 读取评估理由及证据版本绑定。
新增、修改或重新评估 ClaimGate（包括同版本的新评估）会使当前采用的 `supported` 评估需要复核。
可以先记录条件变化，再另行提交 `assess_claim`，不要求同一 ChangeSet 完成。
`needs_review` 阻止显式与自动 terminal 收尾，但独立研究仍可继续。


启动计算前，为 Node 登记明确 Gate，或在创建 Node 时用 `completion_exemption` 写出豁免理由。
每个条件必须有 `id` 和 `source_type`：`runtime_fact`、`validator_result` 或 `agent_assessment`。
评估通过 `assessments` 覆盖每个条件；机器条件引用真实 `result_receipt_ref`，代理评估必须提供理由。
修改条件用 `revise_gate` 并提供 `criteria` 与 `reason`；保留旧版本，旧评估不再表示新条件通过。

`context` 是有限决策视图，详情使用 `detail`；证据用 `attempt_id`/`job_id` 过滤，`offset`/`limit` 分页。
Claim 的 `source_refs` 与 `constraints` 保存目标来源和约束。不要把模型文字登记成计算原始输出。
最终解释使用 `kind=result`，引用 `job_collect` 返回的回执与直接证据；其他运行放在比较或背景角色。
`kind=observation`、`execution_issue` 引用运行时 `execution_observation_ref`。
更正解释使用 `supersedes_id`。输出版本变化会使依赖解释与机器 Gate 评估需要复核。

完成条件同样适用于报告和邮件节点。每个 agent_assessment 对象必须包含 criterion_id、verdict（pass/fail/inconclusive/blocked）、reason；机器评估提供 criterion_id、result_receipt_ref。用 mode=operations query=evaluate_gate 查询完整 schema 和示例。批次失败按 operation_index/target_id 定位，整批回滚不表示前面的 Gate 评估有错。
