---
name: research-state
description: 读取、校验并原子更新由 Phase、Claim、Node、Finding、Gate、关系与焦点组成的 TSPi 规范 ResearchMap。
---

# TSPi Research State

[English version](SKILL.md)

当任务涉及项目研究状态、对象查询、ResearchMap 校验、有界 Research Memory 读取，或通过
`research_read`、`research_change` 执行原子变更时使用本 Skill。研究 workspace 必须具备
`workspace_manifest.json`（`research_state_workspace_2`）、`research_map/context.json`
（`research_map_context_2`）和 `lifecycle/liveness.json`（`research_liveness_2`）。Context
始终包含数组 collection：`phases`、`claims`、`nodes`、`findings`、`gates`、
`claim_relations`、`attempts`、`artifacts`、`evidence_links`、`lifecycle_actions`、
`claim_assessments`、`claim_revisions`、`strategy_plans`、`strategy_reviews`、`attempt_interpretations`；`focus.claim_ids` 和
`focus.node_ids` 也必须是数组。`memory/index.json` 使用 `research_memory_index_1`，只是
metadata/lifecycle projection，不是第二个 ResearchMap 权威。Decision 记录和 Evidence
Registry 由 Research State 管理，通过 `research_read` 的 `decisions` 与 `evidence` mode 暴露
（内部 command ID 为 `research.decisions` 与 `research.evidence`）。

`ResearchClaim`、`ResearchNode`、`Finding` 与 `Gate` 是核心研究对象。
`FactFinding` 和 `IssueFinding` 是 Finding 的类型化实现；`NodeGate` 和 `ClaimGate`
是 Gate 的类型化实现。`ResearchPhase` 只是可选的导航分组，不是必需的生命周期层。
Node 的状态与结果独立于 Claim 状态表达研究进展。

读取时选择足以回答问题的最小 `research_read` 模式。写入陌生操作前先查询
`mode=operations`。所有修改都以显式 ChangeSet 通过 `research_change` 提交；当过期写入不安全时
使用 `expected_revision`。Host 会在发往 Research State 的内部请求中附加 `principal=root_agent` 和
`authority=kernel_write`；这两个 authority 字段不是公共 tool 参数。不要直接编辑 canonical 文档，
也不要访问旧 JSON/SQLite 存储。

ChangeSet 的 `type` 必须是
`references/decision_contract.zh-CN.md` 中的 canonical 操作名，不要编造领域专用操作名。
例如，机理假设使用 `create_claim`，有界机理研究使用 `create_node`。新 Claim 只能从 `proposed` 开始；科学状态通过带理由和已登记证据的 `assess_claim` 更新。Research State
不是 capability catalog；方法说明属于当前 Domain Skill。

Turn 内优先使用 `context` 或 `liveness`；只有当前问题需要时才扩展到 `detail`、`decisions`、
`evidence` 或 `storage`。Attempt 与 Artifact 属于运行证据；在 Interpretation、
Finding 或 Gate 引用前，先登记 manifest 和类型化 link。

Research State 会在提交一个新 revision 前校验引用、反向索引、图的无环性、状态、Gate 规则
以及完整变更后 map。Finding 与 Gate 评估不会隐式改变 Node 或 Claim 状态。Node 要以
`completed` 结果关闭时，所附每个 NodeGate 的最新评估都必须为 `pass`。

## 参考资料

- [state_model.zh-CN.md](references/state_model.zh-CN.md)：对象、状态与不变量。
- [decision_contract.zh-CN.md](references/decision_contract.zh-CN.md)：ChangeSet 操作。
- [workspace_contract.zh-CN.md](references/workspace_contract.zh-CN.md)：持久化与 workspace 所有权。
- [glossary.zh-CN.md](references/glossary.zh-CN.md)：公共术语。

先创建或确认 Claim/Node，再让 research_strategy 引用它们。执行和证据写入前，focus 需要 proposed/active StrategyPlan。遇到 research_decision_required，先读取 mode=context 并补齐策略；前提没有变化时不要重复调用。成功记录 user_input_required 是合法收尾，应等待相关用户输入，不要反复写相同 checkpoint。

普通工具观测不要求写 Finding。需要事实记录时，先用 artifact_create 或 artifact_register 保存原始观测，引用返回的 artifact_id。evidence_reference_unknown 时用 research_read mode=evidence 查证，不能用工具名或自然语言代替 ID。可选诊断失败不阻止独立任务。使用全局 user_input_required 前，先明确原因并阻塞对应 Node；存在独立可执行节点或运行中 Attempt 时 State 会拒绝该 checkpoint。

科学 FactFinding 必须提供 source_refs 和非空 provenance。已登记文献、导入数据和计算产物均可作为证据，不必全部来自 Job；计划和未经检验的假设不能写成 confirmed 事实。terminal checkpoint 前先把完成节点设为 state=closed、outcome=completed，并填写 summary。

通过 `research_interpretation` 记录检查结果后的解释。必填内容为 `interpretation.id`、
`summary`、`outcome`、既有 Claim ID 和真实 Attempt ID。根据证据将 `outcome` 设为
`supports`、`contradicts`、`inconclusive` 或 `invalid`。推荐使用下面的完整嵌套写法，
将示例 ID 和摘要替换为当前工作区的实际记录与判断：

```json
{
  "interpretation": {
    "kind": "result",
    "result_receipt_ref": "result_<exact ID returned by job_collect>",
    "direct_evidence_refs": ["art_<exact artifact returned by job_collect>"],
    "id": "interpretation_result_1",
    "claim_id": "claim_1",
    "attempt_ref": "attempt_1",
    "summary": "The inspected result supports the claim within the tested conditions.",
    "outcome": "supports"
  }
}
```

`claim_id` 与 `attempt_ref` 必须放在 `interpretation` 内。公开字段统一使用 snake_case。
`node_id` 可选，提供时必须指向与该 Claim 关联的既有 Node。
请求的可选 `event_id` 不能代替解释记录必填的 `id`。引用结果文件时用已登记的
`direct_evidence_refs`；执行成功本身不足以证明科学结论成立。

问题修复后通过 research_change 使用 {"type":"resolve_issue","id":"<既有issue ID>","resolution":"<修复内容与验证方式>","source_refs":["<已登记证据ID>"]}。source_refs 可省略，提供时必须存在。该操作保留原 issue 和证据，标记 resolved 并记录修复说明；相关 Node 另行恢复。不要发明 update_finding 或直接改状态文件。ResearchMap 变更会取代旧 checkpoint，恢复后的工作结束前需写新 checkpoint。

计算、报告和交付 Node 均须有完成条件；旧 dependency_ids 要求 closed/completed；类型化 dependencies 可显式允许 finished。completion_exemption 记录有理由的例外，本身不是科学证据。用 `research_read mode=operations query=evaluate_gate` 获取嵌套字段和示例。批次错误含 operation_index 和 target_id；该批次没有任何操作提交。保留回执，修复被拒操作及其前置条件。

用户交付要求用带版本 requirements 保存，与 Claim 和 Node 计划独立。规划前审阅 Host 来源和已安装验收 profile；来源覆盖、不可降低的最低验收、类型化依赖、交付消费和如实停止见 [requirements.zh-CN.md](references/requirements.zh-CN.md)。用 mode=requirements 检查当前履行情况；优先使用 helper 的 prepared_ref 与已登记 artifact_ref，避免转抄摘要。
