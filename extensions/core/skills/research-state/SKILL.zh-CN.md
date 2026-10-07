---
name: research-state
description: 读取、校验并原子更新由 Phase、Claim、Node、Finding、Gate、关系与焦点组成的 TSPi 规范 ResearchMap。
---

# TSPi Research State

[English version](SKILL.md)

当任务涉及项目研究状态、对象查询、ResearchMap 校验、有界 Research Memory 读取，或通过
`research_read`、`research_change` 执行原子变更时使用本 Skill。研究 workspace 必须具备
`workspace_manifest.json`（`research_state_workspace_1`）、`research_map/context.json`
（`research_map_context_1`）和 `lifecycle/liveness.json`（`research_liveness_1`）。Context
始终包含数组 collection：`phases`、`claims`、`nodes`、`findings`、`gates`、
`claim_relations`、`attempts`、`artifacts`、`evidence_links`、`lifecycle_actions`、
`strategy_plans`、`strategy_reviews`、`attempt_interpretations`；`focus.claim_ids` 和
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
使用 `expectedRevision`。Host 会在发往 Research State 的内部请求中附加 `principal=root_agent` 和
`authority=kernel_write`；这两个 authority 字段不是公共 tool 参数。不要直接编辑 canonical 文档，
也不要访问旧 JSON/SQLite 存储。

ChangeSet 的 `type` 必须是
`references/decision_contract.zh-CN.md` 中的 canonical 操作名，不要编造领域专用操作名。
例如，机理假设使用 `create_claim`，有界机理研究使用 `create_node`。Research State
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
