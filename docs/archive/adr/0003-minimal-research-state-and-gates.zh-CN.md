# ADR 0003：最小 ResearchMap 与 Gate 协议

> Historical archive / 历史归档：本文记录旧设计或一次性验证，不是当前接口合同，也不代表本次重构已通过验收。当前设计见 [Research Memory plan](../../RESEARCH_MEMORY_DESIGN_AND_IMPLEMENTATION_PLAN.zh-CN.md)。

> Historical design record. Research graph and lifecycle guidance is superseded by the [current notebook architecture](../../ARCHITECTURE.md).

[English](0003-minimal-research-state-and-gates.md) | 简体中文

- 状态：已接受
- 日期：2026-09-16

实现修订：当前写入使用 `agent_workspace.py`、共享操作合同与不变量，Web 视图由 `projection.py` 生成。平行 Python 状态类已按 [ADR 0010](0010-retire-parallel-runtimes.zh-CN.md) 删除。

## 决定

`ResearchState` 是一个项目唯一规范 `ResearchMap` 的事务和完整性边界。
`ResearchMap` 是经过 schema 校验的聚合记录，规范序列化位于 `research_map/context.json`；
`memory/index.json` 只是 Research State 拥有的有界元数据/生命周期投影。已废弃的 SQLite/JSON
文件只允许用于诊断，永远不是运行时权威。
`nodes/<node_id>/` 下的执行记录属于执行平面，不是另一套科研状态；有界的决策和证据
元数据与它们一起保存在同一个 Research Memory 后端。

```text
ResearchPhase       导航分组
ResearchClaim       科学命题与状态
ResearchNode        有界问题、工作状态与结果
FactFinding         Node 产出的确认事实
IssueFinding        Node 产出的问题、矛盾或风险
Gate                统一的目标/标准/评估协议
  NodeGate          面向 ResearchNode 的 Gate
  ClaimGate         面向 ResearchClaim 的 Gate
```

`Finding` 使用同一种记录结构，通过 `kind` 及特化字段区分 fact 和
issue。`Gate` 也使用统一的记录合同，`scope` 与目标引用标识它的目标。

`projection.py` 从经过校验的 State context 生成 map 的规范视图。RootAgent 和 TS Web 直接读取这份
投影；它们不会建立第二个科学模型或第二个变更存储。客户端可以为了展示筛选记录，
但筛选结果不是协议也不是变更边界。Decision 记录、Attempt/Artifact manifest 和
Evidence Link 是 Research Memory 元数据，不是重复的 ResearchMap 对象，也不复制原始
payload。

## Gate 语义

每个 Gate 只有一个目标、标准和追加式评估历史。评估记录 `pass`、`fail`、
`inconclusive` 或 `blocked`，并保存检查时间、消息、输入 revision 和证据引用。

`NodeGate` 决定 Node 是否可以以 `completed` 结果关闭；通过 NodeGate 不会改变
任何 Claim。`ClaimGate` 记录当前 Finding 对 Claim 的评估，Claim 状态必须由
RootAgent 通过 ChangeSet 明确修改。Gate 评估不会隐式修改目标对象。

## 责任边界

Research State 校验引用和依赖环、执行 Node 状态转换、处理乐观 revision，并原子提交规范的
filesystem context、liveness 和 metadata projection。它不选择方法、不运行 Backend、不提交远程任务，
也不根据工具成功推断 Claim 状态。

Skill 描述流程和能力，Backend 实现具体科学软件或执行器。Compute Environment 是
绑定 Backend 的命名本地或远端执行环境，Platform 提供远端传输和调度细节。Attempt
和 Artifact 可以通过引用关联 Node，但不会自动成为 map 中的科学对象。

## 不变量

- 所有对象都有稳定 id 和创建时间。
- Node、Claim、Finding、Gate 的引用必须在同一个 map 内解析。
- Node 依赖和 Claim 关系必须无环。
- Node readiness 使用共享依赖判断推导，不持久化。
- 关闭 Node 必须给出明确 outcome。
- 有 NodeGate 时，Node 以 completed 关闭必须有最新通过评估。
- ChangeSet 原子应用，一次只增加一个 map revision。
- `ResearchMap` 是唯一规范科学状态模型。
- `research_map/context.json` 是规范持久化科学状态；`memory/index.json` 是有界投影，
  不是第二套权威。
- Decision、Attempt、Artifact 和 Evidence Link 元数据只在 Research State context/projection 中登记一次；
  原始日志和二进制 payload 保存在外部存储。

旧 registry 集合和 view/graph 协议不再兼容。TS Web、RootAgent、报告及其他客户端都消费
ResearchMap 序列化和有界 Research Memory read model；执行工具可以保留 Attempt/Artifact
文件，但只有 Research State 能登记 manifest，并把类型化 Evidence Link 提升为 Finding 或 Gate
证据引用。
