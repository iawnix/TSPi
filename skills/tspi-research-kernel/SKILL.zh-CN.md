---
name: tspi-research-kernel
description: 读取、校验并原子更新由 Phase、Claim、Node、Finding、Gate、关系与焦点组成的 TSPi 规范 ResearchMap。
---

# TSPi Research Kernel

[English version](SKILL.md)

当任务涉及项目研究状态、对象查询、ResearchMap 校验、有界 Research Memory 读取，或通过
`research_read`、`research_change` 执行原子变更时使用本 Skill。ResearchMap 持久化在
`research_map/context.json`；`workspace_manifest.json`、`lifecycle/liveness.json` 和
`memory/index.json` 共同绑定身份与生命周期，不存在第二个权威存储。Decision 记录和
Evidence Registry 由 Kernel 管理，通过 `research.decisions` 与 `research.evidence` 暴露。

`ResearchClaim`、`ResearchNode`、`Finding` 与 `Gate` 是核心研究对象。
`FactFinding` 和 `IssueFinding` 是 Finding 的类型化实现；`NodeGate` 和 `ClaimGate`
是 Gate 的类型化实现。`ResearchPhase` 只是可选的导航分组，不是必需的生命周期层。
Node 的状态与结果独立于 Claim 状态表达研究进展。

读取时选择足以回答问题的最小 `research_read` 模式。写入陌生操作前先查询
`mode=operations`。所有修改都以包含 `principal=root_agent`、`authority=kernel_write` 的显式
ChangeSet 通过 `research_change` 提交；当过期写入不安全时使用 `expectedRevision`。不要直接编辑
canonical 文档，也不要访问旧 JSON/SQLite 存储。

ChangeSet 的 `type` 必须是
`references/decision_contract.zh-CN.md` 中的 canonical 操作名，不要编造领域专用操作名。
例如，机理假设使用 `create_claim`，有界机理研究使用 `create_node`。当
`research_read` 使用 `mode=capabilities` 时，必须同时提供
`capabilityKind=compute` 或 `capabilityKind=analysis`；这两个字段是条件必填项，不是可随意
省略的标签。

Turn 内优先使用 `context` 或 `liveness`；只有当前问题需要时才扩展到 `detail`、`decisions`、
`evidence`、`storage` 或 `capabilities`。Attempt 与 Artifact 属于运行证据；在 Interpretation、
Finding 或 Gate 引用前，先登记 manifest 和类型化 link。

Kernel 会在提交一个新 revision 前校验引用、反向索引、图的无环性、状态、Gate 规则
以及完整变更后 map。Finding 与 Gate 评估不会隐式改变 Node 或 Claim 状态。Node 要以
`completed` 结果关闭时，所附每个 NodeGate 的最新评估都必须为 `pass`。

## 参考资料

- [state_model.zh-CN.md](references/state_model.zh-CN.md)：对象、状态与不变量。
- [decision_contract.zh-CN.md](references/decision_contract.zh-CN.md)：ChangeSet 操作。
- [workspace_contract.zh-CN.md](references/workspace_contract.zh-CN.md)：持久化与 workspace 所有权。
- [glossary.zh-CN.md](references/glossary.zh-CN.md)：公共术语。
