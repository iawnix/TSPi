---
name: tspi-research-kernel
description: 读取、校验并原子更新由 Phase、Claim、Node、Finding、Gate、关系与焦点组成的 TSPi 规范 ResearchMap。
---

# TSPi Research Kernel

[English version](SKILL.md)

当任务涉及项目研究状态、对象查询、ResearchMap 校验或通过 `research.read`、`research.change`
执行原子变更时使用本 Skill。ResearchMap 是 Root 与 TS Web 直接读取的规范数据结构，
不要再建立投影或平行的科学状态注册表。

`ResearchClaim`、`ResearchNode`、`Finding` 与 `Gate` 是核心研究对象。
`FactFinding` 和 `IssueFinding` 是 Finding 的类型化实现；`NodeGate` 和 `ClaimGate`
是 Gate 的类型化实现。`ResearchPhase` 只是可选的导航分组，不是必需的生命周期层。
Node 的状态与结果独立于 Claim 状态表达研究进展。

读取时选择足以回答问题的最小 `research.read` 模式。写入陌生操作前先查询
`mode=operations`。所有修改都以显式 ChangeSet 通过 `research.change` 提交；当过期写入不
安全时使用 `expectedRevision`。不要直接编辑 `research_map.json`。

Kernel 会在提交一个新 revision 前校验引用、反向索引、图的无环性、状态、Gate 规则
以及完整变更后 map。Finding 与 Gate 评估不会隐式改变 Node 或 Claim 状态。Node 要以
`completed` 结果关闭时，所附每个 NodeGate 的最新评估都必须为 `pass`。

## 参考资料

- [state_model.zh-CN.md](references/state_model.zh-CN.md)：对象、状态与不变量。
- [decision_contract.zh-CN.md](references/decision_contract.zh-CN.md)：ChangeSet 操作。
- [workspace_contract.zh-CN.md](references/workspace_contract.zh-CN.md)：持久化与 workspace 所有权。
- [glossary.zh-CN.md](references/glossary.zh-CN.md)：公共术语。
